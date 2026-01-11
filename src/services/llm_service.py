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

IntentType = Literal["credit_limit", "request_increase", "exchange_rate", "interview", "other"]

INTENT_KEYWORDS: dict[IntentType, list[str]] = {
    "credit_limit": ["limite", "credito", "crédito", "credit", "limit", "saldo", "quanto tenho", "meu limite", "disponível", "disponivel"],
    "request_increase": ["aumento", "aumentar", "increase", "mais limite", "subir limite", "elevar", "solicitar aumento", "pedir aumento"],
    "exchange_rate": ["cambio", "câmbio", "dolar", "dólar", "euro", "moeda", "cotacao", "cotação", "exchange", "currency", "converter"],
    "interview": ["entrevista", "interview", "questionario", "questionário", "cadastro", "perfil", "atualizar dados", "informacoes", "informações"],
}


class NaturalLanguageParser:

    @staticmethod
    def parse_income(text: str) -> tuple[Optional[float], str]:
        value = extract_monetary_value(text)
        if value is not None:
            if value < 0:
                return None, "O valor da renda não pode ser negativo. Qual é sua renda mensal?"
            if value > 1_000_000:
                return None, "Esse valor parece muito alto. Poderia confirmar sua renda mensal?"
            return value, ""

        normalized = normalize_text(text)
        if any(p in normalized for p in ["nao sei", "nao tenho certeza", "nao lembro", "incerto"]):
            return None, "Tudo bem! Pode ser um valor aproximado. Quanto você recebe por mês? Ex: 3 mil, 5k, ou 8000."

        return None, "Não consegui identificar o valor. Informe sua renda, ex: 5000, 5k, ou cinco mil."

    @staticmethod
    def parse_expenses(text: str) -> tuple[Optional[float], str]:
        value = extract_monetary_value(text)
        if value is not None:
            if value < 0:
                return None, "O valor das despesas não pode ser negativo."
            if value > 500_000:
                return None, "Esse valor parece muito alto. Poderia confirmar suas despesas mensais?"
            return value, ""

        normalized = normalize_text(text)
        if any(p in normalized for p in ["nao sei", "nao tenho ideia", "dificil dizer"]):
            return None, "Entendo. Tente pensar no total aproximado (aluguel, contas, alimentação, etc). Qual seria?"

        return None, "Não consegui identificar o valor das despesas. Qual o total aproximado? Ex: 2000, 2k."

    @staticmethod
    def parse_employment_type(text: str) -> tuple[Optional[str], str]:
        emp_type = extract_employment_type(text)
        if emp_type is not None:
            return emp_type, ""

        normalized = normalize_text(text)
        if any(p in normalized for p in ["nao sei", "nao tenho certeza", "como assim"]):
            return None, "Opções: CLT (carteira assinada), Servidor Público, Autônomo/Freelancer, MEI, ou Desempregado. Qual é a sua?"

        return None, "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?"

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
        if any(p in normalized for p in ["o que e", "como assim", "nao entendi", "dependente"]):
            return None, "Dependentes são pessoas que dependem financeiramente de você (filhos, cônjuge, pais). Quantos você tem?"

        return None, "Quantas pessoas dependem financeiramente de você? Se nenhuma, diga 'zero'."

    @staticmethod
    def parse_has_debts(text: str) -> tuple[Optional[bool], str]:
        value = parse_boolean_response(text)
        if value is not None:
            return value, ""

        normalized = normalize_text(text)
        if any(p in normalized for p in ["nao sei", "acho que", "talvez", "nao lembro"]):
            return None, "Considere dívidas como: cartão atrasado, empréstimos, nome sujo. Você tem alguma? Sim ou não."

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

        return None, "Informe a moeda: USD (dólar), EUR (euro), GBP (libra), JPY (iene), ou ARS (peso argentino)."


class LLMService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._chain = None
        self.parser = NaturalLanguageParser()

    def _should_use_langchain(self) -> bool:
        return self._settings.use_langchain and self._settings.has_llm_api_key()

    def _init_langchain(self) -> None:
        if self._chain is not None:
            return

        try:
            from langchain_core.prompts import PromptTemplate

            if self._settings.llm_provider == "openai":
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    api_key=self._settings.openai_api_key,
                    temperature=self._settings.llm_temperature,
                    max_tokens=self._settings.llm_max_tokens,
                )
            else:
                from langchain_anthropic import ChatAnthropic
                llm = ChatAnthropic(
                    api_key=self._settings.anthropic_api_key,
                    temperature=self._settings.llm_temperature,
                    max_tokens=self._settings.llm_max_tokens,
                )

            template = """Classifique a mensagem em: credit_limit, request_increase, exchange_rate, interview ou other.
Mensagem: {message}
Responda apenas o nome da intenção."""

            prompt = PromptTemplate(input_variables=["message"], template=template)
            self._chain = prompt | llm
            logger.info(f"LangChain initialized: {self._settings.llm_provider}")

        except Exception as e:
            logger.error(f"Failed to initialize LangChain: {e}")
            self._chain = None

    async def classify_intent(self, message: str | None) -> IntentType | None:
        if not message:
            return None

        if self._should_use_langchain():
            intent = await self._classify_with_langchain(message)
            if intent and intent != "other":
                return intent

        return self._classify_with_rules(message)

    async def _classify_with_langchain(self, message: str) -> IntentType | None:
        try:
            self._init_langchain()
            if self._chain is None:
                return None

            result = await self._chain.ainvoke({"message": message})
            output = (result.content if hasattr(result, "content") else str(result)).strip().lower()

            valid_intents: list[IntentType] = ["credit_limit", "request_increase", "exchange_rate", "interview", "other"]
            if output in valid_intents:
                logger.info(f"LangChain intent: {output}")
                return output
            return None

        except Exception as e:
            logger.warning(f"LangChain classification failed: {e}")
            return None

    def _classify_with_rules(self, message: str) -> IntentType | None:
        normalized = re.sub(r"[^\w\s]", " ", message.lower())

        scores: dict[IntentType, int] = {"credit_limit": 0, "request_increase": 0, "exchange_rate": 0, "interview": 0}

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
