from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

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
    # Limite efetivamente concedido ao cliente, persistido.
    current_limit: float
    # Teto que o score sustenta hoje. Nao existe "disponivel": o MVP nao tem extrato
    # de compras, entao inventar um percentual seria mentir para o cliente.
    max_limit_for_score: float
    score: int


class LimitIncreaseRequest(BaseModel):
    new_limit: float = Field(..., gt=0)


class LimitIncreaseResponse(BaseModel):
    cpf: str
    requested_limit: float
    status: Literal["approved", "pending_analysis", "denied"]
    # Limite depois da decisao: muda quando o pedido e aprovado.
    current_limit: float
    max_limit_for_score: float
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
    # Score que a entrevista sozinha produziu, antes de ser combinado com o historico.
    interview_score: int
    score_factors: dict[str, float]
    current_limit: float
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


class DemoPersona(BaseModel):
    """Cliente de demonstração pronto, para entrar em um clique."""

    id: str
    nome: str
    primeiro_nome: str
    cpf: str
    cpf_formatado: str
    data_nascimento: str
    score: int
    limite_atual: float
    max_limit_for_score: float
    # Uma linha explicando o que esse perfil demonstra ("score alto, pedidos aprovados").
    perfil: str


class DemoPersonasResponse(BaseModel):
    demo_mode: bool
    signup_enabled: bool
    aviso: str
    personas: list[DemoPersona]


class DemoLoginRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    persona_id: str = Field(..., min_length=1, max_length=32)


class SignupRequest(BaseModel):
    nome: str = Field(..., min_length=3, max_length=120)
    # Vazio significa "gere um CPF válido para mim".
    cpf: str | None = Field(default=None, max_length=14)
    data_nascimento: date
    email: EmailStr | None = None
    cep: str | None = Field(default=None, max_length=9)
    session_id: str | None = Field(default=None, max_length=64)


class SignupResponse(BaseModel):
    cpf: str
    cpf_formatado: str
    nome: str
    data_nascimento: str
    score: int
    current_limit: float
    max_limit_for_score: float
    cidade: str | None = None
    uf: str | None = None
    endereco: str | None = None
    # Qual provedor confirmou o CPF e se houve consulta externa de verdade.
    cpf_provider: str
    cpf_verified_externally: bool
    message: str


class SuggestedCpfResponse(BaseModel):
    cpf: str
    cpf_formatado: str
    aviso: str


class AddressResponse(BaseModel):
    cep: str
    logradouro: str | None = None
    bairro: str | None = None
    cidade: str
    uf: str


class SessionSnapshotResponse(BaseModel):
    """Estado da conversa para o front retomar depois de um reload."""

    session_id: str
    state: str
    authenticated: bool
    user_name: str | None = None
    current_agent: str
    available_actions: list[str] = []
    messages: list[dict] = []


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    version: str
    llm_enabled: bool
    demo_mode: bool
    signup_enabled: bool
    cpf_provider: str
    # Contadores de uso: quantos turnos passaram pelo modelo e quantos ficaram só nas
    # regras. É esse número que sustenta a afirmação de custo no README.
    turns_total: int = 0
    llm_turns_total: int = 0
    llm_turn_ratio: float = 0.0
