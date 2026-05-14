"""HTTP endpoints.

The conversational `/chat` is the primary surface used by the frontend.
The REST endpoints (`/triage/authenticate`, `/credit/limit`, ...) stay for
programmatic clients and legacy tests — they delegate to the same agents
used by the orchestrator, so behavior is consistent.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, Query

from src.agents.credit import CreditAgent
from src.agents.exchange import ExchangeAgent
from src.agents.interview import InterviewAgent
from src.agents.triage import TriageAgent
from src.core.orchestrator import Orchestrator
from src.models.schemas import (
    AuthRequest,
    AuthResponse,
    ChatRequest,
    ChatResponse,
    CreditLimitResponse,
    ExchangeRateResponse,
    InterviewRequest,
    InterviewResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
)
from src.services.auth import get_current_cpf

router = APIRouter()


@lru_cache
def _orchestrator() -> Orchestrator:
    return Orchestrator()


@lru_cache
def _triage() -> TriageAgent:
    return _orchestrator().agent("triage")  # type: ignore[return-value]


@lru_cache
def _credit() -> CreditAgent:
    return _orchestrator().agent("credit")  # type: ignore[return-value]


@lru_cache
def _interview() -> InterviewAgent:
    return _orchestrator().agent("interview")  # type: ignore[return-value]


@lru_cache
def _exchange() -> ExchangeAgent:
    return _orchestrator().agent("exchange")  # type: ignore[return-value]


@router.post("/chat/init", response_model=ChatResponse)
async def init_chat() -> ChatResponse:
    return await _orchestrator().init_session()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _orchestrator().process(request)


# Legacy aliases — same orchestrator, kept so older clients keep working.
@router.post("/unified/init", response_model=ChatResponse)
async def init_unified() -> ChatResponse:
    return await _orchestrator().init_session()


@router.post("/unified/chat", response_model=ChatResponse)
async def unified_chat(request: ChatRequest) -> ChatResponse:
    return await _orchestrator().process(request)


@router.post("/triage/authenticate", response_model=AuthResponse)
async def authenticate(request: AuthRequest) -> AuthResponse:
    return await _triage().authenticate(request)


@router.get("/credit/limit", response_model=CreditLimitResponse)
async def get_credit_limit(cpf: str = Depends(get_current_cpf)) -> CreditLimitResponse:
    return await _credit().get_limit(cpf)


@router.post("/credit/request_increase", response_model=LimitIncreaseResponse)
async def request_increase(
    request: LimitIncreaseRequest,
    cpf: str = Depends(get_current_cpf),
) -> LimitIncreaseResponse:
    return await _credit().request_increase(cpf, request)


@router.post("/interview/submit", response_model=InterviewResponse)
async def submit_interview(
    request: InterviewRequest,
    cpf: str = Depends(get_current_cpf),
) -> InterviewResponse:
    return await _interview().submit(cpf, request)


@router.get("/exchange", response_model=ExchangeRateResponse)
async def exchange_rate(
    from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
    to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    _cpf: str = Depends(get_current_cpf),
) -> ExchangeRateResponse:
    return await _exchange().get_rate(from_currency.upper(), to_currency.upper())


def reset_orchestrator() -> None:
    """Test hook: clear singletons so a fresh Settings is picked up."""
    _orchestrator.cache_clear()
    _triage.cache_clear()
    _credit.cache_clear()
    _interview.cache_clear()
    _exchange.cache_clear()
