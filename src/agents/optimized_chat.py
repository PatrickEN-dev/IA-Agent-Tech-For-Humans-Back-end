import logging
import uuid
from collections import defaultdict
from datetime import date
from enum import Enum
from typing import Optional
import hashlib

from src.config import get_settings
from src.models.schemas import ChatRequest, ChatResponse
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService
from src.utils.token_monitor import token_monitor

logger = logging.getLogger(__name__)

BANKING_KEYWORDS = {
    "limite",
    "credito",
    "crédito",
    "cartao",
    "cartão",
    "conta",
    "saldo",
    "banco",
    "pix",
    "transferencia",
    "transferência",
    "emprestimo",
    "empréstimo",
    "financiamento",
    "investimento",
    "poupanca",
    "poupança",
    "cheque",
    "aumento",
    "score",
    "cpf",
    "cadastro",
    "perfil",
    "renda",
    "salario",
    "salário",
    "cambio",
    "câmbio",
    "dolar",
    "dólar",
    "euro",
    "moeda",
    "cotacao",
    "cotação",
    "divida",
    "dívida",
    "parcela",
    "juros",
    "taxa",
    "tarifa",
    "anuidade",
    "entrevista",
    "questionario",
    "questionário",
    "dados",
    "informacoes",
    "informações",
}

FORBIDDEN_TOPICS = {
    "matematica",
    "matemática",
    "calculo",
    "cálculo",
    "historia",
    "história",
    "geografia",
    "ciencia",
    "ciência",
    "tecnologia",
    "programacao",
    "programação",
    "receita",
    "culinaria",
    "culinária",
    "medicina",
    "saude",
    "saúde",
    "esporte",
    "futebol",
    "politica",
    "política",
    "religiao",
    "religião",
    "filosofia",
    "psicologia",
    "entretenimento",
    "filme",
    "musica",
    "música",
    "sentido da vida",
    "relacionamento",
    "amor",
    "familia",
    "família",
    "quanto é",
    "resultado",
    "descobriu",
    "brasil",
    "inteligencia artificial",
    "ia",
    "ai",
    "pedro alvares",
    "cabral",
    "multiplicacao",
    "multiplicação",
    "soma",
    "subtracao",
    "subtração",
    "divisao",
    "divisão",
    "pedro álvares",
}


class ConversationState(str, Enum):
    WELCOME = "welcome"
    COLLECTING_DATA = "collecting_data"
    AUTHENTICATED = "authenticated"
    GOODBYE = "goodbye"


class SessionData:
    def __init__(self):
        self.state = ConversationState.WELCOME
        self.cpf: Optional[str] = None
        self.birthdate: Optional[date] = None
        self.token: Optional[str] = None
        self.conversation_history: list[dict] = []
        self.collected_data: dict = {}


