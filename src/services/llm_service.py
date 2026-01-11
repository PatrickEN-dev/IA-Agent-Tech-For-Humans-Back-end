import logging
import re
from typing import Literal

from src.config import get_settings

logger = logging.getLogger(__name__)

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


class LLMService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._chain = None

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

            template = """Classify the following user message into exactly one of these intents:
- credit_limit: User wants to check their credit limit
- request_increase: User wants to request a limit increase
- exchange_rate: User wants to check currency exchange rates
- interview: User wants to complete a financial interview
- other: Message doesn't match any of the above

User message: {message}

Respond with ONLY the intent name, nothing else."""

            prompt = PromptTemplate(input_variables=["message"], template=template)
            self._chain = prompt | llm
            logger.info(
                f"LangChain initialized with provider: {self._settings.llm_provider}"
            )

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
            logger.info(
                "LangChain returned low-confidence result, falling back to rules"
            )

        return self._classify_with_rules(message)

    async def _classify_with_langchain(self, message: str) -> IntentType | None:
        try:
            self._init_langchain()
            if self._chain is None:
                return None

            result = await self._chain.ainvoke({"message": message})

            if hasattr(result, "content"):
                output = result.content.strip().lower()
            else:
                output = str(result).strip().lower()

            valid_intents: list[IntentType] = [
                "credit_limit",
                "request_increase",
                "exchange_rate",
                "interview",
                "other",
            ]
            if output in valid_intents:
                logger.info(f"LangChain classified intent as: {output}")
                return output

            return None

        except Exception as e:
            logger.warning(f"LangChain classification failed: {e}")
            return None

    def _classify_with_rules(self, message: str) -> IntentType | None:
        normalized = message.lower()
        normalized = re.sub(r"[^\w\s]", " ", normalized)

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

        if all(score == 0 for score in scores.values()):
            return None

        best_intent = max(scores, key=lambda k: scores[k])
        if scores[best_intent] > 0:
            logger.info(f"Rule-based classifier detected intent: {best_intent}")
            return best_intent

        return None
