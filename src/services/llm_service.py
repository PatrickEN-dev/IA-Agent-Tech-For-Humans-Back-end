import logging
import re
from typing import Literal, Optional

from src.config import get_settings
from src.utils.text_normalizer import normalize_text, parse_boolean_response
from src.utils.value_extractor import (
    extract_monetary_value,
    extract_integer,
    extract_employment_type,
    extract_currency_code,
)

logger = logging.getLogger(__name__)

_response_cache: dict[str, str] = {}

IntentType = Literal[
    "credit_limit", "request_increase", "exchange_rate", "interview", "other"
]

INTENT_KEYWORDS: dict[IntentType, list[str]] = {
    "credit_limit": [
        "limite",
        "credito",
        "crédito",
        "credit",
        "limit",
        "saldo",
        "quanto tenho",
        "meu limite",
        "disponível",
        "disponivel",
    ],
    "request_increase": [
        "aumento",
        "aumentar",
        "increase",
        "mais limite",
        "subir limite",
        "elevar",
        "solicitar aumento",
        "pedir aumento",
    ],
    "exchange_rate": [
        "cambio",
        "câmbio",
        "dolar",
        "dólar",
        "euro",
        "moeda",
        "cotacao",
        "cotação",
        "exchange",
        "currency",
        "converter",
    ],
    "interview": [
        "entrevista",
        "interview",
        "questionario",
        "questionário",
        "cadastro",
        "perfil",
        "atualizar dados",
        "informacoes",
        "informações",
    ],
}


class NaturalLanguageParser:

    @staticmethod
    def parse_income(text: str) -> tuple[Optional[float], str]:
        value = extract_monetary_value(text)
        if value is not None:
            if value < 0:
                return (
                    None,
                    "O valor da renda não pode ser negativo. Qual é sua renda mensal?",
                )
            if value > 1_000_000:
                return (
                    None,
                    "Esse valor parece muito alto. Poderia confirmar sua renda mensal?",
                )
            return value, ""

        normalized = normalize_text(text)
        if any(
            p in normalized
            for p in ["nao sei", "nao tenho certeza", "nao lembro", "incerto"]
        ):
            return (
                None,
                "Tudo bem! Pode ser um valor aproximado. Quanto você recebe por mês? Ex: 3 mil, 5k, ou 8000.",
            )

        return (
            None,
            "Não consegui identificar o valor. Informe sua renda, ex: 5000, 5k, ou cinco mil.",
        )

    @staticmethod
    def parse_expenses(text: str) -> tuple[Optional[float], str]:
        value = extract_monetary_value(text)
        if value is not None:
            if value < 0:
                return None, "O valor das despesas não pode ser negativo."
            if value > 500_000:
                return (
                    None,
                    "Esse valor parece muito alto. Poderia confirmar suas despesas mensais?",
                )
            return value, ""

        normalized = normalize_text(text)
        if any(
            p in normalized for p in ["nao sei", "nao tenho ideia", "dificil dizer"]
        ):
            return (
                None,
                "Entendo. Tente pensar no total aproximado (aluguel, contas, alimentação, etc). Qual seria?",
            )

        return (
            None,
            "Não consegui identificar o valor das despesas. Qual o total aproximado? Ex: 2000, 2k.",
        )

    @staticmethod
    def parse_employment_type(text: str) -> tuple[Optional[str], str]:
        emp_type = extract_employment_type(text)
        if emp_type is not None:
            return emp_type, ""

        normalized = normalize_text(text)
        if any(p in normalized for p in ["nao sei", "nao tenho certeza", "como assim"]):
            return (
                None,
                "Opções: CLT (carteira assinada), Servidor Público, Autônomo/Freelancer, MEI, ou Desempregado. Qual é a sua?",
            )

        return (
            None,
            "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?",
        )

    @staticmethod
    def parse_dependents(text: str) -> tuple[Optional[int], str]:
        value = extract_integer(text)
        if value is not None:
            if value < 0:
                return None, "O número de dependentes não pode ser negativo."
            if value > 20:
                return None, "Esse número parece muito alto. Poderia confirmar?"
            return value, ""

        normalized = normalize_text(text)
        if any(
            p in normalized
            for p in ["o que e", "como assim", "nao entendi", "dependente"]
        ):
            return (
                None,
                "Dependentes são pessoas que dependem financeiramente de você (filhos, cônjuge, pais). Quantos você tem?",
            )

        return (
            None,
            "Quantas pessoas dependem financeiramente de você? Se nenhuma, diga 'zero'.",
        )

    @staticmethod
    def parse_has_debts(text: str) -> tuple[Optional[bool], str]:
        value = parse_boolean_response(text)
        if value is not None:
            return value, ""

        normalized = normalize_text(text)
        if any(
            p in normalized for p in ["nao sei", "acho que", "talvez", "nao lembro"]
        ):
            return (
                None,
                "Considere dívidas como: cartão atrasado, empréstimos, nome sujo. Você tem alguma? Sim ou não.",
            )

        return None, "Você tem alguma dívida em aberto? Responda sim ou não."

    @staticmethod
    def parse_limit_value(text: str) -> tuple[Optional[float], str]:
        value = extract_monetary_value(text)
        if value is not None:
            if value <= 0:
                return None, "O valor do limite deve ser maior que zero."
            if value > 1_000_000:
                return None, "Esse valor está fora da faixa permitida."
            return value, ""

        return None, "Qual valor de limite deseja? Ex: 10000, 10k, ou dez mil."

    @staticmethod
    def parse_currency(text: str) -> tuple[Optional[str], str]:
        code = extract_currency_code(text)
        if code is not None:
            return code, ""

        return (
            None,
            "Informe a moeda: USD (dólar), EUR (euro), GBP (libra), JPY (iene), ou ARS (peso argentino).",
        )


