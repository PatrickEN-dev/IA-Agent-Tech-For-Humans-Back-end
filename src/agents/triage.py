"""Triage agent — authenticates the user before any other agent runs."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from src.agents.base import Agent, AgentReply
from src.config import Settings, get_settings
from src.core.session import (
    AGENT_TRIAGE,
    STATE_AUTHENTICATED,
    STATE_COLLECTING_BIRTHDATE,
    STATE_COLLECTING_CPF,
    Session,
)
from src.models.schemas import AuthRequest, AuthResponse
from src.services.auth import AuthService
from src.services.clients import ClientRepository
from src.utils.exceptions import AuthenticationError, MaxAttemptsExceededError
from src.utils.extract import (
    classify_intent_rule_based,
    extract_birthdate,
    extract_cpf,
    is_valid_cpf,
    normalize_cpf,
)

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = (
    "Olá! Bem-vindo ao Banco Ágil. Posso ajudar com: "
    "consultar limite, solicitar aumento de limite, cotação de moedas "
    "ou atualizar seu perfil financeiro. Para começar, qual é o seu CPF?"
)


class TriageAgent(Agent):
    name = AGENT_TRIAGE

    def __init__(
        self,
        clients: ClientRepository | None = None,
        auth: AuthService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._clients = clients or ClientRepository(self._settings)
        self._auth = auth or AuthService(self._settings)
        self._failures: dict[str, int] = defaultdict(int)

    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        """Direct REST authentication (used by /triage/authenticate)."""
        cpf = normalize_cpf(request.cpf)
        self._guard_attempts(cpf)

        if not is_valid_cpf(cpf):
            self._failures[cpf] += 1
            remaining = self._remaining(cpf)
            logger.info("Authentication: invalid CPF format %s***", cpf[:3])
            raise AuthenticationError(remaining_attempts=remaining)

        client = await self._clients.get_by_cpf(cpf)
        if client is None or client.birthdate != request.birthdate:
            self._failures[cpf] += 1
            remaining = self._remaining(cpf)
            logger.info("Authentication failed for CPF %s*** (remaining=%s)", cpf[:3], remaining)
            raise AuthenticationError(remaining_attempts=remaining)

        self._failures[cpf] = 0
        token = self._auth.create_token(cpf)
        intent = (
            classify_intent_rule_based(request.user_message)
            if request.user_message
            else "unknown"
        )
        redirect_intent = intent if intent not in ("unknown", "exit") else None
        logger.info(
            "Authentication succeeded for CPF %s*** (intent=%s)",
            cpf[:3], redirect_intent,
        )
        return AuthResponse(
            authenticated=True,
            token=token,
            redirect_intent=redirect_intent,
            remaining_attempts=self._settings.max_auth_attempts,
        )

    async def handle(self, session: Session, message: str) -> AgentReply:
        if session.state == STATE_COLLECTING_BIRTHDATE:
            return await self._collect_birthdate(session, message)
        return await self._collect_cpf(session, message)

    async def _collect_cpf(self, session: Session, message: str) -> AgentReply:
        cpf = extract_cpf(message)
        if cpf is None or len(cpf) != 11:
            return AgentReply(
                text="Não consegui ler seu CPF. Pode informar os 11 dígitos? "
                     "Pode digitar com ou sem pontos.",
                next_state=STATE_COLLECTING_CPF,
            )
        self._guard_attempts(cpf)
        client = await self._clients.get_by_cpf(cpf)
        if client is None:
            self._failures[cpf] += 1
            return AgentReply(
                text="CPF não encontrado na nossa base. Verifique e tente novamente.",
                next_state=STATE_COLLECTING_CPF,
            )
        session.cpf = cpf
        session.user_name = client.name
        return AgentReply(
            text="CPF confirmado. Agora, qual é a sua data de nascimento? "
                 "Pode usar o formato DD/MM/AAAA.",
            next_state=STATE_COLLECTING_BIRTHDATE,
        )

    async def _collect_birthdate(self, session: Session, message: str) -> AgentReply:
        parts = extract_birthdate(message)
        if parts is None:
            return AgentReply(
                text="Não entendi a data. Pode informar no formato DD/MM/AAAA, "
                     "por exemplo 15/05/1990.",
                next_state=STATE_COLLECTING_BIRTHDATE,
            )
        try:
            day, month, year = parts
            birthdate = date(year, month, day)
        except ValueError:
            return AgentReply(
                text="Essa data não é válida. Pode tentar novamente?",
                next_state=STATE_COLLECTING_BIRTHDATE,
            )

        assert session.cpf is not None
        client = await self._clients.get_by_cpf(session.cpf)
        if client is None or client.birthdate != birthdate:
            self._failures[session.cpf] += 1
            remaining = self._remaining(session.cpf)
            if remaining <= 0:
                return AgentReply(
                    text="Limite de tentativas excedido. Por segurança, tente novamente mais tarde.",
                    next_state=STATE_COLLECTING_BIRTHDATE,
                )
            return AgentReply(
                text=f"Data de nascimento incorreta. Você ainda tem "
                     f"{remaining} tentativa(s).",
                next_state=STATE_COLLECTING_BIRTHDATE,
            )

        session.birthdate = birthdate
        session.token = self._auth.create_token(session.cpf)
        self._failures[session.cpf] = 0
        return AgentReply(
            text=(
                f"Pronto, {client.name}! Você está autenticado. "
                "Posso te ajudar com: ver limite, solicitar aumento, "
                "cotação de moedas ou atualizar seu perfil financeiro. "
                "O que você prefere?"
            ),
            next_state=STATE_AUTHENTICATED,
        )

    def _guard_attempts(self, cpf: str) -> None:
        if self._failures[cpf] >= self._settings.max_auth_attempts:
            raise MaxAttemptsExceededError()

    def _remaining(self, cpf: str) -> int:
        return max(0, self._settings.max_auth_attempts - self._failures[cpf])

    def reset_attempts(self, cpf: str) -> None:
        self._failures[normalize_cpf(cpf)] = 0
