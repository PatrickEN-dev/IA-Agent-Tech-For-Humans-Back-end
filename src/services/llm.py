"""LLM gateway — single entry point for any generative call.

Two responsibilities only:
  - classify_intent(message) -> one of the 4 banking intents (or 'unknown'/'exit')
  - compose_reply(...)       -> humanize a technical message in plain Portuguese

Design notes:
  * System/Human messages are split. The system prompt is constant, which
    lets OpenAI / Anthropic apply automatic prompt caching for repeated
    requests in the same hour. Tokens billed for the system part drop
    dramatically.
  * Two cached LLM clients per provider (intent vs reply) reuse the httpx
    pool — no new connection per turn.
  * Humanized replies are memoized by (user_message + technical_answer +
    user_name). Same input → same output, zero LLM call.
  * A simple circuit breaker shuts the LLM down for N seconds after K
    consecutive failures, so a flaky provider does not stall every chat.
  * Output is validated: if the LLM drops the numbers/status from the
    technical answer or echoes a forbidden phrase, we discard the response
    and use the deterministic fallback.
  * Falls back to the technical answer verbatim when the LLM is disabled
    or all guards fail — the backend never returns "I can't help".
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Sequence

from src.config import Settings, get_settings
from src.utils.extract import Intent, classify_intent_rule_based, normalize

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Você é o assistente virtual do Banco Ágil. Fale em português brasileiro, "
    "tom de pessoa real: simpático, calmo e direto. Não use emojis nem "
    "marketês ('em poucos cliques', 'ágil e seguro', etc.). Não use "
    "markdown, bullets nem listas — só prosa curta (no máximo 3 frases).\n\n"
    "O que você pode resolver:\n"
    "1. Consultar limite de crédito.\n"
    "2. Solicitar aumento de limite.\n"
    "3. Cotação de moedas (câmbio).\n"
    "4. Entrevista para atualizar o perfil financeiro (score).\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "- NUNCA diga 'não posso ajudar', 'isso foge do meu escopo' ou frases "
    "  parecidas. Para qualquer assunto fora dos 4 serviços, reconheça "
    "  brevemente o que o usuário disse e ofereça os 4 caminhos.\n"
    "- Se a mensagem não responde à pergunta atual (saudação, agradecimento, "
    "  pergunta genérica, brincadeira), responda gentilmente em UMA frase e "
    "  repita a pergunta pendente. Nunca entre em loop de 'não entendi'.\n"
    "- Se o usuário parecer mudar de assunto bancário no meio do fluxo, "
    "  CONFIRME antes de trocar: 'Quer interromper isso para falar de X?'.\n"
    "- Preserve EXATAMENTE todos os números, status, percentuais, datas e "
    "  nomes que vierem na resposta técnica. Não arredonde, não traduza, "
    "  não invente.\n"
    "- Se a resposta técnica contém uma pergunta, mantenha a pergunta no "
    "  final da sua resposta — o fluxo depende disso.\n"
    "- Em situações de erro ou recusa (limite negado, dados inválidos), "
    "  seja empático em uma frase e indique o próximo passo possível.\n"
    "- Reais usam vírgula decimal e ponto de milhar: R$ 15.000,00."
)

_INTENT_SYSTEM = (
    "Você classifica intenções de mensagens curtas para um chatbot bancário. "
    "Responda apenas uma das categorias: "
    "credit_limit | request_increase | exchange_rate | interview | exit | unknown."
)

_VALID_INTENTS: tuple[Intent, ...] = (
    "credit_limit", "request_increase", "exchange_rate", "interview", "exit", "unknown",
)

# Phrases the LLM must never emit. If we see them in the output we throw the
# completion away and fall back to the deterministic answer.
_FORBIDDEN_PHRASES = (
    "não posso ajudar",
    "não posso te ajudar",
    "nao posso ajudar",
    "fora do meu escopo",
    "fora do escopo",
    "não consigo ajudar",
    "infelizmente não posso",
)

_MAX_USER_MESSAGE_CHARS = 300
_MAX_TECHNICAL_CHARS = 500
_HISTORY_TURNS = 2
_HISTORY_CHAR_LIMIT = 100


class LLMGateway:
    _MAX_CACHE_ENTRIES = 256
    _CIRCUIT_FAILURE_THRESHOLD = 3
    _CIRCUIT_COOLDOWN_SECONDS = 30.0

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._intent_cache: dict[str, str] = {}
        self._reply_cache: dict[str, str] = {}
        self._llm_intent = None
        self._llm_reply = None
        self._init_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._settings.use_langchain and self._settings.has_llm_api_key()

    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_SECONDS
            logger.warning(
                "LLM circuit opened for %ss after %s failures",
                self._CIRCUIT_COOLDOWN_SECONDS, self._consecutive_failures,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    # ---- public API ------------------------------------------------------

    async def classify_intent(self, message: str) -> Intent:
        if not message or not message.strip():
            return "unknown"

        rule_based = classify_intent_rule_based(message)
        if rule_based != "unknown" or not self.enabled or self._circuit_is_open():
            return rule_based

        cache_key = f"intent::{_hash(message)}"
        if cached := self._intent_cache.get(cache_key):
            return cached  # type: ignore[return-value]

        raw = await self._invoke_intent(message[:200])
        if raw is None:
            return rule_based

        intent = _coerce_intent(raw)
        _remember(self._intent_cache, cache_key, intent, self._MAX_CACHE_ENTRIES)
        return intent

    async def compose_reply(
        self,
        *,
        user_message: str,
        technical_answer: str,
        history: Sequence[dict[str, str]] | None = None,
        user_name: str | None = None,
    ) -> str:
        """Wrap a deterministic technical answer in friendly prose.

        Falls back to the technical answer verbatim when the LLM is unavailable
        or the output looks unsafe (missing numbers, forbidden phrases).
        """
        if not self.enabled or self._circuit_is_open():
            return _fallback_humanize(user_message, technical_answer, user_name)

        user_message = (user_message or "")[:_MAX_USER_MESSAGE_CHARS]
        technical_answer = (technical_answer or "")[:_MAX_TECHNICAL_CHARS]

        cache_key = f"reply::{_hash(user_message + '||' + technical_answer + '||' + (user_name or ''))}"
        if cached := self._reply_cache.get(cache_key):
            return cached

        user_block = _build_user_block(user_message, technical_answer, history, user_name)
        completion = await self._invoke_reply(user_block)
        if not completion:
            return _fallback_humanize(user_message, technical_answer, user_name)

        cleaned = completion.strip()
        if not _validate_humanized(cleaned, technical_answer):
            logger.info("LLM reply failed validation; using fallback")
            return _fallback_humanize(user_message, technical_answer, user_name)

        _remember(self._reply_cache, cache_key, cleaned, self._MAX_CACHE_ENTRIES)
        return cleaned

    # ---- internals -------------------------------------------------------

    async def _invoke_intent(self, user_text: str) -> str | None:
        llm = await self._client("intent")
        return await self._safe_call(llm, _INTENT_SYSTEM, user_text)

    async def _invoke_reply(self, user_text: str) -> str | None:
        llm = await self._client("reply")
        return await self._safe_call(llm, _SYSTEM_PROMPT, user_text)

    async def _client(self, kind: str):
        async with self._init_lock:
            if kind == "intent":
                if self._llm_intent is None:
                    self._llm_intent = self._build_client(
                        max_tokens=10, temperature=0.0,
                    )
                return self._llm_intent
            if self._llm_reply is None:
                self._llm_reply = self._build_client(
                    max_tokens=min(self._settings.llm_max_tokens, 120),
                    temperature=self._settings.llm_temperature,
                )
            return self._llm_reply

    async def _safe_call(self, llm, system: str, user: str) -> str | None:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            result = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
        except Exception as exc:
            logger.warning("LLM invocation failed: %s", exc)
            self._record_failure()
            return None
        self._record_success()
        return getattr(result, "content", str(result))

    def _build_client(self, *, max_tokens: int, temperature: float):
        provider = self._settings.llm_provider
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.openai_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                request_timeout=self._settings.llm_timeout_seconds,
            )

        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model="claude-3-haiku-20240307",
            api_key=self._settings.anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._settings.llm_timeout_seconds,
        )


# ---- module helpers ------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha1(text.lower().strip().encode()).hexdigest()[:16]


def _coerce_intent(raw: str) -> Intent:
    cleaned = normalize(raw).replace(" ", "_")
    for intent in _VALID_INTENTS:
        if intent in cleaned:
            return intent
    return "unknown"


def _remember(cache: dict[str, str], key: str, value: str, max_entries: int) -> None:
    if key in cache:
        return
    if len(cache) >= max_entries:
        cache.pop(next(iter(cache)))
    cache[key] = value


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _extract_numbers(text: str) -> set[str]:
    return {m.replace(" ", "") for m in _NUMBER_RE.findall(text or "")}


def _validate_humanized(reply: str, technical_answer: str) -> bool:
    """Reject completions that drop important data or echo forbidden phrases.

    Cheap, deterministic checks. Anything fishy → caller uses the fallback.
    """
    if not reply:
        return False
    lower = reply.lower()
    if any(bad in lower for bad in _FORBIDDEN_PHRASES):
        return False
    required = _extract_numbers(technical_answer)
    if required:
        present = _extract_numbers(reply)
        # Keep at least 80% of the numeric tokens from the technical answer.
        missing = required - present
        if len(missing) > max(1, int(len(required) * 0.2)):
            return False
    if technical_answer.rstrip().endswith("?") and "?" not in reply:
        return False
    return True


def _build_user_block(
    user_message: str,
    technical_answer: str,
    history: Sequence[dict[str, str]] | None,
    user_name: str | None,
) -> str:
    parts: list[str] = []
    if user_name:
        parts.append(f"Nome do usuário: {user_name}.")
    if history_text := _format_history(history or ()):
        parts.append(history_text)
    parts.append(f'Mensagem do usuário: "{user_message}"')
    parts.append(f'Resposta técnica autorizada: "{technical_answer}"')
    parts.append(
        "Reescreva a resposta técnica acima em tom amigável e natural, "
        "preservando todos os números, status e nomes. Não acrescente "
        "informações que não estejam na resposta técnica."
    )
    return "\n".join(parts)


def _format_history(history: Sequence[dict[str, str]]) -> str:
    if not history:
        return ""
    recent = history[-_HISTORY_TURNS:]
    lines = []
    for entry in recent:
        role = "Usuário" if entry.get("role") == "user" else "Assistente"
        content = (entry.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:_HISTORY_CHAR_LIMIT]}")
    return "Histórico recente:\n" + "\n".join(lines) if lines else ""


def _fallback_humanize(
    user_message: str, technical_answer: str, user_name: str | None
) -> str:
    """Plain reply when the LLM is offline — clearer than the old fallback."""
    greetings = ("ola", "oi", "bom dia", "boa tarde", "boa noite", "hey")
    is_greeting = any(g in normalize(user_message) for g in greetings)

    prefix = ""
    if is_greeting:
        prefix = f"Olá{', ' + user_name if user_name else ''}! "
    return f"{prefix}{technical_answer}".strip()
