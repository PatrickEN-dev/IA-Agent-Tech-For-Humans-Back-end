from fastapi import APIRouter, Depends, Query

from src.agents.cambio import ExchangeAgent
from src.agents.chat import ChatAgent
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.agents.triagem import TriageAgent
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
from src.services.auth_service import get_current_cpf

router = APIRouter()

triage_agent = TriageAgent()
credit_agent = CreditAgent()
interview_agent = InterviewAgent()
exchange_agent = ExchangeAgent()
chat_agent = ChatAgent()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await chat_agent.process_message(request)


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