class LLMService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm = None
        self._intent_chain = None
        self.parser = NaturalLanguageParser()

    def _should_use_langchain(self) -> bool:
        return self._settings.use_langchain and self._settings.has_llm_api_key()

    def _get_llm(self, max_tokens: int = 80, temperature: float | None = None):

        temp = (
            temperature if temperature is not None else self._settings.llm_temperature
        )

        if self._settings.llm_provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.openai_api_key,
                temperature=temp,
                max_tokens=max_tokens,
                request_timeout=8,
            )
        else:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model="claude-3-haiku-20240307",
                api_key=self._settings.anthropic_api_key,
                temperature=temp,
                max_tokens=max_tokens,
            )

    def _init_intent_chain(self) -> None:
        if self._intent_chain is not None:
            return

        try:
            from langchain_core.prompts import PromptTemplate

            template = "Intent:credit_limit|request_increase|exchange_rate|interview|other\n\"{message}\"→"
            prompt = PromptTemplate(input_variables=["message"], template=template)
            self._intent_chain = prompt | self._get_llm(max_tokens=15, temperature=0.1)
            logger.info(f"Intent chain initialized: {self._settings.llm_model}")

        except Exception as e:
            logger.error(f"Failed to initialize intent chain: {e}")
            self._intent_chain = None

    async def classify_intent(self, message: str | None) -> IntentType | None:
        if not message:
            return None

        if self._should_use_langchain():
            intent = await self._classify_with_langchain(message)
            if intent and intent != "other":
                return intent

        return self._classify_with_rules(message)

    async def _classify_with_langchain(self, message: str) -> IntentType | None:

        cache_key = f"intent:{message[:50]}"
        if cache_key in _response_cache:
            return _response_cache[cache_key]

        try:
            self._init_intent_chain()
            if self._intent_chain is None:
                return None

            result = await self._intent_chain.ainvoke({"message": message})
            output = (
                (result.content if hasattr(result, "content") else str(result))
                .strip()
                .lower()
                .replace(" ", "_")
            )

            valid_intents: list[IntentType] = [
                "credit_limit",
                "request_increase",
                "exchange_rate",
                "interview",
                "other",
            ]

            for intent in valid_intents:
                if intent in output:
                    _response_cache[cache_key] = intent
                    logger.info(f"Intent classified: {intent}")
                    return intent

            return None

        except Exception as e:
            logger.warning(f"Intent classification failed: {e}")
            return None

    def _classify_with_rules(self, message: str) -> IntentType | None:
        normalized = re.sub(r"[^\w\s]", " ", message.lower())

        scores: dict[IntentType, int] = {
            "credit_limit": 0,
            "request_increase": 0,
            "exchange_rate": 0,
            "interview": 0,
        }

        for intent, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in normalized:
                    scores[intent] += 1

        if all(s == 0 for s in scores.values()):
            return None

        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            logger.info(f"Rule-based intent: {best}")
            return best

        return None

    async def generate_response(self, prompt: str) -> str:

        if self._should_use_langchain():
            response = await self._generate_with_langchain(prompt)
            if response:
                return response

        return self._generate_fallback_response(prompt)

    async def _generate_with_langchain(self, prompt: str) -> str | None:

        try:
            from langchain_core.prompts import PromptTemplate

            template = "Banco Ágil.1-2 frases.\n{prompt}"

            prompt_template = PromptTemplate(
                input_variables=["prompt"], template=template
            )
            chain = prompt_template | self._get_llm(max_tokens=80)

            result = await chain.ainvoke({"prompt": prompt})
            response = result.content if hasattr(result, "content") else str(result)

            logger.info("Response generated")
            return response.strip()

        except Exception as e:
            logger.warning(f"Response generation failed: {e}")
            return None

    def _generate_fallback_response(self, prompt: str) -> str:
        """Gera resposta de fallback quando IA não está disponível"""
        prompt_lower = prompt.lower()

        if "cpf" in prompt_lower:
            return "Informe seu CPF (11 dígitos)."
        elif "data" in prompt_lower and "nascimento" in prompt_lower:
            return "Sua data de nascimento?"
        elif "limite" in prompt_lower:
            return "Consultando limite..."
        elif "aumento" in prompt_lower:
            return "Qual valor de aumento deseja?"
        elif "cambio" in prompt_lower or "cotacao" in prompt_lower:
            return "Qual moeda consultar?"
        else:
            return "Como posso ajudar? Limite, aumento, câmbio ou perfil?"

    async def humanize_response(
        self,
        user_message: str,
        technical_response: str,
        conversation_context: list[dict] | None = None,
        user_name: str | None = None,
    ) -> str:

        if self._should_use_langchain():
            humanized = await self._humanize_with_langchain(
                user_message, technical_response, conversation_context, user_name
            )
            if humanized:
                return humanized

        return self._humanize_fallback(user_message, technical_response, user_name)

    async def _humanize_with_langchain(
        self,
        user_message: str,
        technical_response: str,
        conversation_context: list[dict] | None,
        user_name: str | None,
    ) -> str | None:

        try:
            from langchain_core.prompts import PromptTemplate

            name_part = f"[{user_name}]" if user_name else ""

            ctx = ""
            if conversation_context and len(conversation_context) >= 2:
                last = conversation_context[-2]
                if last.get("role") == "assistant":
                    ctx = f"[Ant:{last.get('content', '')[:50]}]"

            system_prompt = f"""Banco Ágil.Humanize 1-2 frases.{name_part}{ctx}
U:"{user_message}"
T:"{technical_response}"
→"""

            template = PromptTemplate(input_variables=[], template=system_prompt)
            chain = template | self._get_llm(max_tokens=100, temperature=0.5)

            result = await chain.ainvoke({})
            response = result.content if hasattr(result, "content") else str(result)

            logger.info("Response humanized")
            return response.strip()

        except Exception as e:
            logger.warning(f"Humanization failed: {e}")
            return None

    def _humanize_fallback(
        self, user_message: str, technical_response: str, user_name: str | None
    ) -> str:
        """Humanização básica quando IA não está disponível"""
        user_lower = user_message.lower().strip()
        greeting_words = [
            "ola",
            "olá",
            "oi",
            "bom dia",
            "boa tarde",
            "boa noite",
            "hey",
            "eai",
            "e ai",
        ]

        has_greeting = any(word in user_lower for word in greeting_words)

        name_part = f", {user_name}" if user_name else ""
        greeting_response = ""

        if has_greeting:
            greetings = [
                f"Olá{name_part}! Tudo bem? ",
                f"Oi{name_part}! Como vai? ",
                f"Olá{name_part}! Que bom ter você aqui! ",
            ]
            import random

            greeting_response = random.choice(greetings)

        technical_lower = technical_response.lower()

        if (
            "cpf inválido" in technical_lower
            or "informe" in technical_lower
            and "cpf" in technical_lower
        ):
            if has_greeting:
                return f"{greeting_response}Para eu poder te ajudar, preciso primeiro confirmar seus dados. Poderia me informar seu CPF, por favor?"
            return "Para continuar, preciso do seu CPF. São 11 dígitos, pode me passar?"

        if "formato inválido" in technical_lower or "data inválida" in technical_lower:
            return "Hmm, não consegui entender a data. Pode me passar no formato dia/mês/ano? Por exemplo: 15/05/1990"

        if "não encontrado" in technical_lower:
            return "Puxa, não encontrei esse CPF na nossa base. Pode verificar se digitou certinho?"

        if "incorreta" in technical_lower:
            return "Ops, a data não confere com nossos registros. Quer tentar de novo?"

        if has_greeting:
            return f"{greeting_response}{technical_response}"

        return technical_response
