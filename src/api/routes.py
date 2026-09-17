from fastapi import APIRouter, Depends, Query

from src.agents.cambio import ExchangeAgent
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.agents.orchestrator import Orchestrator
from src.agents.triagem import TriageAgent
from src.models.schemas import (
    AuthRequest,
    AuthResponse,
    CreditLimitResponse,
    ExchangeRateResponse,
    InterviewRequest,
    InterviewResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
    UnifiedChatRequest,
    UnifiedChatResponse,
)
from src.services.auth_service import AuthService, get_current_cpf
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService
from src.services.score_service import ScoreService

router = APIRouter()

# Uma instancia de cada servico/agente para todo o processo: o orquestrador e os
# endpoints diretos compartilham cache de LLM, cliente HTTP de cambio e contadores.
csv_service = CSVService()
auth_service = AuthService()
llm_service = LLMService()
score_service = ScoreService(csv_service)

triage_agent = TriageAgent(csv_service, auth_service, llm_service)
credit_agent = CreditAgent(csv_service, score_service)
interview_agent = InterviewAgent(csv_service, score_service)
exchange_agent = ExchangeAgent()
orchestrator = Orchestrator(
    credit_agent=credit_agent,
    interview_agent=interview_agent,
    exchange_agent=exchange_agent,
    csv_service=csv_service,
    auth_service=auth_service,
    llm_service=llm_service,
)


@router.post("/triage/authenticate", response_model=AuthResponse)
async def authenticate(request: AuthRequest) -> AuthResponse:
    return await triage_agent.authenticate(request)


@router.get("/credit/limit", response_model=CreditLimitResponse)
async def get_credit_limit(cpf: str = Depends(get_current_cpf)) -> CreditLimitResponse:
    return await credit_agent.get_limit(cpf)


@router.post("/credit/request_increase", response_model=LimitIncreaseResponse)
async def request_limit_increase(
    request: LimitIncreaseRequest,
    cpf: str = Depends(get_current_cpf),
) -> LimitIncreaseResponse:
    return await credit_agent.request_increase(cpf, request)


@router.post("/interview/submit", response_model=InterviewResponse)
async def submit_interview(
    request: InterviewRequest,
    cpf: str = Depends(get_current_cpf),
) -> InterviewResponse:
    return await interview_agent.submit(cpf, request)


@router.get("/exchange", response_model=ExchangeRateResponse)
async def get_exchange_rate(
    from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
    to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    _cpf: str = Depends(get_current_cpf),
) -> ExchangeRateResponse:
    return await exchange_agent.get_rate(from_currency.upper(), to_currency.upper())


@router.post("/unified/init", response_model=UnifiedChatResponse)
async def init_unified_chat() -> UnifiedChatResponse:
    return await orchestrator.init_session()


@router.post("/unified/chat", response_model=UnifiedChatResponse)
async def unified_chat(request: UnifiedChatRequest) -> UnifiedChatResponse:
    return await orchestrator.process_message(request)
