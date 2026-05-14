"""Credit agent — handles 'see my limit' and 'I want a higher limit'."""
from __future__ import annotations

import logging

from src.agents.base import Agent, AgentReply
from src.core.session import (
    AGENT_CREDIT,
    STATE_AUTHENTICATED,
    STATE_CREDIT_INCREASE,
    Session,
)
from src.models.schemas import (
    CreditLimitResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
)
from src.services.clients import ClientRepository
from src.services.scoring import ScoringService
from src.utils.exceptions import ClientNotFoundError
from src.utils.extract import extract_money

logger = logging.getLogger(__name__)


class CreditAgent(Agent):
    name = AGENT_CREDIT

    def __init__(
        self,
        clients: ClientRepository | None = None,
        scoring: ScoringService | None = None,
    ) -> None:
        self._clients = clients or ClientRepository()
        self._scoring = scoring or ScoringService(self._clients)

    async def get_limit(self, cpf: str) -> CreditLimitResponse:
        client = await self._clients.get_by_cpf(cpf)
        if client is None:
            raise ClientNotFoundError(cpf)
        current_limit = await self._scoring.limit_for_score(client.score)
        return CreditLimitResponse(
            cpf=cpf,
            current_limit=current_limit,
            available_limit=self._scoring.available_from(current_limit),
            score=client.score,
        )

    async def request_increase(
        self, cpf: str, request: LimitIncreaseRequest
    ) -> LimitIncreaseResponse:
        client = await self._clients.get_by_cpf(cpf)
        if client is None:
            raise ClientNotFoundError(cpf)

        current_limit = await self._scoring.limit_for_score(client.score)
        status = await self._scoring.evaluate_request(
            score=client.score,
            current_limit=current_limit,
            requested_limit=request.new_limit,
        )
        await self._clients.append_limit_request(
            cpf=cpf,
            current_limit=current_limit,
            requested_limit=request.new_limit,
            status=status,
        )

        message = _status_message(status, request.new_limit)
        offer_interview = status == "denied"
        return LimitIncreaseResponse(
            cpf=cpf,
            requested_limit=request.new_limit,
            status=status,
            message=message,
            offer_interview=offer_interview,
            interview_message=(
                "Gostaria de fazer uma entrevista financeira para reavaliarmos seu score?"
                if offer_interview
                else None
            ),
        )

    async def handle(self, session: Session, message: str) -> AgentReply:
        assert session.cpf, "Credit agent requires an authenticated session"

        if session.state == STATE_CREDIT_INCREASE:
            return await self._handle_increase(session, message)

        result = await self.get_limit(session.cpf)
        reply = (
            f"Seu limite atual é de R$ {result.current_limit:,.2f} "
            f"(disponível R$ {result.available_limit:,.2f}, score {result.score}). "
            "Quer solicitar um aumento?"
        )
        session.pending_redirect = {
            "target_agent": "credit_increase",
            "reason": "limit_consult_followup",
        }
        return AgentReply(text=reply, next_state=STATE_AUTHENTICATED)

    async def _handle_increase(self, session: Session, message: str) -> AgentReply:
        value = extract_money(message)
        if value is None or value <= 0:
            return AgentReply(
                text="Não consegui ler o valor. Qual seria o novo limite? "
                     "Pode escrever 10000, 10k ou dez mil. "
                     "(Ou diga 'cancelar' para sair.)",
                next_state=STATE_CREDIT_INCREASE,
                humanize=False,
            )
        result = await self.request_increase(
            session.cpf, LimitIncreaseRequest(new_limit=value)
        )
        text = result.message
        redirect: dict[str, str] | None = None
        if result.offer_interview and result.interview_message:
            text = f"{text} {result.interview_message}"
            redirect = {"target_agent": "interview", "reason": "credit_denied"}
            session.pending_redirect = redirect
        else:
            session.pending_redirect = None
        return AgentReply(text=text, next_state=STATE_AUTHENTICATED, redirect=redirect)


def _status_message(status: str, requested_limit: float) -> str:
    if status == "approved":
        return f"Aprovado! Seu novo limite de R$ {requested_limit:,.2f} já está disponível."
    if status == "pending_analysis":
        return (
            "Solicitação em análise. Em até 2 dias úteis você recebe a resposta "
            "(status: pending_analysis)."
        )
    return "Infelizmente o aumento não foi aprovado agora."
