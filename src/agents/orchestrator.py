import logging
import uuid
from collections import defaultdict
from datetime import date
from enum import Enum
from typing import Optional

from src.agents.cambio import ExchangeAgent
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.agents.triagem import TriageAgent
from src.config import get_settings
from src.models.schemas import (
    AuthRequest,
    InterviewRequest,
    LimitIncreaseRequest,
    RedirectAction,
    UnifiedChatRequest,
    UnifiedChatResponse,
)
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService
from src.utils.text_normalizer import extract_cpf_from_text, parse_date_from_text
from src.utils.value_extractor import (
    extract_monetary_value,
    extract_currency_code,
    extract_employment_type,
    extract_integer,
)

logger = logging.getLogger(__name__)


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


class OrchestratorSession:
    def __init__(self):
        self.state = OrchestratorState.WELCOME
        self.cpf: Optional[str] = None
        self.birthdate: Optional[date] = None
        self.token: Optional[str] = None
        self.current_agent: AgentType = AgentType.TRIAGE
        self.collected_data: dict = {}
        self.pending_redirect: Optional[RedirectAction] = None
        self.conversation_history: list[dict] = []


class Orchestrator:
    def __init__(self):
        self._settings = get_settings()
        self._sessions: dict[str, OrchestratorSession] = defaultdict(OrchestratorSession)

        self._triage_agent = TriageAgent()
        self._credit_agent = CreditAgent()
        self._interview_agent = InterviewAgent()
        self._exchange_agent = ExchangeAgent()

        self._csv_service = CSVService()
        self._auth_service = AuthService()
        self._llm_service = LLMService()

    def _get_session(self, session_id: str) -> OrchestratorSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = OrchestratorSession()
        return self._sessions[session_id]

    async def init_session(self) -> UnifiedChatResponse:
        session_id = str(uuid.uuid4())
        session = self._get_session(session_id)
        session.state = OrchestratorState.COLLECTING_CPF

        welcome_message = (
            "Olá! Bem-vindo ao Banco Ágil!\n\n"
            "Sou seu assistente virtual e posso ajudar com:\n"
            "- Consultar limite de crédito\n"
            "- Solicitar aumento de limite\n"
            "- Cotação de moedas\n"
            "- Atualizar seu perfil financeiro\n\n"
            "Para começar, preciso validar sua identidade.\n"
            "Qual é o seu CPF?"
        )

        return self._build_response(session_id, session, welcome_message)

    async def process_message(self, request: UnifiedChatRequest) -> UnifiedChatResponse:
        session_id = request.session_id or str(uuid.uuid4())
        session = self._get_session(session_id)
        message = request.message.strip()

        session.conversation_history.append({"role": "user", "content": message})

        if session.state == OrchestratorState.WELCOME:
            session.state = OrchestratorState.COLLECTING_CPF
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Olá! Para começar, informe seu CPF.",
                user_message=message,
            )

        if self._is_exit_command(message):
            session.state = OrchestratorState.GOODBYE
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Obrigado por usar o Banco Ágil! Até logo.",
                user_message=message,
            )

        if session.pending_redirect and self._accepts_redirect(message):
            return await self._handle_redirect_acceptance(session_id, session, message)

        if session.pending_redirect and self._rejects_redirect(message):
            session.pending_redirect = None
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Tudo bem! Posso ajudar com mais alguma coisa? Limite, aumento, câmbio ou perfil.",
                user_message=message,
            )

        response = await self._route_message(session_id, session, message)

        session.conversation_history.append({"role": "assistant", "content": response.message})

        return response

    async def _route_message(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:

        if session.state == OrchestratorState.COLLECTING_CPF:
            return await self._handle_cpf_collection(session_id, session, message)

        if session.state == OrchestratorState.COLLECTING_BIRTHDATE:
            return await self._handle_birthdate_collection(session_id, session, message)

        if session.state == OrchestratorState.AUTHENTICATED:
            return await self._handle_authenticated_message(session_id, session, message)

        if session.state in [
            OrchestratorState.CREDIT_FLOW,
            OrchestratorState.CREDIT_INCREASE_FLOW,
        ]:
            return await self._handle_credit_flow(session_id, session, message)

        if session.state in [
            OrchestratorState.INTERVIEW_FLOW,
            OrchestratorState.INTERVIEW_INCOME,
            OrchestratorState.INTERVIEW_EMPLOYMENT,
            OrchestratorState.INTERVIEW_EXPENSES,
            OrchestratorState.INTERVIEW_DEPENDENTS,
            OrchestratorState.INTERVIEW_DEBTS,
        ]:
            return await self._handle_interview_flow(session_id, session, message)

        if session.state in [
            OrchestratorState.EXCHANGE_FLOW,
            OrchestratorState.EXCHANGE_FROM,
            OrchestratorState.EXCHANGE_TO,
        ]:
            return await self._handle_exchange_flow(session_id, session, message)

        return self._build_response(
            session_id, session,
            "Desculpe, não entendi. Como posso ajudar?"
        )

    async def _handle_cpf_collection(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        cpf = extract_cpf_from_text(message)

        if not cpf or len(cpf) != 11:
            return await self._build_humanized_response(
                session_id, session,
                technical_message="CPF inválido. Informe os 11 dígitos do seu CPF.",
                user_message=message,
            )

        client = await self._csv_service.get_client_by_cpf(cpf)
        if not client:
            return await self._build_humanized_response(
                session_id, session,
                technical_message="CPF não encontrado em nossa base. Verifique e tente novamente.",
                user_message=message,
            )

        session.cpf = cpf
        session.state = OrchestratorState.COLLECTING_BIRTHDATE

        return await self._build_humanized_response(
            session_id, session,
            technical_message="CPF validado! Agora, qual é a sua data de nascimento?",
            user_message=message,
        )

    async def _handle_birthdate_collection(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        date_parts = parse_date_from_text(message)

        if not date_parts:
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Formato inválido. Use DD/MM/AAAA.",
                user_message=message,
            )

        try:
            day, month, year = date_parts
            birthdate = date(year, month, day)
        except ValueError:
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Data inválida. Verifique e tente novamente.",
                user_message=message,
            )

        client = await self._csv_service.get_client_by_cpf(session.cpf)
        client_birthdate = date.fromisoformat(client.data_nascimento)

        if client_birthdate != birthdate:
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Data de nascimento incorreta. Tente novamente.",
                user_message=message,
            )

        session.birthdate = birthdate
        session.token = self._auth_service.create_token(session.cpf)
        session.state = OrchestratorState.AUTHENTICATED
        session.current_agent = AgentType.TRIAGE

        return await self._build_humanized_response(
            session_id, session,
            technical_message=(
                f"Autenticado com sucesso! Olá, {client.nome}!\n\n"
                "Como posso ajudar?\n"
                "- Ver meu limite\n"
                "- Solicitar aumento\n"
                "- Cotação de moedas\n"
                "- Atualizar perfil"
            ),
            user_message=message,
            authenticated=True,
            user_name=client.nome,
        )

    async def _handle_authenticated_message(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        intent = await self._llm_service.classify_intent(message)

        if intent == "credit_limit":
            session.current_agent = AgentType.CREDIT
            result = await self._credit_agent.get_limit(session.cpf)

            response_message = (
                f"Seu limite atual: R$ {result.current_limit:,.2f}\n"
                f"Disponível: R$ {result.available_limit:,.2f}\n"
                f"Score: {result.score}\n\n"
                "Deseja solicitar aumento de limite?"
            )

            session.state = OrchestratorState.AUTHENTICATED
            return self._build_response(session_id, session, response_message, authenticated=True)

        if intent == "request_increase":
            session.current_agent = AgentType.CREDIT
            session.state = OrchestratorState.CREDIT_INCREASE_FLOW
            return self._build_response(
                session_id, session,
                "Vou te ajudar a solicitar um aumento no seu limite de crédito. Qual valor você gostaria de ter como novo limite?",
                authenticated=True
            )

        if intent == "interview":
            session.current_agent = AgentType.INTERVIEW
            session.state = OrchestratorState.INTERVIEW_INCOME
            session.collected_data = {}
            return self._build_response(
                session_id, session,
                "Ótimo! Vou te ajudar a atualizar seu perfil financeiro. Com essas informações, podemos avaliar melhores opções de crédito para você.\n\nPara começar, qual é a sua renda mensal?",
                authenticated=True
            )

        if intent == "exchange_rate":
            session.current_agent = AgentType.EXCHANGE
            session.state = OrchestratorState.EXCHANGE_FROM
            return self._build_response(
                session_id, session,
                "Qual moeda você quer converter? (USD, EUR, GBP, etc.)",
                authenticated=True
            )

        return self._build_response(
            session_id, session,
            "Posso te ajudar com: consultar seu limite de crédito, solicitar aumento de limite, verificar cotação de moedas ou atualizar seu perfil financeiro. O que você prefere?",
            authenticated=True
        )

    async def _handle_credit_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        if session.state == OrchestratorState.CREDIT_INCREASE_FLOW:
            value = extract_monetary_value(message)

            if value is None:
                return self._build_response(
                    session_id, session,
                    "Não consegui identificar o valor. Pode me informar quanto você gostaria de limite? Por exemplo: 10000, 10k ou dez mil.",
                    authenticated=True
                )

            request = LimitIncreaseRequest(new_limit=value)
            result = await self._credit_agent.request_increase(session.cpf, request)

            response_message = result.message

            if result.offer_interview:
                session.pending_redirect = RedirectAction(
                    should_redirect=True,
                    target_agent="interview",
                    reason="credit_denied",
                    suggested_action="complete_interview"
                )
                response_message += f"\n\n{result.interview_message}"

            session.state = OrchestratorState.AUTHENTICATED
            return self._build_response(
                session_id, session,
                response_message,
                authenticated=True,
                redirect=session.pending_redirect
            )

        return self._build_response(
            session_id, session,
            "Como posso ajudar?",
            authenticated=True
        )

    async def _handle_interview_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:

        if session.state == OrchestratorState.INTERVIEW_INCOME:
            value = extract_monetary_value(message)
            if value is None:
                return self._build_response(
                    session_id, session,
                    "Qual sua renda mensal? Ex: 5000, 5k.",
                    authenticated=True
                )
            session.collected_data["renda_mensal"] = value
            session.state = OrchestratorState.INTERVIEW_EMPLOYMENT
            return self._build_response(
                session_id, session,
                "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?",
                authenticated=True
            )

        if session.state == OrchestratorState.INTERVIEW_EMPLOYMENT:
            emp_type = extract_employment_type(message)
            if emp_type is None:
                return self._build_response(
                    session_id, session,
                    "Opções: CLT, Servidor Público (PUBLICO), Autônomo (AUTONOMO), MEI ou Desempregado.",
                    authenticated=True
                )
            session.collected_data["tipo_emprego"] = emp_type
            session.state = OrchestratorState.INTERVIEW_EXPENSES
            return self._build_response(
                session_id, session,
                "Qual o total das suas despesas mensais?",
                authenticated=True
            )

        if session.state == OrchestratorState.INTERVIEW_EXPENSES:
            value = extract_monetary_value(message)
            if value is None:
                return self._build_response(
                    session_id, session,
                    "Qual o total aproximado? Ex: 2000, 2k.",
                    authenticated=True
                )
            session.collected_data["despesas"] = value
            session.state = OrchestratorState.INTERVIEW_DEPENDENTS
            return self._build_response(
                session_id, session,
                "Quantos dependentes você tem?",
                authenticated=True
            )

        if session.state == OrchestratorState.INTERVIEW_DEPENDENTS:
            value = extract_integer(message)
            if value is None:
                return self._build_response(
                    session_id, session,
                    "Quantas pessoas dependem de você? Se nenhuma, diga 'zero'.",
                    authenticated=True
                )
            session.collected_data["num_dependentes"] = value
            session.state = OrchestratorState.INTERVIEW_DEBTS
            return self._build_response(
                session_id, session,
                "Você tem alguma dívida em aberto? (sim/não)",
                authenticated=True
            )

        if session.state == OrchestratorState.INTERVIEW_DEBTS:
            msg_lower = message.lower()
            if "sim" in msg_lower or "tenho" in msg_lower or "yes" in msg_lower:
                has_debts = True
            elif "nao" in msg_lower or "não" in msg_lower or "no" in msg_lower or "nenhuma" in msg_lower:
                has_debts = False
            else:
                return self._build_response(
                    session_id, session,
                    "Responda sim ou não.",
                    authenticated=True
                )

            session.collected_data["tem_dividas"] = has_debts

            interview_request = InterviewRequest(
                renda_mensal=session.collected_data["renda_mensal"],
                tipo_emprego=session.collected_data["tipo_emprego"],
                despesas=session.collected_data["despesas"],
                num_dependentes=session.collected_data["num_dependentes"],
                tem_dividas=session.collected_data["tem_dividas"],
            )

            result = await self._interview_agent.submit(session.cpf, interview_request)

            session.state = OrchestratorState.AUTHENTICATED
            session.collected_data = {}

            redirect = RedirectAction(
                should_redirect=True,
                target_agent="credit",
                reason="interview_completed",
                suggested_action="check_new_limit"
            )

            return self._build_response(
                session_id, session,
                f"Entrevista concluída!\n\n"
                f"Score anterior: {result.previous_score}\n"
                f"Novo score: {result.new_score}\n\n"
                f"{result.recommendation}\n\n"
                "Deseja consultar seu novo limite de crédito?",
                authenticated=True,
                redirect=redirect
            )

        return self._build_response(
            session_id, session,
            "Vamos continuar. Qual sua renda mensal?",
            authenticated=True
        )

    async def _handle_exchange_flow(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:

        if session.state == OrchestratorState.EXCHANGE_FROM:
            currency = extract_currency_code(message)
            if currency is None:
                return self._build_response(
                    session_id, session,
                    "Moeda não reconhecida. Use: USD, EUR, GBP, JPY ou ARS.",
                    authenticated=True
                )
            session.collected_data["from_currency"] = currency
            session.state = OrchestratorState.EXCHANGE_TO
            return self._build_response(
                session_id, session,
                f"Converter {currency} para qual moeda? (BRL para Real)",
                authenticated=True
            )

        if session.state == OrchestratorState.EXCHANGE_TO:
            currency = extract_currency_code(message)
            if currency is None:
                return self._build_response(
                    session_id, session,
                    "Moeda não reconhecida. Use: BRL, USD, EUR, GBP, JPY ou ARS.",
                    authenticated=True
                )

            from_curr = session.collected_data.get("from_currency", "USD")
            result = await self._exchange_agent.get_rate(from_curr, currency)

            session.state = OrchestratorState.AUTHENTICATED
            session.collected_data = {}

            return self._build_response(
                session_id, session,
                f"Cotação: 1 {from_curr} = {result.rate:.4f} {currency}\n"
                f"Atualizado em: {result.timestamp.strftime('%d/%m/%Y %H:%M')}\n\n"
                "Posso ajudar com mais alguma coisa?",
                authenticated=True
            )

        return self._build_response(
            session_id, session,
            "Qual moeda você quer converter?",
            authenticated=True
        )

    async def _handle_redirect_acceptance(
        self, session_id: str, session: OrchestratorSession, message: str
    ) -> UnifiedChatResponse:
        redirect = session.pending_redirect
        session.pending_redirect = None

        if redirect.target_agent == "interview":
            session.current_agent = AgentType.INTERVIEW
            session.state = OrchestratorState.INTERVIEW_INCOME
            session.collected_data = {}
            return await self._build_humanized_response(
                session_id, session,
                technical_message="Ótimo! Vamos atualizar seu perfil financeiro. Qual é sua renda mensal?",
                user_message=message,
                authenticated=True,
            )

        if redirect.target_agent == "credit":
            session.current_agent = AgentType.CREDIT
            result = await self._credit_agent.get_limit(session.cpf)
            return await self._build_humanized_response(
                session_id, session,
                technical_message=(
                    f"Seu novo limite: R$ {result.current_limit:,.2f}\n"
                    f"Disponível: R$ {result.available_limit:,.2f}\n"
                    f"Score: {result.score}\n\n"
                    "Posso ajudar com mais alguma coisa?"
                ),
                user_message=message,
                authenticated=True,
            )

        return await self._build_humanized_response(
            session_id, session,
            technical_message="Como posso ajudar?",
            user_message=message,
            authenticated=True,
        )

    def _is_exit_command(self, message: str) -> bool:
        exit_words = {"tchau", "sair", "encerrar", "bye", "adeus", "até logo"}
        return any(word in message.lower() for word in exit_words)

    def _accepts_redirect(self, message: str) -> bool:
        accept_words = {"sim", "yes", "ok", "vamos", "quero", "pode", "claro", "aceito"}
        return any(word in message.lower() for word in accept_words)

    def _rejects_redirect(self, message: str) -> bool:
        reject_words = {"nao", "não", "no", "agora não", "depois", "talvez"}
        return any(word in message.lower() for word in reject_words)

    def _get_available_actions(self, session: OrchestratorSession) -> list[str]:
        if not session.token:
            return ["autenticar"]

        return [
            "consultar_limite",
            "solicitar_aumento",
            "cotacao_cambio",
            "atualizar_perfil"
        ]

    def _build_response(
        self,
        session_id: str,
        session: OrchestratorSession,
        message: str,
        authenticated: bool = False,
        redirect: Optional[RedirectAction] = None,
    ) -> UnifiedChatResponse:
        return UnifiedChatResponse(
            session_id=session_id,
            message=message,
            state=session.state.value,
            authenticated=authenticated or session.token is not None,
            token=session.token,
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
        user_name: Optional[str] = None,
    ) -> UnifiedChatResponse:
        """Constrói resposta humanizada usando IA ou fallback"""
        humanized_message = await self._llm_service.humanize_response(
            user_message=user_message,
            technical_response=technical_message,
            conversation_context=session.conversation_history,
            user_name=user_name,
        )

        return UnifiedChatResponse(
            session_id=session_id,
            message=humanized_message,
            state=session.state.value,
            authenticated=authenticated or session.token is not None,
            token=session.token,
            current_agent=session.current_agent.value,
            available_actions=self._get_available_actions(session),
            redirect_suggestion=redirect,
        )
