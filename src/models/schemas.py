from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EmploymentType = Literal["CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"]
LimitStatus = Literal["approved", "pending_analysis", "denied"]

# Hard ceiling for any monetary input from the user. Higher than this is
# almost certainly a typo and exceeds any reasonable consumer-credit policy.
MAX_MONEY_INPUT: float = 1_000_000.0
MIN_BIRTH_YEAR: int = 1900


class AuthRequest(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=14)
    birthdate: date
    user_message: str | None = Field(default=None, max_length=500)

    @field_validator("birthdate")
    @classmethod
    def _birthdate_in_range(cls, value: date) -> date:
        today = date.today()
        if value > today:
            raise ValueError("birthdate cannot be in the future")
        if value.year < MIN_BIRTH_YEAR:
            raise ValueError("birthdate year is unrealistic")
        return value


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
    new_limit: float = Field(..., gt=0, le=MAX_MONEY_INPUT)


class LimitIncreaseResponse(BaseModel):
    cpf: str
    requested_limit: float
    status: LimitStatus
    message: str
    offer_interview: bool = False
    interview_message: str | None = None


class InterviewRequest(BaseModel):
    renda_mensal: float = Field(..., ge=0, le=MAX_MONEY_INPUT)
    tipo_emprego: EmploymentType
    despesas: float = Field(..., ge=0, le=MAX_MONEY_INPUT)
    num_dependentes: int = Field(..., ge=0, le=20)
    tem_dividas: bool


class InterviewResponse(BaseModel):
    cpf: str
    previous_score: int
    new_score: int
    recommendation: str
    redirect_to: str = "/credit/limit"


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


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def _strip_and_require(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        return stripped


class ChatResponse(BaseModel):
    session_id: str
    message: str
    state: str
    current_agent: str
    authenticated: bool = False
    token: str | None = None
    available_actions: list[str] = []
    redirect_suggestion: RedirectAction | None = None
