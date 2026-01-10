from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=14, description="CPF with or without formatting")
    birthdate: date = Field(..., description="Date of birth in YYYY-MM-DD format")
    user_message: str | None = Field(None, description="Optional message for intent detection")


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
    new_limit: float = Field(..., gt=0, description="Requested new credit limit")


class LimitIncreaseResponse(BaseModel):
    cpf: str
    requested_limit: float
    status: Literal["approved", "pending_analysis", "denied"]
    message: str


class InterviewRequest(BaseModel):
    renda_mensal: float = Field(..., ge=0, description="Monthly income")
    tipo_emprego: Literal["CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"] = Field(
        ..., description="Employment type"
    )
    despesas: float = Field(..., ge=0, description="Monthly expenses")
    num_dependentes: int = Field(..., ge=0, le=20, description="Number of dependents")
    tem_dividas: bool = Field(..., description="Has existing debts")


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
