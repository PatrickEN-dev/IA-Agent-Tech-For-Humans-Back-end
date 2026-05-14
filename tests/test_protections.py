"""Tests for the post-refactor defensive measures.

Covers:
  - CPF Brazilian checksum (utils.extract.is_valid_cpf)
  - Schema-level guards on dates and monetary upper bounds
  - ScoringService cache invalidation
  - SessionStore TTL and eviction
  - Orchestrator session reset after goodbye
  - Security headers + CORS sanity
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from src.core.session import (
    STATE_AUTHENTICATED,
    STATE_GOODBYE,
    Session,
    SessionStore,
)
from src.models.schemas import (
    AuthRequest,
    InterviewRequest,
    LimitIncreaseRequest,
)
from src.services.clients import ClientRepository
from src.services.scoring import ScoringService
from src.utils.extract import is_valid_cpf, normalize_cpf


# ---------- CPF checksum --------------------------------------------------

@pytest.mark.parametrize(
    "cpf,expected",
    [
        ("12345678909", True),
        ("123.456.789-09", True),
        ("11144477735", True),
        ("11111111111", False),  # all-equal-digits invariant
        ("00000000000", False),
        ("12345678901", False),  # bad check digits
        ("abc", False),
        ("", False),
    ],
)
def test_is_valid_cpf(cpf: str, expected: bool) -> None:
    assert is_valid_cpf(cpf) is expected


def test_normalize_cpf_strips_everything_non_digit() -> None:
    assert normalize_cpf("  123.456.789-09  ") == "12345678909"


# ---------- Schema guards --------------------------------------------------

def test_birthdate_in_future_rejected() -> None:
    future = date.today() + timedelta(days=1)
    with pytest.raises(ValidationError):
        AuthRequest(cpf="12345678909", birthdate=future)


def test_birthdate_too_old_rejected() -> None:
    with pytest.raises(ValidationError):
        AuthRequest(cpf="12345678909", birthdate=date(1800, 1, 1))


def test_limit_increase_upper_bound() -> None:
    LimitIncreaseRequest(new_limit=999_999.0)  # ok
    with pytest.raises(ValidationError):
        LimitIncreaseRequest(new_limit=10_000_000.0)


def test_interview_monetary_upper_bound() -> None:
    with pytest.raises(ValidationError):
        InterviewRequest(
            renda_mensal=2_000_000.0,
            tipo_emprego="CLT",
            despesas=1000.0,
            num_dependentes=0,
            tem_dividas=False,
        )


# ---------- ScoringService cache ------------------------------------------

@pytest.mark.asyncio
async def test_scoring_caches_limit_table(test_settings) -> None:  # noqa: F811
    repo = ClientRepository(test_settings)
    scoring = ScoringService(repo)

    calls = {"n": 0}
    original = repo.read_score_limits

    async def counting():
        calls["n"] += 1
        return await original()

    repo.read_score_limits = counting  # type: ignore[assignment]

    await scoring.limit_for_score(750)
    await scoring.limit_for_score(600)
    assert calls["n"] == 1  # second call served from cache

    scoring.invalidate_cache()
    await scoring.limit_for_score(750)
    assert calls["n"] == 2


# ---------- SessionStore TTL ----------------------------------------------

def test_session_store_evicts_after_ttl() -> None:
    store = SessionStore(ttl=timedelta(microseconds=1))
    sid, session = store.create()
    import time as _time
    _time.sleep(0.01)
    new_sid, new_session = store.get_or_create(sid)
    assert new_sid != sid
    assert new_session is not session


def test_session_reset_active_flow_keeps_token() -> None:
    s = Session()
    s.token = "abc"
    s.collected = {"renda": 5000}
    s.state = "interview_income"
    s.reset_active_flow()
    assert s.state == STATE_AUTHENTICATED
    assert s.token == "abc"
    assert s.collected == {}


# ---------- Orchestrator goodbye reset ------------------------------------

@pytest.mark.asyncio
async def test_goodbye_then_new_message_restarts_session(client: AsyncClient) -> None:
    init = await client.post("/unified/init")
    session_id = init.json()["session_id"]
    await client.post("/unified/chat", json={"session_id": session_id, "message": "tchau"})

    follow_up = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "olá de novo"},
    )
    data = follow_up.json()
    assert data["state"] != STATE_GOODBYE
    assert data["authenticated"] is False


# ---------- Security headers + CORS sanity --------------------------------

@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.post("/unified/init")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "no-referrer"
