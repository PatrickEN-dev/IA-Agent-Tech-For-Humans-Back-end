import asyncio
import logging
import re
from collections import OrderedDict
from typing import Literal, Optional

from src.config import get_settings
from src.utils.text_normalizer import (
    contains_any,
    contains_word,
    normalize_text,
    parse_boolean_response,
)
from src.utils.value_extractor import (
    extract_currency_code,
    extract_employment_type,
    extract_integer,
    extract_monetary_value,
)

logger = logging.getLogger(__name__)

IntentType = Literal[
    "credit_limit",
    "request_increase",
    "exchange_rate",
    "interview",
    "greeting",
    "goodbye",
    "confirm",
    "reject",
    "off_topic",
    "other",
]

VALID_INTENTS: tuple[str, ...] = (
    "credit_limit",
    "request_increase",
    "exchange_rate",
    "interview",
    "greeting",
    "goodbye",
    "confirm",
    "reject",
    "off_topic",
    "other",
)

BANKING_INTENTS: frozenset[str] = frozenset(
    {"credit_limit", "request_increase", "exchange_rate", "interview"}
)

# Palavras-chave ja normalizadas (minusculas, sem acento). Frases com espaco pesam 2.
INTENT_KEYWORDS: dict[str, list[str]] = {
    "credit_limit": [
        "limite",
        "credito",
        "credit",
        "limit",
        "saldo",
        "score",
        "quanto tenho",
        "quanto posso gastar",
        "disponivel",
        "meu limite",
        "consultar limite",
        "ver limite",
        "limite atual",
    ],
    "request_increase": [
        "aumento",
        "aumentar",
        "aumenta",
        "increase",
        "mais limite",
        "subir limite",
        "elevar",
        "ampliar",
        "solicitar aumento",
        "pedir aumento",
        "quero mais",
    ],
    "exchange_rate": [
        "cambio",
        "dolar",
        "dolares",
        "euro",
        "euros",
        "libra",
        "libras",
        "iene",
        "yen",
        "peso argentino",
        "yuan",
        "moeda",
        "moedas",
        "cotacao",
        "exchange",
        "currency",
        "converter",
        "conversao",
        "usd",
        "eur",
        "gbp",
        "jpy",
        "ars",
        "brl",
    ],
    "interview": [
        "entrevista",
        "interview",
        "questionario",
        "cadastro",
        "recadastro",
        "perfil",
        "atualizar dados",
        "atualizar meus dados",
        "atualizar informacoes",
        "atualizar cadastro",
        "melhorar score",
        "melhorar meu score",
        "aumentar score",
        "aumentar meu score",
        "renda",
        "dados financeiros",
        "informacoes financeiras",
    ],
}

GOODBYE_PHRASES = [
    "tchau",
    "xau",
    "adeus",
    "bye",
    "ate logo",
    "ate mais",
    "ate a proxima",
    "sair",
    "encerrar",
    "finalizar",
    "terminar",
    "era so isso",
    "so isso",
    "e so isso",
    "nao preciso mais",
    "nao preciso de mais nada",
    "por hoje e so",
    "pode encerrar",
    "falou",
    "flw",
    "obrigado tchau",
]

CONFIRM_PHRASES = [
    "sim",
    "s",
    "yes",
    "ok",
    "okay",
    "claro",
    "pode",
    "pode ser",
    "pode sim",
    "quero",
    "quero sim",
    "vamos",
    "vamos la",
    "bora",
    "aceito",
    "com certeza",
    "isso",
    "positivo",
    "por favor",
    "manda",
    "beleza",
    "blz",
    "show",
    "top",
    "perfeito",
    "otimo",
    "boa",
    "certo",
    "combinado",
    "fechado",
    "gostaria",
]

REJECT_PHRASES = [
    "nao",
    "nao quero",
    "nao precisa",
    "nao preciso",
    "agora nao",
    "depois",
    "mais tarde",
    "talvez depois",
    "deixa pra la",
    "deixa para la",
    "nunca",
    "negativo",
    "dispenso",
    "cancelar",
    "cancela",
    "desisto",
    "esquece",
    "nem",
    "nope",
]

GREETING_PHRASES = [
    "oi",
    "ola",
    "bom dia",
    "boa tarde",
    "boa noite",
    "hey",
    "hello",
    "hi",
    "eai",
    "e ai",
    "opa",
    "tudo bem",
    "tudo bom",
    "alo",
]

# Respostas curtas que sozinhas significam "nao" mas seriam ambiguas dentro de uma frase
STANDALONE_REJECT = {"no", "n", "nn", "nao", "não"}

INTENT_SYSTEM_PROMPT = (
    "Você classifica a intenção de mensagens de clientes de um chatbot bancário "
    "(Banco Ágil). Responda apenas com um destes rótulos, sem explicação:\n"
    "credit_limit: consultar limite, saldo ou score\n"
    "request_increase: pedir aumento de limite\n"
    "exchange_rate: cotação, câmbio ou moedas\n"
    "interview: atualizar perfil ou dados financeiros\n"
    "greeting: saudação\n"
    "goodbye: encerrar a conversa, despedida, \"era só isso\"\n"
    "confirm: aceitar uma oferta (sim, pode, quero)\n"
    "reject: recusar uma oferta (não, depois, agora não)\n"
    "off_topic: assunto não bancário\n"
    "other: não classificável"
)

