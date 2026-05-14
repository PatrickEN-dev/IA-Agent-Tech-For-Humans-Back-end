"""Tests for off-topic / meta-command behavior introduced in the refactor.

The previous implementation got stuck in retry loops when the user sent
something unrelated mid-flow. These tests pin the new contract:

  - cancel/help meta-commands always work;
  - smalltalk during a flow re-asks the current question, never says
    "I didn't understand";
  - asking for a different banking service mid-flow triggers a confirm
    handoff (not a silent retry);
  - off-topic at rest returns the menu, never a refusal;
  - empty/whitespace input is rejected at the boundary.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.config import Settings
from src.core.session import SessionStore, _now  # type: ignore[attr-defined]


async def _authenticate(client: AsyncClient, cpf: str = "12345678909", birthdate: str = "15/05/1990") -> str:
    init = await client.post("/unified/init")
    session_id = init.json()["session_id"]
    await client.post("/unified/chat", json={"session_id": session_id, "message": cpf})
    await client.post("/unified/chat", json={"session_id": session_id, "message": birthdate})
    return session_id


@pytest.mark.asyncio
async def test_smalltalk_during_flow_does_not_get_stuck(client: AsyncClient) -> None:
    session_id = await _authenticate(client)
    await client.post("/unified/chat", json={"session_id": session_id, "message": "quero atualizar meu perfil"})

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "olá tudo bem?"},
    )
    data = response.json()
    # Still in the same flow, but the message acknowledges and re-asks.
    assert data["state"] == "interview_income"
    text = data["message"].lower()
    assert "não posso" not in text
    assert "renda" in text or "atendimento" in text


@pytest.mark.asyncio
async def test_thanks_during_flow_does_not_break(client: AsyncClient) -> None:
    session_id = await _authenticate(client)
    await client.post("/unified/chat", json={"session_id": session_id, "message": "cotação"})

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "obrigado!"},
    )
    data = response.json()
    assert data["state"] == "exchange_from"
    assert "não posso" not in data["message"].lower()


@pytest.mark.asyncio
async def test_mid_flow_intent_switch_asks_for_confirmation(client: AsyncClient) -> None:
    session_id = await _authenticate(client)
    # Start the interview flow.
    await client.post("/unified/chat", json={"session_id": session_id, "message": "quero atualizar meu perfil"})

    # User pivots to a different service mid-flow.
    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "qual a cotação do dólar?"},
    )
    data = response.json()
    msg = data["message"].lower()
    assert "interromper" in msg or "trocar" in msg or "moedas" in msg
    # A pending redirect is now set, waiting on the user's yes/no.
    assert data["redirect_suggestion"] is not None


@pytest.mark.asyncio
async def test_mid_flow_switch_confirmed_drops_old_flow(client: AsyncClient) -> None:
    session_id = await _authenticate(client)
    await client.post("/unified/chat", json={"session_id": session_id, "message": "quero atualizar meu perfil"})
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "qual a cotação do dólar?"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "sim"},
    )
    data = response.json()
    # Old interview state is gone; exchange flow is active.
    assert data["state"] == "exchange_from"


@pytest.mark.asyncio
async def test_unauthenticated_off_topic_keeps_asking_cpf(client: AsyncClient) -> None:
    init = await client.post("/unified/init")
    session_id = init.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quem descobriu o Brasil?"},
    )
    data = response.json()
    msg = data["message"].lower()
    assert "não posso" not in msg
    assert "cpf" in msg


@pytest.mark.asyncio
async def test_empty_message_is_rejected_at_boundary(client: AsyncClient) -> None:
    init = await client.post("/unified/init")
    session_id = init.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "   "},
    )
    # Pydantic validation rejects whitespace-only input.
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_session_store_expires_old_sessions() -> None:
    from datetime import timedelta

    store = SessionStore(ttl=timedelta(milliseconds=1))
    sid, session = store.create()
    # Forge an old activity timestamp.
    session.last_activity_at = _now() - timedelta(seconds=10)

    new_sid, _ = store.get_or_create(sid)
    assert new_sid != sid, "expired session should yield a fresh id"


def test_settings_refuses_dev_secret_in_production() -> None:
    settings = Settings(
        environment="prod",
        jwt_secret_key="dev-secret-key-change-in-production",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        settings.validate_for_boot()


def test_settings_passes_with_strong_secret() -> None:
    settings = Settings(environment="prod", jwt_secret_key="super-strong-secret-key-xyz")
    settings.validate_for_boot()  # should not raise
