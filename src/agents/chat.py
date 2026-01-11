import logging
from collections import defaultdict
from datetime import date
from enum import Enum
from typing import Optional

from src.config import get_settings
from src.models.schemas import ChatRequest, ChatResponse
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService, NaturalLanguageParser
from src.utils.text_normalizer import (
    normalize_text,
    extract_cpf_from_text,
    parse_date_from_text,
    parse_boolean_response,
)

logger = logging.getLogger(__name__)


class ConversationState(str, Enum):
    WELCOME = "welcome"
    COLLECTING_CPF = "collecting_cpf"
    COLLECTING_BIRTHDATE = "collecting_birthdate"
    AUTHENTICATED = "authenticated"
    INTERVIEW_INCOME = "interview_income"
    INTERVIEW_EMPLOYMENT = "interview_employment"
    INTERVIEW_EXPENSES = "interview_expenses"
    INTERVIEW_DEPENDENTS = "interview_dependents"
    INTERVIEW_DEBTS = "interview_debts"
    INTERVIEW_CONFIRM = "interview_confirm"
    WAITING_LIMIT_VALUE = "waiting_limit_value"
    WAITING_CURRENCY = "waiting_currency"
    GOODBYE = "goodbye"


GREETINGS = ["ola", "oi", "bom dia", "boa tarde", "boa noite", "hey", "hello", "hi", "e ai", "eai", "fala", "salve"]
HELP_WORDS = ["ajuda", "help", "como funciona", "o que voce faz", "pode me ajudar"]
GOODBYE_WORDS = ["sair", "tchau", "adeus", "encerrar", "bye", "exit", "ate logo", "finalizar"]


class SessionData:
    def __init__(self):
        self.state = ConversationState.WELCOME
        self.cpf: Optional[str] = None
        self.birthdate: Optional[date] = None
        self.token: Optional[str] = None
        self.auth_attempts: int = 0
        self.interview_data: dict = {}
        self.pending_currency_from: Optional[str] = None


