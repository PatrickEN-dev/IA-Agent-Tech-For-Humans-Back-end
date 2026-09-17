import logging
import re
import time
import uuid
from datetime import date
from enum import Enum
from typing import Optional

from src.agents.cambio import ExchangeAgent
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.config import get_settings
from src.models.schemas import (
    InterviewRequest,
    LimitIncreaseRequest,
    RedirectAction,
    UnifiedChatRequest,
    UnifiedChatResponse,
)
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import BANKING_INTENTS, LLMService
from src.utils.formatting import format_brl, format_datetime_brt
from src.utils.text_normalizer import (
    contains_any,
    count_digits,
    extract_cpf_from_text,
    has_digits,
    normalize_text,
    parse_date_from_text,
)
from src.utils.value_extractor import extract_currency_codes

logger = logging.getLogger(__name__)

CPF_LENGTH = 11
MAX_CUSTOMER_AGE_YEARS = 120

# Depois de tantas respostas nao compreendidas seguidas dentro de um fluxo,
# lembramos o cliente de que ele pode sair com "cancelar".
FLOW_MISSES_BEFORE_HINT = 2
CANCEL_HINT = 'Se preferir, é só dizer "cancelar" para voltar ao menu.'

MENU_ACTIONS = [
    "consultar_limite",
    "solicitar_aumento",
    "cotacao_cambio",
    "atualizar_perfil",
]
CANCEL_ACTION = "cancelar"

SESSION_EXPIRED_NOTICE = (
    "Sua sessão anterior expirou por inatividade, então vamos recomeçar por segurança."
)
TECHNICAL_ERROR_MESSAGE = (
    "Tive um problema técnico ao processar sua solicitação. Pode tentar de novo em "
    "instantes? Se preferir, posso ajudar com outra coisa."
)

MENU_TEXT = (
    "- Consultar limite de crédito\n"
    "- Solicitar aumento de limite\n"
    "- Cotação de moedas\n"
    "- Atualizar perfil financeiro"
)

MENU_INLINE = (
    "Posso te ajudar com: consultar seu limite de crédito, solicitar aumento de limite, "
    "verificar cotação de moedas ou atualizar seu perfil financeiro. O que você prefere?"
)

# Palavras que, no meio de um fluxo (entrevista, aumento, câmbio), significam "quero parar"
CANCEL_PHRASES = [
    "cancelar",
    "cancela",
    "desistir",
    "desisto",
    "deixa pra la",
    "deixa para la",
    "esquece",
    "esqueca",
    "voltar",
    "menu",
    "parar",
    "quero parar",
    "nao quero mais",
    "nao quero continuar",
]

NEGATION_PHRASES = ["nao", "agora nao", "depois", "nunca", "nem", "dispenso"]

# "nao quero aumento", "nao preciso de entrevista": pedido negado logo no inicio da frase
NEGATED_REQUEST_PATTERN = re.compile(r"^(nao|nem)\s+(quero|preciso|desejo|gostaria|vou querer)(?!\w)")

INTENT_LABELS = {
    "credit_limit": "consultar seu limite",
    "request_increase": "solicitar o aumento de limite",
    "exchange_rate": "ver a cotação",
    "interview": "atualizar seu perfil financeiro",
}

REDIRECT_TARGET_INTENT = {
    "credit_increase": "request_increase",
    "interview": "interview",
    "credit": "credit_limit",
}

MIN_AUTO_LIMIT_VALUE = 100.0


class AgentType(str, Enum):
    TRIAGE = "triage"
    CREDIT = "credit"
    INTERVIEW = "interview"
    EXCHANGE = "exchange"


class OrchestratorState(str, Enum):
    WELCOME = "welcome"
    COLLECTING_CPF = "collecting_cpf"
    COLLECTING_BIRTHDATE = "collecting_birthdate"
    AUTHENTICATED = "authenticated"
    CREDIT_FLOW = "credit_flow"
    CREDIT_INCREASE_FLOW = "credit_increase_flow"
    INTERVIEW_FLOW = "interview_flow"
    INTERVIEW_INCOME = "interview_income"
    INTERVIEW_EMPLOYMENT = "interview_employment"
    INTERVIEW_EXPENSES = "interview_expenses"
    INTERVIEW_DEPENDENTS = "interview_dependents"
    INTERVIEW_DEBTS = "interview_debts"
    EXCHANGE_FLOW = "exchange_flow"
    EXCHANGE_FROM = "exchange_from"
    EXCHANGE_TO = "exchange_to"
    GOODBYE = "goodbye"


INTERVIEW_STATES = {
    OrchestratorState.INTERVIEW_FLOW,
    OrchestratorState.INTERVIEW_INCOME,
    OrchestratorState.INTERVIEW_EMPLOYMENT,
    OrchestratorState.INTERVIEW_EXPENSES,
    OrchestratorState.INTERVIEW_DEPENDENTS,
    OrchestratorState.INTERVIEW_DEBTS,
}

