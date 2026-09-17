from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Teto absoluto do payload; o limite "amigavel" (max_message_length) e tratado no orquestrador
# com uma resposta de chat, nao com erro 422.
MAX_MESSAGE_PAYLOAD = 10_000


class AuthRequest(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=14)
    birthdate: date
    user_message: str | None = None


class AuthResponse(BaseModel):
    authenticated: bool
    token: str | None = None
    redirect_intent: str | None = None
    remaining_attempts: int


class CreditLimitResponse(BaseModel):
    cpf: str
    current_limit: float
    available_limit: float
    score: int


class LimitIncreaseRequest(BaseModel):
    new_limit: float = Field(..., gt=0)


class LimitIncreaseResponse(BaseModel):
    cpf: str
    requested_limit: float
    status: Literal["approved", "pending_analysis", "denied"]
    message: str
    offer_interview: bool = False
    interview_message: str | None = None


class InterviewRequest(BaseModel):
    renda_mensal: float = Field(..., ge=0)
    tipo_emprego: Literal["CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"]
    despesas: float = Field(..., ge=0)
    num_dependentes: int = Field(..., ge=0, le=20)
    tem_dividas: bool


class InterviewResponse(BaseModel):
    cpf: str
    previous_score: int
    new_score: int
    recommendation: str
    redirect_to: str


class ExchangeRateResponse(BaseModel):
    from_currency: str
    to_currency: str
    rate: float
    timestamp: datetime
    message: str


class RedirectAction(BaseModel):
    should_redirect: bool = False
    target_agent: str | None = None
    reason: str | None = None
    suggested_action: str | None = None


class UnifiedChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(..., max_length=MAX_MESSAGE_PAYLOAD)


class UnifiedChatResponse(BaseModel):
    session_id: str
    message: str
    state: str
    authenticated: bool = False
    token: str | None = None
    # Primeiro nome do cliente autenticado, para o front personalizar a interface
    user_name: str | None = None
    current_agent: str
    available_actions: list[str] = []
    redirect_suggestion: RedirectAction | None = None


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    version: str
    llm_enabled: bool
