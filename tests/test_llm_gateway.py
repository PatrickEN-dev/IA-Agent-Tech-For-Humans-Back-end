"""Tests for `services.llm` — the gateway only, no real network calls.

We swap the internal `_safe_call` so the gateway is deterministic in tests.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable

import pytest

from src.config import Settings
from src.services.llm import (
    LLMGateway,
    _extract_numbers,
    _fallback_humanize,
    _validate_humanized,
)


def _llm_settings(**overrides) -> Settings:
    base = dict(
        use_langchain=True,
        llm_provider="openai",
        openai_api_key="test-key",
        llm_max_tokens=120,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _stub(gateway: LLMGateway, behavior: Callable[[str, str], Awaitable[str | None]]) -> None:
    async def fake_safe_call(_llm, system: str, user: str) -> str | None:
        return await behavior(system, user)
    gateway._safe_call = fake_safe_call  # type: ignore[assignment]
    gateway._llm_intent = object()
    gateway._llm_reply = object()


@pytest.mark.asyncio
async def test_compose_reply_uses_cache_on_repeated_input() -> None:
    gateway = LLMGateway(_llm_settings())
    calls = {"n": 0}

    async def fake(_system: str, _user: str) -> str:
        calls["n"] += 1
        return "Seu limite atual é R$ 15.000,00."

    _stub(gateway, fake)

    out1 = await gateway.compose_reply(
        user_message="qual meu limite", technical_answer="Seu limite atual é R$ 15.000,00.",
    )
    out2 = await gateway.compose_reply(
        user_message="qual meu limite", technical_answer="Seu limite atual é R$ 15.000,00.",
    )
    assert out1 == out2
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_compose_reply_rejects_forbidden_phrase() -> None:
    gateway = LLMGateway(_llm_settings())

    async def fake(_system: str, _user: str) -> str:
        return "Desculpe, não posso te ajudar com isso."

    _stub(gateway, fake)

    out = await gateway.compose_reply(
        user_message="quanto é 25 x 34?",
        technical_answer="Posso te ajudar com 4 coisas: limite, aumento, câmbio, perfil.",
    )
    # Fallback kicks in — original technical answer is preserved verbatim.
    assert "não posso" not in out.lower()
    assert "limite" in out.lower()


@pytest.mark.asyncio
async def test_compose_reply_rejects_when_number_is_dropped() -> None:
    gateway = LLMGateway(_llm_settings())

    async def fake(_system: str, _user: str) -> str:
        return "Seu limite atual é alto."  # number missing

    _stub(gateway, fake)

    technical = "Seu limite atual é R$ 15.000,00 (score 750)."
    out = await gateway.compose_reply(
        user_message="qual meu limite?", technical_answer=technical,
    )
    # Fallback path used since the LLM stripped numbers.
    assert "15" in out


@pytest.mark.asyncio
async def test_compose_reply_keeps_question_mark() -> None:
    gateway = LLMGateway(_llm_settings())

    async def fake(_system: str, _user: str) -> str:
        return "Vou conferir o seu limite agora."  # missing the '?'

    _stub(gateway, fake)

    out = await gateway.compose_reply(
        user_message="ok", technical_answer="Quer solicitar um aumento?",
    )
    assert out.endswith("?")


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures() -> None:
    gateway = LLMGateway(_llm_settings())
    gateway._llm_intent = object()
    gateway._llm_reply = object()

    async def boom(_llm, _system: str, _user: str) -> str | None:
        return None  # simulates an exception path in _safe_call
    gateway._safe_call = boom  # type: ignore[assignment]

    # Force consecutive failures via the public path.
    for _ in range(gateway._CIRCUIT_FAILURE_THRESHOLD):
        gateway._record_failure()

    assert gateway._circuit_is_open()

    # While the circuit is open, compose_reply skips the LLM entirely.
    async def must_not_run(_system: str, _user: str) -> str:
        raise AssertionError("LLM should not be invoked while circuit is open")
    gateway._safe_call = must_not_run  # type: ignore[assignment]

    out = await gateway.compose_reply(
        user_message="oi", technical_answer="Seu limite é R$ 8.000,00.",
    )
    assert "8.000,00" in out


def test_extract_numbers_pulls_digits_and_decimals() -> None:
    assert _extract_numbers("R$ 15.000,00 e score 750") == {"15.000,00", "750"}


def test_validate_humanized_basic_rules() -> None:
    assert _validate_humanized(
        "Seu limite é R$ 15.000,00. Quer aumentar?",
        "Seu limite atual: R$ 15.000,00. Quer aumentar?",
    )
    assert not _validate_humanized(
        "Não posso te ajudar com isso.", "Seu limite é R$ 15.000,00.",
    )
    assert not _validate_humanized(
        "Beleza.", "Quer solicitar aumento?",  # question mark dropped
    )


def test_fallback_humanize_prefixes_greeting() -> None:
    out = _fallback_humanize("ola, tudo bem?", "Qual é seu CPF?", "Maria")
    assert out.startswith("Olá, Maria!")