EXCHANGE_STATES = {
    OrchestratorState.EXCHANGE_FLOW,
    OrchestratorState.EXCHANGE_FROM,
    OrchestratorState.EXCHANGE_TO,
}

CREDIT_STATES = {
    OrchestratorState.CREDIT_FLOW,
    OrchestratorState.CREDIT_INCREASE_FLOW,
}


class OrchestratorSession:
    def __init__(self, max_history: int = 20):
        self.state = OrchestratorState.WELCOME
        self.cpf: Optional[str] = None
        self.birthdate: Optional[date] = None
        self.token: Optional[str] = None
        self.user_name: Optional[str] = None
        self.current_agent: AgentType = AgentType.TRIAGE
        self.collected_data: dict = {}
        self.pending_redirect: Optional[RedirectAction] = None
        # Intencao dita antes da autenticacao ("quero ver meu limite" -> pede CPF -> mostra limite)
        self.pending_intent: Optional[str] = None
        self.pending_intent_message: Optional[str] = None
        self.conversation_history: list[dict] = []
        self.auth_attempts = 0
        self.locked = False
        # Respostas seguidas nao compreendidas dentro do fluxo atual
        self.flow_misses = 0
        # Aviso a ser prefixado na proxima resposta (ex.: sessao expirada)
        self.pending_notice: Optional[str] = None
        self.last_activity = time.monotonic()
        self._max_history = max_history

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def remember(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self._max_history:
            del self.conversation_history[: -self._max_history]

    def reset_flow(self) -> None:
        self.state = OrchestratorState.AUTHENTICATED
        self.collected_data = {}
        self.flow_misses = 0

    @property
    def in_flow(self) -> bool:
        return self.state in CREDIT_STATES | INTERVIEW_STATES | EXCHANGE_STATES

    @property
    def first_name(self) -> Optional[str]:
        return self.user_name.split()[0] if self.user_name else None


class Orchestrator:
    """Maquina de estados da conversa unificada.

    As dependencias sao injetaveis para que a API compartilhe uma unica instancia
    de cada agente/servico (e para facilitar testes com dubles).
    """

    def __init__(
        self,
        *,
        credit_agent: CreditAgent | None = None,
        interview_agent: InterviewAgent | None = None,
        exchange_agent: ExchangeAgent | None = None,
        csv_service: CSVService | None = None,
        auth_service: AuthService | None = None,
        llm_service: LLMService | None = None,
    ):
        self._settings = get_settings()
        self._sessions: dict[str, OrchestratorSession] = {}
        self._last_cleanup = time.monotonic()

        self._csv_service = csv_service or CSVService()
        self._auth_service = auth_service or AuthService()
        self._llm_service = llm_service or LLMService()
        self._parser = self._llm_service.parser

        self._credit_agent = credit_agent or CreditAgent(self._csv_service)
        self._interview_agent = interview_agent or InterviewAgent(self._csv_service)
        self._exchange_agent = exchange_agent or ExchangeAgent()

    def warmup(self) -> None:
        self._llm_service.warmup()

    # ---------------------------------------------------------------- sessions

    def _get_session(self, session_id: str) -> OrchestratorSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = OrchestratorSession(self._settings.max_conversation_history)
            self._sessions[session_id] = session
        return session

    def _resolve_session(self, requested_id: Optional[str]) -> tuple[str, OrchestratorSession]:
        """Recupera a sessao pedida ou cria uma nova.

        Se o cliente mandou um id que nao conhecemos mais (TTL expirado ou reinicio
        do servidor), avisamos que a conversa recomecou em vez de pedir o CPF do nada.
        """
        if requested_id and requested_id in self._sessions:
            return requested_id, self._sessions[requested_id]

        session_id = requested_id or str(uuid.uuid4())
        session = self._get_session(session_id)
        if requested_id:
            session.pending_notice = SESSION_EXPIRED_NOTICE
        return session_id, session

    def _restart_session(self, session_id: str) -> OrchestratorSession:
        session = OrchestratorSession(self._settings.max_conversation_history)
        session.state = OrchestratorState.COLLECTING_CPF
        self._sessions[session_id] = session
        return session

    def _cleanup_expired_sessions(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        ttl = self._settings.session_ttl_minutes * 60
        expired = [
            sid for sid, s in self._sessions.items() if now - s.last_activity > ttl
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info(f"Expired {len(expired)} idle session(s)")

    # ---------------------------------------------------------------- entrypoints

    async def init_session(self) -> UnifiedChatResponse:
        session_id = str(uuid.uuid4())
        session = self._get_session(session_id)
        session.state = OrchestratorState.COLLECTING_CPF

        welcome_message = (
            "Olá! Bem-vindo ao Banco Ágil!\n\n"
            "Sou seu assistente virtual e posso ajudar com:\n"
            f"{MENU_TEXT}\n\n"
            "Para começar, preciso validar sua identidade.\n"
            "Qual é o seu CPF?"
        )

        return self._build_response(session_id, session, welcome_message)

    async def process_message(self, request: UnifiedChatRequest) -> UnifiedChatResponse:
        self._cleanup_expired_sessions()

        session_id, session = self._resolve_session(request.session_id)
        session.touch()
        message = request.message.strip()

        if session.locked:
            return self._build_response(
                session_id,
                session,
                "Este atendimento foi encerrado por segurança após várias tentativas de "
                "autenticação. Inicie uma nova conversa para tentar novamente.",
            )

        if session.state == OrchestratorState.GOODBYE:
            session = self._restart_session(session_id)

        if session.state == OrchestratorState.WELCOME:
            session.state = OrchestratorState.COLLECTING_CPF

        if len(message) > self._settings.max_message_length:
            return self._build_response(
                session_id,
                session,
                "Sua mensagem ficou longa demais para eu processar. Pode resumir em "
                "poucas palavras o que você precisa?",
                authenticated=bool(session.token),
            )

        session.remember("user", message)

        if not message:
            return self._build_response(
                session_id, session, self._current_prompt(session), authenticated=bool(session.token)
            )

        try:
            return await self._route(session_id, session, message)
        except Exception:
            # Falha em CSV, API externa ou bug interno: nao derruba a conversa com um 500.
            logger.exception("Unhandled error while processing message (state=%s)", session.state)
            if session.token:
                session.reset_flow()
            return self._build_response(
                session_id,
                session,
                TECHNICAL_ERROR_MESSAGE,
                authenticated=bool(session.token),
            )

    async def _route(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        if session.state == OrchestratorState.COLLECTING_CPF:
            return await self._handle_cpf_collection(session_id, session, message)

        if session.state == OrchestratorState.COLLECTING_BIRTHDATE:
            return await self._handle_birthdate_collection(session_id, session, message)

        if session.state == OrchestratorState.AUTHENTICATED:
            return await self._handle_authenticated_message(session_id, session, message)

        if session.state in CREDIT_STATES:
            return await self._handle_credit_flow(session_id, session, message)

        if session.state in INTERVIEW_STATES:
            return await self._handle_interview_flow(session_id, session, message)

        if session.state in EXCHANGE_STATES:
            return await self._handle_exchange_flow(session_id, session, message)

        session.reset_flow()
        return self._build_response(
            session_id, session, f"Desculpe, não entendi. {MENU_INLINE}", authenticated=True
        )

    def _current_prompt(self, session: OrchestratorSession) -> str:
        state = session.state
        if state == OrchestratorState.COLLECTING_CPF:
            return "Para começar, me informe seu CPF (11 dígitos)."
        if state == OrchestratorState.COLLECTING_BIRTHDATE:
            return "Agora preciso da sua data de nascimento (DD/MM/AAAA)."
        if state == OrchestratorState.CREDIT_INCREASE_FLOW:
            return "Qual valor você gostaria de ter como novo limite?"
        if state == OrchestratorState.INTERVIEW_INCOME:
            return "Qual é a sua renda mensal?"
        if state == OrchestratorState.INTERVIEW_EMPLOYMENT:
            return "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?"
        if state == OrchestratorState.INTERVIEW_EXPENSES:
            return "Qual o total das suas despesas mensais?"
        if state == OrchestratorState.INTERVIEW_DEPENDENTS:
            return "Quantos dependentes você tem?"
        if state == OrchestratorState.INTERVIEW_DEBTS:
            return "Você tem alguma dívida em aberto? (sim/não)"
        if state == OrchestratorState.EXCHANGE_FROM:
            return "Qual moeda você quer converter? (USD, EUR, GBP, JPY, ARS)"
        if state == OrchestratorState.EXCHANGE_TO:
            return "Converter para qual moeda?"
        return f"Como posso ajudar?\n{MENU_TEXT}"

    # ---------------------------------------------------------------- auth flow

    async def _classify_pre_auth(self, message: str) -> Optional[str]:
        """Antes da autenticacao: regras sempre; LLM apenas se nao houver digitos."""
        intent = self._llm_service.classify_with_rules(message)
        if intent is None and not has_digits(message):
            intent = await self._llm_service.classify_intent(message)
        return intent

    @staticmethod
    def _is_plausible_birthdate(birthdate: date) -> bool:
        today = date.today()
        if birthdate > today:
            return False
        return today.year - birthdate.year <= MAX_CUSTOMER_AGE_YEARS

    def _register_failed_attempt(self, session: OrchestratorSession) -> bool:
        """Conta uma tentativa de autenticacao falha. Retorna True se a sessao travou."""
        session.auth_attempts += 1
        if session.auth_attempts >= self._settings.max_auth_attempts:
            session.locked = True
            session.state = OrchestratorState.GOODBYE
            logger.warning("Session locked after too many failed authentication attempts")
            return True
        return False

    def _locked_response(self, session_id: str, session: OrchestratorSession) -> UnifiedChatResponse:
        return self._build_response(
            session_id,
            session,
            f"Por segurança, encerrei o atendimento após {self._settings.max_auth_attempts} "
            "tentativas de autenticação sem sucesso. Se precisar, inicie uma nova conversa.",
        )

    async def _handle_cpf_collection(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        cpf = extract_cpf_from_text(message)

        if not cpf:
            intent = await self._classify_pre_auth(message)

            if intent == "goodbye":
                return await self._say_goodbye(session_id, session, message)

            if intent in BANKING_INTENTS:
                session.pending_intent = intent
                session.pending_intent_message = message
                return await self._build_humanized_response(
                    session_id,
                    session,
                    technical_message=(
                        f"Claro! Para {INTENT_LABELS[intent]}, primeiro preciso confirmar "
                        "sua identidade. Qual é o seu CPF?"
                    ),
                    user_message=message,
                )

            if intent == "greeting":
                return await self._build_humanized_response(
                    session_id,
                    session,
                    technical_message="Olá! Para começar, me informe seu CPF.",
                    user_message=message,
                )

            if has_digits(message) and self._register_failed_attempt(session):
                return self._locked_response(session_id, session)

            digits = count_digits(message)
            if 0 < digits < CPF_LENGTH:
                # Digitou um CPF incompleto: dizer quantos digitos vieram ajuda mais que "invalido"
                return self._build_response(
                    session_id,
                    session,
                    f"Encontrei só {digits} dígito{'s' if digits > 1 else ''}, mas o CPF tem "
                    f"{CPF_LENGTH} dígitos. Pode conferir e enviar de novo?",
                )

            return await self._build_humanized_response(
                session_id,
                session,
                technical_message="CPF inválido. Informe os 11 dígitos do seu CPF.",
                user_message=message,
            )

        client = await self._csv_service.get_client_by_cpf(cpf)
        if not client:
            if self._register_failed_attempt(session):
                return self._locked_response(session_id, session)
            return await self._build_humanized_response(
                session_id,
                session,
                technical_message="CPF não encontrado em nossa base. Verifique e tente novamente.",
                user_message=message,
            )

        session.cpf = cpf
        session.user_name = client.nome
        session.state = OrchestratorState.COLLECTING_BIRTHDATE

        return await self._build_humanized_response(
            session_id,
            session,
            technical_message="CPF validado! Agora, qual é a sua data de nascimento?",
            user_message=message,
        )

    async def _handle_birthdate_collection(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        date_parts = parse_date_from_text(message)

        if not date_parts:
            intent = await self._classify_pre_auth(message)

            if intent == "goodbye":
                return await self._say_goodbye(session_id, session, message)

            if intent in BANKING_INTENTS:
                session.pending_intent = intent
                session.pending_intent_message = message
                return await self._build_humanized_response(
                    session_id,
                    session,
                    technical_message=(
                        f"Anotado! Para {INTENT_LABELS[intent]}, só falta confirmar sua "
                        "data de nascimento (DD/MM/AAAA)."
                    ),
                    user_message=message,
                )

            if intent == "greeting":
                return await self._build_humanized_response(
                    session_id,
                    session,
                    technical_message="Olá! Para continuar, me informe sua data de nascimento (DD/MM/AAAA).",
                    user_message=message,
                )

            if has_digits(message) and self._register_failed_attempt(session):
                return self._locked_response(session_id, session)

            return await self._build_humanized_response(
                session_id,
                session,
                technical_message="Formato inválido. Use DD/MM/AAAA.",
                user_message=message,
            )

        try:
            day, month, year = date_parts
            birthdate = date(year, month, day)
        except ValueError:
            if self._register_failed_attempt(session):
                return self._locked_response(session_id, session)
            return await self._build_humanized_response(
                session_id,
                session,
                technical_message="Data inválida. Verifique e tente novamente.",
                user_message=message,
            )

        if not self._is_plausible_birthdate(birthdate):
            # Data no futuro ou idade impossivel: quase sempre erro de digitacao (ano),
            # entao explicamos em vez de so dizer "incorreta".
            if self._register_failed_attempt(session):
                return self._locked_response(session_id, session)
            return self._build_response(
                session_id,
                session,
                f"A data {birthdate.strftime('%d/%m/%Y')} não parece uma data de nascimento "
                "válida. Confere o ano e me envia de novo no formato DD/MM/AAAA?",
            )

        client = await self._csv_service.get_client_by_cpf(session.cpf)
        if client is None or date.fromisoformat(client.data_nascimento) != birthdate:
            if self._register_failed_attempt(session):
                return self._locked_response(session_id, session)
            return await self._build_humanized_response(
                session_id,
                session,
                technical_message="Data de nascimento incorreta. Tente novamente.",
                user_message=message,
            )

        session.birthdate = birthdate
        session.token = self._auth_service.create_token(session.cpf)
        session.state = OrchestratorState.AUTHENTICATED
        session.current_agent = AgentType.TRIAGE
        session.auth_attempts = 0

        greeting = f"Autenticado com sucesso! Olá, {client.nome}!"

        if session.pending_intent:
            intent = session.pending_intent
            original_message = session.pending_intent_message or message
            session.pending_intent = None
            session.pending_intent_message = None
            return await self._dispatch_intent(
                session_id, session, intent, original_message, prefix=greeting
            )

        return await self._build_humanized_response(
            session_id,
            session,
            technical_message=f"{greeting}\n\nComo posso ajudar?\n{MENU_TEXT}",
            user_message=message,
            authenticated=True,
        )

    # ------------------------------------------------------------ authenticated

    async def _handle_authenticated_message(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        # Mensagens com digitos ("20 mil", "15000") sao valores, nao frases ambiguas:
        # nao vale pagar uma chamada de LLM por elas.
        intent = await self._llm_service.classify_intent(
            message, allow_llm=not has_digits(message)
        )

        if session.pending_redirect:
            redirect = session.pending_redirect
            target_intent = REDIRECT_TARGET_INTENT.get(redirect.target_agent or "")

            if intent == "confirm":
                session.pending_redirect = None
                return await self._accept_redirect(session_id, session, redirect, message)

            if redirect.target_agent == "credit_increase" and intent in (None, "credit_limit"):
                # "Deseja solicitar aumento?" respondido direto com o valor ("20 mil")
                value, _ = self._parser.parse_limit_value(message)
                if value is not None and value >= MIN_AUTO_LIMIT_VALUE:
                    session.pending_redirect = None
                    session.current_agent = AgentType.CREDIT
                    return await self._process_increase(session_id, session, value)

            if intent == "reject" or (
                intent == target_intent and self._has_negation(message)
            ):
                session.pending_redirect = None
                return await self._build_humanized_response(
                    session_id,
                    session,
                    technical_message=f"Tudo bem! Posso ajudar com mais alguma coisa?\n{MENU_TEXT}",
                    user_message=message,
                    authenticated=True,
                )

            if intent is None:
                # Nao entendemos; mantem a oferta em pe e pergunta de novo
                label = INTENT_LABELS.get(target_intent or "", "seguir com isso")
                return self._build_response(
                    session_id,
                    session,
                    f"Não entendi bem. Você quer {label}? Responda sim ou não.",
                    authenticated=True,
                )

            # Mudou de assunto: descarta a oferta e segue com a nova intencao
            session.pending_redirect = None

        if intent in BANKING_INTENTS and self._is_negated_request(message):
            # "nao quero aumento" sem oferta pendente: a intencao bancaria nao e um pedido
            return await self._build_humanized_response(
                session_id,
                session,
                technical_message=f"Tudo bem! Posso ajudar com mais alguma coisa?\n{MENU_TEXT}",
                user_message=message,
                authenticated=True,
            )

        return await self._dispatch_intent(session_id, session, intent, message)

    async def _dispatch_intent(
        self,
        session_id: str,
        session: OrchestratorSession,
        intent: Optional[str],
        message: str,
        prefix: str = "",
    ) -> UnifiedChatResponse:
        prefix_text = f"{prefix}\n\n" if prefix else ""

        if intent == "goodbye":
            return await self._say_goodbye(session_id, session, message)

        if intent == "credit_limit":
            return await self._show_limit(session_id, session, prefix_text)

        if intent == "request_increase":
            return await self._start_increase(session_id, session, message, prefix_text)

        if intent == "interview":
            return self._start_interview(session_id, session, prefix_text)

        if intent == "exchange_rate":
            return await self._start_exchange(session_id, session, message, prefix_text)

        if intent == "greeting":
            name = f", {session.first_name}" if session.first_name else ""
            return await self._build_humanized_response(
                session_id,
                session,
                technical_message=f"{prefix_text}Olá{name}! Como posso ajudar?\n{MENU_TEXT}",
                user_message=message,
                authenticated=True,
            )

        if intent == "off_topic":
            return self._build_response(
                session_id,
                session,
                f"{prefix_text}Sou o assistente virtual do Banco Ágil e só consigo ajudar com "
                f"assuntos do banco. Posso te ajudar com:\n{MENU_TEXT}",
                authenticated=True,
            )

        return self._build_response(
            session_id, session, f"{prefix_text}{MENU_INLINE}", authenticated=True
        )

    # ---------------------------------------------------------------- credit

    async def _show_limit(
        self, session_id: str, session: OrchestratorSession, prefix: str = ""
    ) -> UnifiedChatResponse:
        session.current_agent = AgentType.CREDIT
        result = await self._credit_agent.get_limit(session.cpf)

        response_message = (
            f"{prefix}"
            f"Seu limite atual: {format_brl(result.current_limit)}\n"
            f"Disponível: {format_brl(result.available_limit)}\n"
            f"Score: {result.score}\n\n"
            "Deseja solicitar aumento de limite?"
        )

        redirect = RedirectAction(
            should_redirect=True,
            target_agent="credit_increase",
            reason="Usuário pode querer aumentar limite após ver o atual",
            suggested_action="request_increase",
        )
        session.pending_redirect = redirect
        session.reset_flow()
        return self._build_response(
            session_id, session, response_message, authenticated=True, redirect=redirect
        )

    async def _start_increase(
        self, session_id: str, session: OrchestratorSession, message: str, prefix: str = ""
    ) -> UnifiedChatResponse:
        session.current_agent = AgentType.CREDIT

        # "quero aumentar meu limite para 10 mil" -> ja processa, sem perguntar o valor de novo
        value, _ = self._parser.parse_limit_value(message)
        if value is not None and value >= MIN_AUTO_LIMIT_VALUE:
            return await self._process_increase(session_id, session, value, prefix)

        session.state = OrchestratorState.CREDIT_INCREASE_FLOW
        return self._build_response(
            session_id,
            session,
            f"{prefix}Vou te ajudar a solicitar um aumento no seu limite de crédito. "
            "Qual valor você gostaria de ter como novo limite?",
            authenticated=True,
        )

    async def _process_increase(
        self, session_id: str, session: OrchestratorSession, value: float, prefix: str = ""
    ) -> UnifiedChatResponse:
        request = LimitIncreaseRequest(new_limit=value)
        result = await self._credit_agent.request_increase(session.cpf, request)

        response_message = f"{prefix}{result.message}"
        redirect: Optional[RedirectAction] = None

        if result.offer_interview:
            redirect = RedirectAction(
                should_redirect=True,
                target_agent="interview",
                reason="credit_denied",
                suggested_action="complete_interview",
            )
            session.pending_redirect = redirect
            response_message += f"\n\n{result.interview_message}"
        else:
            response_message += "\n\nPosso ajudar com mais alguma coisa?"

        session.reset_flow()
        return self._build_response(
            session_id, session, response_message, authenticated=True, redirect=redirect
        )

    async def _handle_credit_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        if session.state != OrchestratorState.CREDIT_INCREASE_FLOW:
            session.reset_flow()
            return self._build_response(session_id, session, MENU_INLINE, authenticated=True)

        value, help_message = self._parser.parse_limit_value(message)

        if value is None:
            escape = await self._handle_flow_escape(
                session_id, session, message, flow_label="a solicitação de aumento"
            )
            if escape is not None:
                return escape
            return self._flow_help_response(session_id, session, help_message)

        return await self._process_increase(session_id, session, value)

    # ---------------------------------------------------------------- interview

    def _start_interview(
        self, session_id: str, session: OrchestratorSession, prefix: str = ""
    ) -> UnifiedChatResponse:
        session.current_agent = AgentType.INTERVIEW
        session.state = OrchestratorState.INTERVIEW_INCOME
        session.collected_data = {}
        return self._build_response(
            session_id,
            session,
            f"{prefix}Ótimo! Vou te ajudar a atualizar seu perfil financeiro. Com essas "
            "informações, podemos avaliar melhores opções de crédito para você.\n\n"
            "Para começar, qual é a sua renda mensal?",
            authenticated=True,
        )

    async def _handle_interview_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        data = session.collected_data
        state = session.state

        async def not_understood(help_message: str) -> UnifiedChatResponse:
            escape = await self._handle_flow_escape(
                session_id, session, message, flow_label="a entrevista"
            )
            if escape is not None:
                return escape
            return self._flow_help_response(session_id, session, help_message)

        if state in (OrchestratorState.INTERVIEW_FLOW, OrchestratorState.INTERVIEW_INCOME):
            value, help_message = self._parser.parse_income(message)
            if value is None:
                return await not_understood(help_message)
            data["renda_mensal"] = value
            session.state = OrchestratorState.INTERVIEW_EMPLOYMENT
            return self._build_response(
                session_id,
                session,
                "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?",
                authenticated=True,
            )

        if state == OrchestratorState.INTERVIEW_EMPLOYMENT:
            emp_type, help_message = self._parser.parse_employment_type(message)
            if emp_type is None:
                return await not_understood(help_message)
            data["tipo_emprego"] = emp_type
            session.state = OrchestratorState.INTERVIEW_EXPENSES
            return self._build_response(
                session_id,
                session,
                "Qual o total das suas despesas mensais?",
                authenticated=True,
            )

        if state == OrchestratorState.INTERVIEW_EXPENSES:
            value, help_message = self._parser.parse_expenses(message)
            if value is None:
                return await not_understood(help_message)
            data["despesas"] = value
            session.state = OrchestratorState.INTERVIEW_DEPENDENTS
            return self._build_response(
                session_id, session, "Quantos dependentes você tem?", authenticated=True
            )

        if state == OrchestratorState.INTERVIEW_DEPENDENTS:
            value, help_message = self._parser.parse_dependents(message)
            if value is None:
                return await not_understood(help_message)
            data["num_dependentes"] = value
            session.state = OrchestratorState.INTERVIEW_DEBTS
            return self._build_response(
                session_id,
                session,
                "Você tem alguma dívida em aberto? (sim/não)",
                authenticated=True,
            )

        if state == OrchestratorState.INTERVIEW_DEBTS:
            has_debts, help_message = self._parser.parse_has_debts(message)
            if has_debts is None:
                return await not_understood(help_message)
            data["tem_dividas"] = has_debts

            interview_request = InterviewRequest(
                renda_mensal=data["renda_mensal"],
                tipo_emprego=data["tipo_emprego"],
                despesas=data["despesas"],
                num_dependentes=data["num_dependentes"],
                tem_dividas=data["tem_dividas"],
            )
            result = await self._interview_agent.submit(session.cpf, interview_request)

            session.reset_flow()

            redirect = RedirectAction(
                should_redirect=True,
                target_agent="credit",
                reason="interview_completed",
                suggested_action="check_new_limit",
            )
            session.pending_redirect = redirect

            return self._build_response(
                session_id,
                session,
                "Entrevista concluída!\n\n"
                f"Score anterior: {result.previous_score}\n"
                f"Novo score: {result.new_score}\n"
                f"{self._describe_score_change(result.previous_score, result.new_score)}\n\n"
                f"{result.recommendation}\n\n"
                "Deseja consultar seu novo limite de crédito?",
                authenticated=True,
                redirect=redirect,
            )

        session.state = OrchestratorState.INTERVIEW_INCOME
        return self._build_response(
            session_id, session, "Vamos continuar. Qual sua renda mensal?", authenticated=True
        )

    # ---------------------------------------------------------------- exchange

    async def _start_exchange(
        self, session_id: str, session: OrchestratorSession, message: str, prefix: str = ""
    ) -> UnifiedChatResponse:
        session.current_agent = AgentType.EXCHANGE
        session.collected_data = {}

        codes = extract_currency_codes(message)

        if len(codes) >= 2:
            return await self._answer_rate(session_id, session, codes[0], codes[1], prefix)

        if len(codes) == 1:
            if codes[0] != "BRL":
                # "cotação do dólar" -> responde direto em reais, sem duas perguntas
                return await self._answer_rate(session_id, session, codes[0], "BRL", prefix)
            session.collected_data["from_currency"] = "BRL"
            session.state = OrchestratorState.EXCHANGE_TO
            return self._build_response(
                session_id,
                session,
                f"{prefix}Converter BRL (Real) para qual moeda? USD, EUR, GBP, JPY ou ARS.",
                authenticated=True,
            )

        session.state = OrchestratorState.EXCHANGE_FROM
        return self._build_response(
            session_id,
            session,
            f"{prefix}Qual moeda você quer converter? (USD, EUR, GBP, etc.)",
            authenticated=True,
        )

    async def _answer_rate(
        self,
        session_id: str,
        session: OrchestratorSession,
        from_currency: str,
        to_currency: str,
        prefix: str = "",
    ) -> UnifiedChatResponse:
        result = await self._exchange_agent.get_rate(from_currency, to_currency)

        response_message = (
            f"{prefix}{result.message}\n"
            f"Atualizado em: {format_datetime_brt(result.timestamp)} (Brasília)\n\n"
            "Quer a cotação de outra moeda ou posso ajudar com mais alguma coisa?"
        )

        session.reset_flow()
        return self._build_response(session_id, session, response_message, authenticated=True)

    async def _handle_exchange_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        codes = extract_currency_codes(message)

        if not codes:
            escape = await self._handle_flow_escape(
                session_id, session, message, flow_label="a consulta de câmbio"
            )
            if escape is not None:
                return escape
            options = (
                "BRL, USD, EUR, GBP, JPY ou ARS"
                if session.state == OrchestratorState.EXCHANGE_TO
                else "USD, EUR, GBP, JPY ou ARS"
            )
            return self._flow_help_response(
                session_id, session, f"Moeda não reconhecida. Use: {options}."
            )

        if session.state == OrchestratorState.EXCHANGE_TO:
            from_currency = session.collected_data.get("from_currency", "USD")
            to_currency = codes[0]
            if to_currency == from_currency and len(codes) > 1:
                to_currency = codes[1]
            return await self._answer_rate(session_id, session, from_currency, to_currency)

        # EXCHANGE_FROM (ou estado generico de cambio)
        if len(codes) >= 2:
            return await self._answer_rate(session_id, session, codes[0], codes[1])

        if codes[0] == "BRL":
            session.collected_data["from_currency"] = "BRL"
            session.state = OrchestratorState.EXCHANGE_TO
            return self._build_response(
                session_id,
                session,
                "Converter BRL (Real) para qual moeda? USD, EUR, GBP, JPY ou ARS.",
                authenticated=True,
            )

        return await self._answer_rate(session_id, session, codes[0], "BRL")

    # ---------------------------------------------------------------- helpers

    def _flow_help_response(
        self, session_id: str, session: OrchestratorSession, help_message: str
    ) -> UnifiedChatResponse:
        """Resposta de ajuda dentro de um fluxo; apos alguns erros seguidos, lembra do 'cancelar'."""
        session.flow_misses += 1
        if session.flow_misses >= FLOW_MISSES_BEFORE_HINT:
            help_message = f"{help_message}\n\n{CANCEL_HINT}"
        return self._build_response(session_id, session, help_message, authenticated=True)

    @staticmethod
    def _describe_score_change(previous: int, current: int) -> str:
        delta = current - previous
        if delta > 0:
            return f"Seu score subiu {delta} pontos com as informações atualizadas."
        if delta < 0:
            return (
                f"Seu score caiu {-delta} pontos: o novo cálculo pesa renda, despesas, "
                "dependentes e dívidas informados agora."
            )
        return "Seu score se manteve o mesmo."

    def _flow_intent(self, state: OrchestratorState) -> Optional[str]:
        if state in CREDIT_STATES:
            return "request_increase"
        if state in INTERVIEW_STATES:
            return "interview"
        if state in EXCHANGE_STATES:
            return "exchange_rate"
        return None

    async def _handle_flow_escape(
        self,
        session_id: str,
        session: OrchestratorSession,
        message: str,
        flow_label: str,
    ) -> Optional[UnifiedChatResponse]:
        """Permite sair de um fluxo de coleta sem ficar preso em "não entendi o valor".

        Cancelamento explicito ("cancelar", "voltar"), despedida ou uma intencao bancaria
        clara e diferente do fluxo atual encerram a coleta e seguem a nova intencao.
        Usa apenas regras (sem LLM) para manter o fluxo rapido e previsivel.
        """
        normalized = normalize_text(message)

        if contains_any(normalized, CANCEL_PHRASES):
            session.reset_flow()
            return self._build_response(
                session_id,
                session,
                f"Sem problemas, cancelei {flow_label}. Posso ajudar com mais alguma coisa?\n{MENU_TEXT}",
                authenticated=True,
            )

        intent = self._llm_service.classify_with_rules(message)

        if intent == "goodbye":
            session.reset_flow()
            return await self._say_goodbye(session_id, session, message)

        if intent in BANKING_INTENTS and intent != self._flow_intent(session.state):
            session.reset_flow()
            return await self._dispatch_intent(session_id, session, intent, message)

        return None

    async def _accept_redirect(
        self,
        session_id: str,
        session: OrchestratorSession,
        redirect: RedirectAction,
        message: str,
    ) -> UnifiedChatResponse:
        if redirect.target_agent == "interview":
            return self._start_interview(session_id, session)

        if redirect.target_agent == "credit":
            session.current_agent = AgentType.CREDIT
            result = await self._credit_agent.get_limit(session.cpf)
            session.reset_flow()
            return self._build_response(
                session_id,
                session,
                f"Seu novo limite: {format_brl(result.current_limit)}\n"
                f"Disponível: {format_brl(result.available_limit)}\n"
                f"Score: {result.score}\n\n"
                "Posso ajudar com mais alguma coisa?",
                authenticated=True,
            )

        if redirect.target_agent == "credit_increase":
            session.current_agent = AgentType.CREDIT
            session.state = OrchestratorState.CREDIT_INCREASE_FLOW
            return self._build_response(
                session_id,
                session,
                "Qual valor você gostaria de ter como novo limite?",
                authenticated=True,
            )

        return self._build_response(session_id, session, MENU_INLINE, authenticated=True)

    async def _say_goodbye(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        session.state = OrchestratorState.GOODBYE
        name = f", {session.first_name}" if session.first_name else ""
        return await self._build_humanized_response(
            session_id,
            session,
            technical_message=f"Obrigado por usar o Banco Ágil{name}! Até logo.",
            user_message=message,
            authenticated=bool(session.token),
        )

    def _has_negation(self, message: str) -> bool:
        return contains_any(normalize_text(message), NEGATION_PHRASES)

    def _is_negated_request(self, message: str) -> bool:
        return NEGATED_REQUEST_PATTERN.match(normalize_text(message)) is not None

    def _get_available_actions(self, session: OrchestratorSession) -> list[str]:
        if not session.token:
            return ["autenticar"]

        if session.in_flow:
            # No meio de uma coleta, o front pode oferecer um atalho de "cancelar"
            return [CANCEL_ACTION, *MENU_ACTIONS]

        return list(MENU_ACTIONS)

    def _build_response(
        self,
        session_id: str,
        session: OrchestratorSession,
        message: str,
        authenticated: bool = False,
        redirect: Optional[RedirectAction] = None,
    ) -> UnifiedChatResponse:
        if session.pending_notice:
            message = f"{session.pending_notice}\n\n{message}"
            session.pending_notice = None

        session.remember("assistant", message)
        return UnifiedChatResponse(
            session_id=session_id,
            message=message,
            state=session.state.value,
            authenticated=authenticated or session.token is not None,
            token=session.token,
            user_name=session.first_name if session.token else None,
            current_agent=session.current_agent.value,
            available_actions=self._get_available_actions(session),
            redirect_suggestion=redirect,
        )

    async def _build_humanized_response(
        self,
        session_id: str,
        session: OrchestratorSession,
        technical_message: str,
        user_message: str,
        authenticated: bool = False,
        redirect: Optional[RedirectAction] = None,
    ) -> UnifiedChatResponse:
        humanized_message = await self._llm_service.humanize_response(
            user_message=user_message,
            technical_response=technical_message,
            conversation_context=session.conversation_history,
            user_name=session.user_name,
        )
        return self._build_response(
            session_id, session, humanized_message, authenticated, redirect
        )