class ChatAgent:
    def __init__(self):
        self._settings = get_settings()
        self._sessions: dict[str, SessionData] = defaultdict(SessionData)
        self._csv_service = CSVService()
        self._auth_service = AuthService()
        self._llm_service = LLMService()
        self._parser = NaturalLanguageParser()

    def _get_session(self, session_id: str) -> SessionData:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionData()
        return self._sessions[session_id]

    async def process_message(self, request: ChatRequest) -> ChatResponse:
        session = self._get_session(request.session_id)
        message = request.message.strip()
        normalized = normalize_text(message)

        if session.state == ConversationState.GOODBYE:
            session.state = ConversationState.WELCOME
            return self._response(request.session_id, session, "Novo atendimento iniciado. Como posso ajudar?")

        if any(w in normalized for w in GOODBYE_WORDS) and session.state != ConversationState.WELCOME:
            session.state = ConversationState.GOODBYE
            return self._response(request.session_id, session, "Obrigado por usar o Banco Ágil! Até a próxima.")

        if session.state == ConversationState.WELCOME:
            return await self._handle_welcome(request.session_id, session, message, normalized)

        if session.state == ConversationState.COLLECTING_CPF:
            return await self._handle_cpf(request.session_id, session, message, normalized)

        if session.state == ConversationState.COLLECTING_BIRTHDATE:
            return await self._handle_birthdate(request.session_id, session, message, normalized)

        if session.state == ConversationState.AUTHENTICATED:
            return await self._handle_authenticated(request.session_id, session, message, normalized)

        if session.state == ConversationState.WAITING_LIMIT_VALUE:
            return await self._handle_limit_value(request.session_id, session, message)

        if session.state == ConversationState.WAITING_CURRENCY:
            return await self._handle_currency(request.session_id, session, message)

        if session.state in [
            ConversationState.INTERVIEW_INCOME,
            ConversationState.INTERVIEW_EMPLOYMENT,
            ConversationState.INTERVIEW_EXPENSES,
            ConversationState.INTERVIEW_DEPENDENTS,
            ConversationState.INTERVIEW_DEBTS,
            ConversationState.INTERVIEW_CONFIRM,
        ]:
            return await self._handle_interview(request.session_id, session, message)

        return self._response(request.session_id, session, "Desculpe, algo deu errado. Digite 'oi' para recomeçar.")

    async def _handle_welcome(self, session_id: str, session: SessionData, message: str, normalized: str) -> ChatResponse:
        if any(g in normalized for g in GREETINGS):
            session.state = ConversationState.COLLECTING_CPF
            return self._response(
                session_id, session,
                "Olá! Bem-vindo ao Banco Ágil! 😊\n\nSou seu assistente virtual e posso ajudar com:\n- Consultar limite de crédito\n- Solicitar aumento de limite\n- Cotação de moedas\n- Atualizar seu perfil financeiro\n\nPara começar, preciso validar sua identidade. Qual é o seu CPF?"
            )

        if any(h in normalized for h in HELP_WORDS):
            session.state = ConversationState.COLLECTING_CPF
            return self._response(
                session_id, session,
                "Claro! Sou o assistente do Banco Ágil.\n\nPosso ajudar você a:\n• Ver seu limite de crédito\n• Pedir aumento de limite\n• Consultar cotação de moedas\n• Atualizar dados financeiros\n\nPara começar, me informe seu CPF."
            )

        cpf = extract_cpf_from_text(message)
        if cpf and len(cpf) == 11:
            session.cpf = cpf
            session.state = ConversationState.COLLECTING_BIRTHDATE
            return self._response(session_id, session, f"CPF recebido!\n\nAgora, qual é sua data de nascimento? (ex: 15/05/1990)")

        session.state = ConversationState.COLLECTING_CPF
        return self._response(
            session_id, session,
            "Olá! Bem-vindo ao Banco Ágil!\n\nPara começar seu atendimento, por favor informe seu CPF."
        )

    async def _handle_cpf(self, session_id: str, session: SessionData, message: str, normalized: str) -> ChatResponse:
        if any(g in normalized for g in GREETINGS):
            return self._response(session_id, session, "Olá! 😊 Para continuar, preciso do seu CPF.")

        if any(w in normalized for w in ["nao sei", "esqueci", "nao lembro", "onde encontro"]):
            return self._response(
                session_id, session,
                "Sem problemas! Seu CPF tem 11 dígitos e você pode encontrá-lo no RG, CNH ou carteira de trabalho.\n\nQuando tiver, é só digitar aqui."
            )

        cpf = extract_cpf_from_text(message)
        if cpf is None:
            if any(h in normalized for h in HELP_WORDS):
                return self._response(session_id, session, "O CPF é um número de 11 dígitos. Você pode digitar com ou sem pontos e traço.\n\nExemplo: 123.456.789-01 ou 12345678901")
            return self._response(session_id, session, "Não consegui identificar o CPF. Por favor, digite os 11 números.\n\nExemplo: 12345678901")

        if len(cpf) != 11:
            return self._response(session_id, session, f"O CPF deve ter 11 dígitos. Você digitou {len(cpf)}. Tente novamente.")

        session.cpf = cpf
        session.state = ConversationState.COLLECTING_BIRTHDATE
        return self._response(session_id, session, "Perfeito! Recebi seu CPF.\n\nAgora, qual é sua data de nascimento?\n(Pode digitar: 15/05/1990 ou 15 de maio de 1990)")

    async def _handle_birthdate(self, session_id: str, session: SessionData, message: str, normalized: str) -> ChatResponse:
        if any(g in normalized for g in GREETINGS):
            return self._response(session_id, session, "Oi! Estamos quase lá. Só preciso da sua data de nascimento para validar.")

        if any(w in normalized for w in ["nao sei", "esqueci", "nao lembro"]):
            return self._response(session_id, session, "A data de nascimento é necessária para sua segurança. Você pode verificar em um documento como RG ou CNH.")

        date_parts = parse_date_from_text(message)
        if date_parts is None:
            return self._response(session_id, session, "Não entendi a data. Por favor, informe no formato dia/mês/ano.\n\nExemplo: 15/05/1990")

        day, month, year = date_parts
        from datetime import datetime
        current_year = datetime.now().year

        if year < 1900 or year > current_year:
            return self._response(session_id, session, f"O ano parece incorreto. Deve estar entre 1900 e {current_year}.")

        if month < 1 or month > 12:
            return self._response(session_id, session, "O mês deve estar entre 1 e 12.")

        try:
            birthdate_obj = date(year, month, day)
        except ValueError:
            return self._response(session_id, session, "Data inválida. Verifique se o dia existe no mês informado.")

        session.birthdate = birthdate_obj
        return await self._authenticate(session_id, session)

    async def _authenticate(self, session_id: str, session: SessionData) -> ChatResponse:
        client = await self._csv_service.get_client_by_cpf(session.cpf)

        if not client:
            session.auth_attempts += 1
            remaining = self._settings.max_auth_attempts - session.auth_attempts
            if remaining <= 0:
                session.state = ConversationState.GOODBYE
                return self._response(session_id, session, "Acesso bloqueado por excesso de tentativas.\n\nPara suporte: 0800-123-4567")
            session.cpf = None
            session.birthdate = None
            session.state = ConversationState.COLLECTING_CPF
            return self._response(session_id, session, f"Não encontrei esse CPF no sistema.\n\nVocê tem {remaining} tentativa(s). Digite o CPF novamente.")

        client_birthdate = date.fromisoformat(client.data_nascimento)
        if client_birthdate != session.birthdate:
            session.auth_attempts += 1
            remaining = self._settings.max_auth_attempts - session.auth_attempts
            if remaining <= 0:
                session.state = ConversationState.GOODBYE
                return self._response(session_id, session, "Acesso bloqueado por excesso de tentativas.\n\nPara suporte: 0800-123-4567")
            session.birthdate = None
            session.state = ConversationState.COLLECTING_BIRTHDATE
            return self._response(session_id, session, f"A data não confere com nossos registros.\n\nVocê tem {remaining} tentativa(s). Informe a data novamente.")

        session.token = self._auth_service.create_token(session.cpf)
        session.state = ConversationState.AUTHENTICATED
        session.auth_attempts = 0

        return self._response(
            session_id, session,
            f"Autenticado com sucesso! Olá, {client.nome}! 👋\n\nComo posso ajudar?\n\n• \"Ver meu limite\" - consultar crédito\n• \"Quero aumento\" - solicitar mais limite\n• \"Cotação do dólar\" - ver câmbio\n• \"Atualizar perfil\" - entrevista financeira",
            authenticated=True,
            token=session.token
        )

    async def _handle_authenticated(self, session_id: str, session: SessionData, message: str, normalized: str) -> ChatResponse:
        if any(g in normalized for g in GREETINGS):
            return self._response(session_id, session, "Oi! Em que posso ajudar?\n\n• Limite de crédito\n• Aumento de limite\n• Cotação de moedas\n• Atualizar perfil", authenticated=True, token=session.token)

        if any(w in normalized for w in ["limite", "credito", "saldo", "quanto tenho", "meu limite"]):
            return await self._get_credit_limit(session_id, session)

        if any(w in normalized for w in ["aumento", "aumentar", "mais limite", "elevar", "subir"]):
            value, _ = self._parser.parse_limit_value(message)
            if value:
                return await self._request_limit_increase(session_id, session, value)
            session.state = ConversationState.WAITING_LIMIT_VALUE
            return self._response(session_id, session, "Qual valor de limite você gostaria?\n\nPode digitar: 25000, 25k, ou vinte e cinco mil", authenticated=True, token=session.token)

        if any(w in normalized for w in ["cambio", "dolar", "euro", "moeda", "cotacao", "libra", "iene"]):
            currency, _ = self._parser.parse_currency(message)
            if currency:
                return await self._get_exchange_rate(session_id, session, currency)
            session.state = ConversationState.WAITING_CURRENCY
            return self._response(session_id, session, "Qual moeda você quer consultar?\n\n• USD (dólar)\n• EUR (euro)\n• GBP (libra)\n• JPY (iene)", authenticated=True, token=session.token)

        if any(w in normalized for w in ["entrevista", "perfil", "atualizar", "cadastro", "questionario", "dados"]):
            return self._start_interview(session_id, session)

        if any(h in normalized for h in HELP_WORDS):
            return self._response(session_id, session, "Posso ajudar com:\n\n• **Limite**: \"qual meu limite?\"\n• **Aumento**: \"quero aumento de 20k\"\n• **Câmbio**: \"cotação do dólar\"\n• **Perfil**: \"atualizar meus dados\"\n• **Sair**: \"tchau\"", authenticated=True, token=session.token)

        intent = await self._llm_service.classify_intent(message)
        if intent == "credit_limit":
            return await self._get_credit_limit(session_id, session)
        if intent == "request_increase":
            session.state = ConversationState.WAITING_LIMIT_VALUE
            return self._response(session_id, session, "Entendi que você quer aumentar o limite. Qual valor?", authenticated=True, token=session.token)
        if intent == "exchange_rate":
            session.state = ConversationState.WAITING_CURRENCY
            return self._response(session_id, session, "Entendi! Qual moeda você quer consultar?", authenticated=True, token=session.token)
        if intent == "interview":
            return self._start_interview(session_id, session)

        return self._response(session_id, session, "Não entendi bem. Posso ajudar com:\n\n• Ver limite de crédito\n• Solicitar aumento\n• Cotação de moedas\n• Atualizar perfil\n\nO que você precisa?", authenticated=True, token=session.token)

    async def _handle_limit_value(self, session_id: str, session: SessionData, message: str) -> ChatResponse:
        value, error_msg = self._parser.parse_limit_value(message)
        if value is None:
            return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
        session.state = ConversationState.AUTHENTICATED
        return await self._request_limit_increase(session_id, session, value)

    async def _handle_currency(self, session_id: str, session: SessionData, message: str) -> ChatResponse:
        currency, error_msg = self._parser.parse_currency(message)
        if currency is None:
            return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
        session.state = ConversationState.AUTHENTICATED
        return await self._get_exchange_rate(session_id, session, currency)

    async def _get_credit_limit(self, session_id: str, session: SessionData) -> ChatResponse:
        from src.agents.credito import CreditAgent
        credit_agent = CreditAgent()
        result = await credit_agent.get_limit(session.cpf)
        msg = f"**Seu Crédito**\n\n• Score: **{result.score}**\n• Limite Total: **R$ {result.current_limit:,.2f}**\n• Disponível: **R$ {result.available_limit:,.2f}**\n\nPosso ajudar com mais alguma coisa?"
        return self._response(session_id, session, msg, authenticated=True, token=session.token, data={"score": result.score, "limit": result.current_limit, "available": result.available_limit})

    async def _request_limit_increase(self, session_id: str, session: SessionData, value: float) -> ChatResponse:
        from src.agents.credito import CreditAgent
        from src.models.schemas import LimitIncreaseRequest
        credit_agent = CreditAgent()
        request = LimitIncreaseRequest(new_limit=value)
        result = await credit_agent.request_increase(session.cpf, request)
        status_text = {"approved": "Aprovado! ✅", "pending_analysis": "Em análise 🔄", "denied": "Negado ❌"}
        msg = f"**Solicitação de Aumento**\n\nValor: R$ {value:,.2f}\nStatus: {status_text.get(result.status, result.status)}\n\n{result.message}\n\nPosso ajudar com mais alguma coisa?"
        return self._response(session_id, session, msg, authenticated=True, token=session.token, data={"status": result.status, "requested": value})

    async def _get_exchange_rate(self, session_id: str, session: SessionData, currency: str) -> ChatResponse:
        from src.agents.cambio import ExchangeAgent
        exchange_agent = ExchangeAgent()
        result = await exchange_agent.get_rate("BRL", currency)
        msg = f"**Cotação BRL → {currency}**\n\n1 BRL = {result.rate:.4f} {currency}\n\n{result.message}\n\nQuer consultar outra moeda?"
        return self._response(session_id, session, msg, authenticated=True, token=session.token, data={"rate": result.rate, "currency": currency})

    def _start_interview(self, session_id: str, session: SessionData) -> ChatResponse:
        session.interview_data = {}
        session.state = ConversationState.INTERVIEW_INCOME
        return self._response(session_id, session, "Vamos atualizar seu perfil financeiro! Isso pode melhorar seu score.\n\n**Qual é sua renda mensal?**\n\n(Pode digitar: 6000, 6k, ou seis mil)", authenticated=True, token=session.token)

    async def _handle_interview(self, session_id: str, session: SessionData, message: str) -> ChatResponse:
        state = session.state

        if state == ConversationState.INTERVIEW_INCOME:
            value, error_msg = self._parser.parse_income(message)
            if value is None:
                return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
            session.interview_data["renda_mensal"] = value
            session.state = ConversationState.INTERVIEW_EMPLOYMENT
            return self._response(session_id, session, f"Renda: **R$ {value:,.2f}**\n\n**Qual seu tipo de trabalho?**\n\n(CLT, autônomo, MEI, servidor público, desempregado)", authenticated=True, token=session.token)

        if state == ConversationState.INTERVIEW_EMPLOYMENT:
            emp, error_msg = self._parser.parse_employment_type(message)
            if emp is None:
                return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
            session.interview_data["tipo_emprego"] = emp
            session.state = ConversationState.INTERVIEW_EXPENSES
            names = {"CLT": "CLT", "FORMAL": "Formal", "PUBLICO": "Servidor Público", "AUTONOMO": "Autônomo", "MEI": "MEI", "DESEMPREGADO": "Desempregado"}
            return self._response(session_id, session, f"Tipo: **{names.get(emp, emp)}**\n\n**Qual o total de despesas mensais?**\n\n(aluguel, contas, alimentação, etc)", authenticated=True, token=session.token)

        if state == ConversationState.INTERVIEW_EXPENSES:
            value, error_msg = self._parser.parse_expenses(message)
            if value is None:
                return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
            session.interview_data["despesas"] = value
            session.state = ConversationState.INTERVIEW_DEPENDENTS
            return self._response(session_id, session, f"Despesas: **R$ {value:,.2f}**\n\n**Quantos dependentes você tem?**\n\n(filhos, cônjuge sem renda, pais)", authenticated=True, token=session.token)

        if state == ConversationState.INTERVIEW_DEPENDENTS:
            value, error_msg = self._parser.parse_dependents(message)
            if value is None:
                return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
            session.interview_data["num_dependentes"] = value
            session.state = ConversationState.INTERVIEW_DEBTS
            dep_text = "nenhum" if value == 0 else str(value)
            return self._response(session_id, session, f"Dependentes: **{dep_text}**\n\n**Você tem alguma dívida em aberto?**\n\n(sim ou não)", authenticated=True, token=session.token)

        if state == ConversationState.INTERVIEW_DEBTS:
            value, error_msg = self._parser.parse_has_debts(message)
            if value is None:
                return self._response(session_id, session, error_msg, authenticated=True, token=session.token)
            session.interview_data["tem_dividas"] = value
            session.state = ConversationState.INTERVIEW_CONFIRM
            data = session.interview_data
            names = {"CLT": "CLT", "FORMAL": "Formal", "PUBLICO": "Servidor Público", "AUTONOMO": "Autônomo", "MEI": "MEI", "DESEMPREGADO": "Desempregado"}
            summary = f"""**Resumo do seu perfil:**

• Renda: R$ {data['renda_mensal']:,.2f}
• Trabalho: {names.get(data['tipo_emprego'], data['tipo_emprego'])}
• Despesas: R$ {data['despesas']:,.2f}
• Dependentes: {data['num_dependentes']}
• Dívidas: {'Sim' if value else 'Não'}

**Confirma esses dados?** (sim ou não)"""
            return self._response(session_id, session, summary, authenticated=True, token=session.token)

        if state == ConversationState.INTERVIEW_CONFIRM:
            confirmed = parse_boolean_response(message)
            if confirmed is None:
                return self._response(session_id, session, "Não entendi. Os dados estão corretos? (sim ou não)", authenticated=True, token=session.token)
            if not confirmed:
                session.interview_data = {}
                session.state = ConversationState.INTERVIEW_INCOME
                return self._response(session_id, session, "Ok! Vamos recomeçar.\n\n**Qual é sua renda mensal?**", authenticated=True, token=session.token)
            return await self._submit_interview(session_id, session)

        return self._response(session_id, session, "Algo deu errado na entrevista. Digite 'atualizar perfil' para recomeçar.", authenticated=True, token=session.token)

    async def _submit_interview(self, session_id: str, session: SessionData) -> ChatResponse:
        from src.agents.entrevista import InterviewAgent
        from src.models.schemas import InterviewRequest

        interview_agent = InterviewAgent()
        data = session.interview_data

        request = InterviewRequest(
            renda_mensal=data["renda_mensal"],
            tipo_emprego=data["tipo_emprego"],
            despesas=data["despesas"],
            num_dependentes=data["num_dependentes"],
            tem_dividas=data["tem_dividas"],
        )

        result = await interview_agent.submit(session.cpf, request)
        session.state = ConversationState.AUTHENTICATED
        session.interview_data = {}

        score_diff = result.new_score - result.previous_score
        diff_text = f"+{score_diff}" if score_diff >= 0 else str(score_diff)

        msg = f"""**Perfil atualizado com sucesso!** ✅

• Score anterior: {result.previous_score}
• Score atual: **{result.new_score}** ({diff_text})

**Recomendação:** {result.recommendation}

Posso ajudar com mais alguma coisa?"""

        return self._response(session_id, session, msg, authenticated=True, token=session.token, data={"previous_score": result.previous_score, "new_score": result.new_score})

    def _response(self, session_id: str, session: SessionData, message: str, authenticated: bool = False, token: str = None, data: dict = None) -> ChatResponse:
        return ChatResponse(
            session_id=session_id,
            message=message,
            state=session.state.value,
            authenticated=authenticated,
            token=token,
            data=data,
        )
