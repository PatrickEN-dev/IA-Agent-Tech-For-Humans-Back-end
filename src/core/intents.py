"""Intent classification + agent routing + meta-commands.

The orchestrator owns the conversation; this module owns the question
"given a free-form sentence, which agent should handle it?". Rules first
(zero cost, no latency); LLM is used only when rules say 'unknown' AND it
is configured.

It also exposes meta-command detectors (cancel/help/smalltalk) used by the
orchestrator to handle off-topic input *during* multi-turn flows — so the
user is never stuck repeating "I don't understand the value".
"""
from __future__ import annotations

import re

from src.core.session import (
    AGENT_CREDIT,
    AGENT_EXCHANGE,
    AGENT_INTERVIEW,
)
from src.services.llm import LLMGateway
from src.utils.extract import (
    Intent,
    classify_intent_rule_based,
    normalize,
)


_INTENT_TO_AGENT: dict[Intent, str | None] = {
    "credit_limit": AGENT_CREDIT,
    "request_increase": AGENT_CREDIT,
    "interview": AGENT_INTERVIEW,
    "exchange_rate": AGENT_EXCHANGE,
    "exit": None,
    "unknown": None,
}

_ACCEPT_TOKENS = (
    "sim", "yes", "ok", "vamos", "quero", "pode", "claro", "aceito",
    "concordo", "vamos la", "manda", "bora",
)
_REJECT_TOKENS = (
    "nao", "agora nao", "depois", "talvez nao", "fica pra outra",
    "agora não",
)

_CANCEL_TOKENS = (
    "cancelar", "cancela", "desistir", "esquece", "esquece isso",
    "voltar pro menu", "voltar ao menu", "menu inicial", "volta pro menu",
    "parar tudo", "sair daqui", "comecar de novo", "começar de novo",
)

_HELP_TOKENS = (
    "ajuda", "help", "socorro", "como funciona", "o que voce faz",
    "o que voce pode fazer", "o que posso fazer", "opcoes", "opções",
    "menu", "lista", "quais opcoes",
)

_GREETING_TOKENS = (
    "ola", "oi", "bom dia", "boa tarde", "boa noite", "hey", "hello",
    "eai", "e ai", "tudo bem", "blz", "beleza", "salve",
)

_THANKS_TOKENS = (
    "obrigado", "obrigada", "valeu", "thanks", "thx", "agradecido", "grato",
)


def _has_token(message: str, tokens: tuple[str, ...]) -> bool:
    normalized = normalize(message)
    return any(
        re.search(rf"\b{re.escape(token)}\b", normalized) for token in tokens
    )


class IntentRouter:
    """Maps a message to (intent, target_agent)."""

    def __init__(self, llm: LLMGateway | None = None) -> None:
        self._llm = llm or LLMGateway()

    async def route(self, message: str) -> tuple[Intent, str | None]:
        intent = classify_intent_rule_based(message)
        if intent != "unknown":
            return intent, _INTENT_TO_AGENT[intent]

        intent = await self._llm.classify_intent(message)
        return intent, _INTENT_TO_AGENT[intent]


def is_accept(message: str) -> bool:
    return _has_token(message, _ACCEPT_TOKENS)


def is_reject(message: str) -> bool:
    return _has_token(message, _REJECT_TOKENS)


def is_cancel(message: str) -> bool:
    """User wants to abandon the current flow."""
    return _has_token(message, _CANCEL_TOKENS)


def is_help(message: str) -> bool:
    return _has_token(message, _HELP_TOKENS)


def is_smalltalk(message: str) -> bool:
    """Greetings, thanks, generic pleasantries that aren't answers."""
    return _has_token(message, _GREETING_TOKENS) or _has_token(message, _THANKS_TOKENS)


def menu_message() -> str:
    return (
        "Posso te ajudar com 4 coisas: ver seu limite de crédito, "
        "solicitar aumento de limite, cotação de moedas, ou atualizar seu "
        "perfil financeiro. Qual delas você quer?"
    )