class OptimizedChatAgent:
    def __init__(self):
        self._settings = get_settings()
        self._sessions: dict[str, SessionData] = defaultdict(SessionData)
        self._csv_service = CSVService()
        self._auth_service = AuthService()
        self._llm_service = LLMService()

        self._response_cache: dict[str, str] = {}
        self._cache_max_size = 100

    def _is_banking_related(self, message: str) -> bool:
        message_lower = message.lower()

        for forbidden in FORBIDDEN_TOPICS:
            if forbidden in message_lower:
                return False

        for keyword in BANKING_KEYWORDS:
            if keyword in message_lower:
                return True

        greetings = {
            "oi",
            "olá",
            "ola",
            "bom dia",
            "boa tarde",
            "boa noite",
            "hey",
            "hello",
        }
        if any(greeting in message_lower for greeting in greetings):
            return True

        bank_questions = {
            "que banco",
            "qual banco",
            "banco agil",
            "banco ágil",
            "quem é",
            "o que faz",
        }
        if any(q in message_lower for q in bank_questions):
            return True

        return False

    def _generate_restriction_response(self, session: SessionData) -> str:
        """Gera resposta quando pergunta está fora do escopo bancário"""
        if session.state == ConversationState.AUTHENTICATED:
            return (
                "Sou especializado apenas em serviços bancários. "
                "Posso ajudar com limite de crédito, aumento de limite, "
                "cotação de moedas ou atualização do seu perfil financeiro. "
                "Como posso ajudar?"
            )
        else:
            return (
                "Sou o assistente bancário do Banco Ágil. "
                "Para começar, preciso do seu CPF para validação."
            )

    def _get_session(self, session_id: str) -> SessionData:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionData()
        return self._sessions[session_id]

    async def init_session(self) -> ChatResponse:
        session_id = str(uuid.uuid4())
        session = self._get_session(session_id)
        session.state = ConversationState.COLLECTING_DATA

        welcome_message = (
            "Olá! Bem-vindo ao Banco Ágil! 😊\n\n"
            "Sou seu assistente virtual e posso ajudar com:\n"
            "• Consultar limite de crédito\n"
            "• Solicitar aumento de limite\n"
            "• Cotação de moedas\n"
            "• Atualizar seu perfil financeiro\n\n"
            "Para começar, preciso validar sua identidade.\n"
            "Qual é o seu CPF?"
        )

        return self._response(session_id, session, welcome_message)

    async def process_message(self, request: ChatRequest) -> ChatResponse:
        session_id = request.session_id or str(uuid.uuid4())
        is_new_session = request.session_id is None
        session = self._get_session(session_id)
        message = request.message.strip()

        session.conversation_history.append({"role": "user", "content": message})

        if is_new_session and session.state == ConversationState.WELCOME:
            session.state = ConversationState.COLLECTING_DATA
            welcome_message = (
                "Olá! Bem-vindo ao Banco Ágil! 😊\n\n"
                "Sou seu assistente virtual e posso ajudar com:\n"
                "• Consultar limite de crédito\n"
                "• Solicitar aumento de limite\n"
                "• Cotação de moedas\n"
                "• Atualizar seu perfil financeiro\n\n"
                "Para começar, preciso validar sua identidade.\n"
                "Qual é o seu CPF?"
            )
            return self._response(session_id, session, welcome_message)

        if not is_new_session and not self._is_banking_related(message):
            restricted_response = self._generate_restriction_response(session)
            session.conversation_history.append(
                {"role": "assistant", "content": restricted_response}
            )
            return self._response(
                session_id,
                session,
                restricted_response,
                authenticated=session.state == ConversationState.AUTHENTICATED,
                token=session.token,
            )

        ai_response = await self._generate_ai_response(session, message)

        session.conversation_history.append(
            {"role": "assistant", "content": ai_response}
        )

        return self._response(
            session_id,
            session,
            ai_response,
            authenticated=session.state == ConversationState.AUTHENTICATED,
            token=session.token,
        )

    async def _generate_ai_response(
        self, session: SessionData, user_message: str
    ) -> str:

        cache_key = self._generate_cache_key(session, user_message)
        if cache_key in self._response_cache:
            token_monitor.track_cache_hit()
            return self._response_cache[cache_key]

        system_context = self._build_system_context(session)

        recent_history = session.conversation_history[-3:]

        prompt = self._build_ai_prompt(
            system_context, recent_history, user_message, session
        )

        try:
            response = await self._llm_service.generate_response(prompt)

            self._cache_response(cache_key, response)

            await self._process_ai_response(session, user_message, response)

            return response
        except Exception as e:
            logger.error(f"Erro ao gerar resposta IA: {e}")
            return "Erro técnico. Tente novamente."

    def _build_system_context(self, session: SessionData) -> str:

        base = (
            "Banco Ágil.Bancário(limite/crédito/câmbio/perfil).Tom amigável e claro."
        )

        if session.state == ConversationState.COLLECTING_DATA:
            if not session.cpf:
                return f"{base}Peça CPF educadamente."
            elif not session.birthdate:
                return f"{base}Peça data nascimento."
            return f"{base}Validando..."

        if session.state == ConversationState.AUTHENTICATED:
            return f"{base}Autenticado.Explique opções quando perguntado."

        return base

    def _build_ai_prompt(
        self,
        system_context: str,
        history: list[dict],
        current_message: str,
        session: SessionData,
    ) -> str:
        prompt = f"{system_context}\n"

        for msg in history:
            role = "U" if msg["role"] == "user" else "A"
            prompt += f"{role}:{msg['content']}\n"

        prompt += f"U:{current_message}\n→Responda claro e amigável:"

        return prompt

    async def _process_ai_response(
        self, session: SessionData, user_message: str, ai_response: str
    ) -> None:

        if session.state == ConversationState.COLLECTING_DATA and not session.cpf:
            from src.utils.text_normalizer import extract_cpf_from_text

            cpf = extract_cpf_from_text(user_message)
            if cpf and len(cpf) == 11:
                session.cpf = cpf

        elif (
            session.state == ConversationState.COLLECTING_DATA
            and session.cpf
            and not session.birthdate
        ):
            from src.utils.text_normalizer import parse_date_from_text

            date_parts = parse_date_from_text(user_message)
            if date_parts:
                try:
                    day, month, year = date_parts
                    session.birthdate = date(year, month, day)

                    await self._try_authentication(session)
                except ValueError:
                    pass

        if any(
            word in user_message.lower()
            for word in ["tchau", "sair", "encerrar", "bye"]
        ):
            session.state = ConversationState.GOODBYE

    async def _try_authentication(self, session: SessionData) -> None:
        try:
            client = await self._csv_service.get_client_by_cpf(session.cpf)
            if client and client.birth_date == session.birthdate:
                auth_result = await self._auth_service.authenticate(
                    session.cpf, session.birthdate
                )
                if auth_result.authenticated:
                    session.state = ConversationState.AUTHENTICATED
                    session.token = auth_result.token
        except Exception as e:
            logger.error(f"Erro na autenticação: {e}")

    def _generate_cache_key(self, session: SessionData, message: str) -> str:
        state_key = (
            f"{session.state.value}_{bool(session.cpf)}_{bool(session.birthdate)}"
        )
        message_hash = hashlib.md5(message.lower().encode()).hexdigest()[:8]
        return f"{state_key}_{message_hash}"

    def _cache_response(self, key: str, response: str) -> None:
        if len(self._response_cache) >= self._cache_max_size:
            oldest_key = next(iter(self._response_cache))
            del self._response_cache[oldest_key]

        self._response_cache[key] = response

    def _response(
        self,
        session_id: str,
        session: SessionData,
        message: str,
        authenticated: bool = False,
        token: str = None,
    ) -> ChatResponse:
        return ChatResponse(
            session_id=session_id,
            message=message,
            state=session.state.value,
            authenticated=authenticated,
            token=token,
        )