HUMANIZE_SYSTEM_PROMPT = (
    "Você é o atendente virtual do Banco Ágil. Reescreva a resposta técnica em "
    "português do Brasil de forma natural, calorosa e objetiva, em 1 a 3 frases. "
    "Regras: mantenha todos os dados, valores e perguntas da resposta técnica; "
    "não invente informações nem faça promessas; se o cliente cumprimentou, "
    "cumprimente de volta{name_part}; não use markdown nem listas."
)


class BoundedCache(OrderedDict):
    """Cache LRU simples para evitar crescimento infinito de memoria."""

    def __init__(self, max_size: int) -> None:
        super().__init__()
        self._max_size = max_size

    def get_value(self, key: str) -> Optional[str]:
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def set_value(self, key: str, value: str) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self._max_size:
            self.popitem(last=False)


_intent_cache = BoundedCache(max_size=get_settings().intent_cache_max_size)


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
        self._llm_cache: dict[tuple, object] = {}
        self.parser = NaturalLanguageParser()

    def _should_use_langchain(self) -> bool:
        return self._settings.use_langchain and self._settings.has_llm_api_key()

    def _get_llm(
        self, *, max_tokens: int, temperature: float, timeout: float
    ):
        """Instancia (e reaproveita) o cliente LLM.

        Criar um ChatOpenAI a cada chamada abre uma conexao HTTP nova; reaproveitar
        a instancia mantem o pool de conexoes e corta latencia por requisicao.
        """
        key = (self._settings.llm_provider, max_tokens, round(temperature, 2), timeout)
        cached = self._llm_cache.get(key)
        if cached is not None:
            return cached

        if self._settings.llm_provider == "openai":
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.openai_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=1,
            )
        else:
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model=self._settings.anthropic_model,
                api_key=self._settings.anthropic_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=1,
            )

        self._llm_cache[key] = llm
        return llm

    def warmup(self) -> None:
        """Pre-carrega os clientes LLM no startup.

        O primeiro uso pagava o import do LangChain e a criacao do cliente HTTP
        (~1-3 s). Sem chamada de rede aqui, apenas instanciacao.
        """
        if not self._should_use_langchain():
            return
        try:
            self._get_llm(
                max_tokens=8,
                temperature=0.0,
                timeout=self._settings.llm_intent_timeout_seconds,
            )
            self._get_llm(
                max_tokens=160,
                temperature=0.4,
                timeout=self._settings.llm_humanize_timeout_seconds,
            )
            logger.info("LLM clients warmed up")
        except Exception as e:
            logger.warning(f"LLM warmup failed: {e}")

    # ------------------------------------------------------------------ intent

    async def classify_intent(
        self, message: str | None, allow_llm: bool = True
    ) -> IntentType | None:
        """Classifica a intencao: regras primeiro (0 ms), LLM so quando ambiguo.

        Regras cobrem a grande maioria das mensagens ("meu limite", "sim", "tchau").
        O LLM entra para frases sem palavra-chave ("era so isso", "acho que nao").
        """
        if not message or not message.strip():
            return None

        rule_intent = self.classify_with_rules(message)
        if rule_intent is not None:
            return rule_intent

        if allow_llm and self._should_use_langchain():
            llm_intent = await self._classify_with_langchain(message)
            if llm_intent and llm_intent != "other":
                return llm_intent

        return None

    def classify_with_rules(self, message: str) -> IntentType | None:
        normalized = normalize_text(re.sub(r"[^\w\s]", " ", message))
        if not normalized:
            return None

        if normalized in STANDALONE_REJECT:
            return "reject"

        scores: dict[str, int] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if contains_word(normalized, keyword):
                    score += 2 if " " in keyword else 1
            if score:
                scores[intent] = score

        if scores:
            if "credit_limit" in scores and "request_increase" in scores:
                # "quero aumentar meu limite": a acao (aumentar) e mais especifica
                logger.debug("Rule-based intent: request_increase (action priority)")
                return "request_increase"

            if len(scores) == 1:
                intent = next(iter(scores))
                logger.debug(f"Rule-based intent: {intent}")
                return intent

            ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            if ordered[0][1] > ordered[1][1]:
                logger.debug(f"Rule-based intent: {ordered[0][0]}")
                return ordered[0][0]

            return None

        if contains_any(normalized, GOODBYE_PHRASES):
            return "goodbye"

        is_confirm = contains_any(normalized, CONFIRM_PHRASES)
        is_reject = contains_any(normalized, REJECT_PHRASES)
        if is_reject and not is_confirm:
            return "reject"
        if is_confirm and not is_reject:
            return "confirm"
        if is_confirm and is_reject:
            return None

        if contains_any(normalized, GREETING_PHRASES):
            return "greeting"

        return None

    async def _classify_with_langchain(self, message: str) -> IntentType | None:
        cache_key = normalize_text(message)[:80]
        cached = _intent_cache.get_value(cache_key)
        if cached:
            return cached

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            timeout = self._settings.llm_intent_timeout_seconds
            llm = self._get_llm(max_tokens=8, temperature=0.0, timeout=timeout)

            result = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        SystemMessage(content=INTENT_SYSTEM_PROMPT),
                        HumanMessage(content=f'Mensagem: "{message}"'),
                    ]
                ),
                timeout=timeout + 0.5,
            )
            output = (
                (result.content if hasattr(result, "content") else str(result))
                .strip()
                .lower()
                .replace(" ", "_")
            )

            for intent in VALID_INTENTS:
                if intent in output:
                    _intent_cache.set_value(cache_key, intent)
                    logger.info(f"LLM intent classified: {intent}")
                    return intent

            return None

        except asyncio.TimeoutError:
            logger.warning("Intent classification timed out; using rules fallback")
            return None
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}")
            return None

    # --------------------------------------------------------------- generation

    async def generate_response(self, prompt: str) -> str:
        if self._should_use_langchain():
            response = await self._generate_with_langchain(prompt)
            if response:
                return response

        return self._generate_fallback_response(prompt)

    async def _generate_with_langchain(self, prompt: str) -> str | None:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            timeout = self._settings.llm_humanize_timeout_seconds
            llm = self._get_llm(
                max_tokens=120, temperature=self._settings.llm_temperature, timeout=timeout
            )
            result = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        SystemMessage(
                            content="Você é o atendente virtual do Banco Ágil. Responda em português, de forma clara e amigável, em até 2 frases."
                        ),
                        HumanMessage(content=prompt),
                    ]
                ),
                timeout=timeout + 0.5,
            )
            response = result.content if hasattr(result, "content") else str(result)
            return response.strip()

        except Exception as e:
            logger.warning(f"Response generation failed: {e}")
            return None

    def _generate_fallback_response(self, prompt: str) -> str:
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

    # ------------------------------------------------------------- humanization

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
            from langchain_core.messages import HumanMessage, SystemMessage

            name_part = f" e chame o cliente de {user_name.split()[0]}" if user_name else ""
            system_prompt = HUMANIZE_SYSTEM_PROMPT.format(name_part=name_part)

            previous = ""
            if conversation_context and len(conversation_context) >= 2:
                last = conversation_context[-2]
                if last.get("role") == "assistant":
                    previous = f'Última mensagem do atendente: "{last.get("content", "")[:160]}"\n'

            human_prompt = (
                f"{previous}"
                f'Cliente: "{user_message}"\n'
                f'Resposta técnica: "{technical_response}"'
            )

            timeout = self._settings.llm_humanize_timeout_seconds
            llm = self._get_llm(max_tokens=160, temperature=0.4, timeout=timeout)

            result = await asyncio.wait_for(
                llm.ainvoke(
                    [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
                ),
                timeout=timeout + 0.5,
            )
            response = result.content if hasattr(result, "content") else str(result)
            response = response.strip().strip('"').strip()
            if not response:
                return None

            logger.info("Response humanized")
            return response

        except asyncio.TimeoutError:
            logger.warning("Humanization timed out; using template fallback")
            return None
        except Exception as e:
            logger.warning(f"Humanization failed: {e}")
            return None

    def _humanize_fallback(
        self, user_message: str, technical_response: str, user_name: str | None
    ) -> str:
        """Humanização por template quando o LLM não está disponível."""
        user_normalized = normalize_text(user_message)
        has_greeting = contains_any(user_normalized, GREETING_PHRASES)

        first_name = user_name.split()[0] if user_name else None
        name_part = f", {first_name}" if first_name else ""
        greeting_response = ""

        if has_greeting:
            import random

            greetings = [
                f"Olá{name_part}! Tudo bem? ",
                f"Oi{name_part}! Como vai? ",
                f"Olá{name_part}! Que bom ter você aqui! ",
            ]
            greeting_response = random.choice(greetings)

        technical_lower = technical_response.lower()

        if "cpf inválido" in technical_lower:
            if has_greeting:
                return f"{greeting_response}Para eu poder te ajudar, preciso primeiro confirmar seus dados. Poderia me informar seu CPF, por favor?"
            return "Não consegui identificar um CPF válido. São 11 dígitos, pode me passar?"

        if "formato inválido" in technical_lower or "data inválida" in technical_lower:
            return "Hmm, não consegui entender a data. Pode me passar no formato dia/mês/ano? Por exemplo: 15/05/1990"

        if "não encontrado" in technical_lower:
            return "Hmm, CPF não encontrado na nossa base. Pode verificar se digitou certinho?"

        if "incorreta" in technical_lower:
            return "Ops, a data de nascimento está incorreta em relação aos nossos registros. Quer tentar de novo?"

        if has_greeting:
            return f"{greeting_response}{technical_response}"

        return technical_response
