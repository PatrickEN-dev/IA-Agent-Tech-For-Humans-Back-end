from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.agents.cambio import ExchangeAgent
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.agents.orchestrator import Orchestrator
from src.agents.triagem import TriageAgent
from src.config import get_settings
from src.db.repositories import (
    ClientRepository,
    LimitRequestRepository,
    ScoreLimitRepository,
)
from src.models.schemas import (
    AddressResponse,
    AuthRequest,
    AuthResponse,
    CreditLimitResponse,
    DemoLoginRequest,
    DemoPersonasResponse,
    ExchangeRateResponse,
    InterviewRequest,
    InterviewResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
    SessionSnapshotResponse,
    SignupRequest,
    SignupResponse,
    SuggestedCpfResponse,
    UnifiedChatRequest,
    UnifiedChatResponse,
)
from src.services.address_service import AddressService
from src.services.auth_service import AuthService, get_current_cpf
from src.services.cpf_provider import build_cpf_provider
from src.services.demo_service import DEMO_NOTICE, DemoService
from src.services.llm_service import LLMService
from src.services.rate_limit import limit
from src.services.score_service import ScoreService
from src.services.signup_service import SignupError, SignupService
from src.utils.cpf import format_cpf
from src.utils.formatting import format_brl

router = APIRouter()

# Uma instancia de cada servico/agente para todo o processo: o orquestrador e os
# endpoints diretos compartilham cache de LLM, cliente HTTP de cambio e contadores.
client_repository = ClientRepository()
score_limit_repository = ScoreLimitRepository()
limit_request_repository = LimitRequestRepository()

auth_service = AuthService()
llm_service = LLMService()
score_service = ScoreService(score_limit_repository)
address_service = AddressService()
cpf_provider = build_cpf_provider()
signup_service = SignupService(
    client_repository, score_service, address_service, cpf_provider
)
demo_service = DemoService(client_repository, score_service)

triage_agent = TriageAgent(client_repository, auth_service, llm_service)
credit_agent = CreditAgent(client_repository, score_service, limit_request_repository)
interview_agent = InterviewAgent(client_repository, score_service)
exchange_agent = ExchangeAgent()
orchestrator = Orchestrator(
    credit_agent=credit_agent,
    interview_agent=interview_agent,
    exchange_agent=exchange_agent,
    client_repository=client_repository,
    auth_service=auth_service,
    llm_service=llm_service,
    signup_service=signup_service,
)


def _require_demo_mode() -> None:
    """Endpoints de demonstração não existem fora dela — 404, não 403.

    403 confirmaria que a rota existe; 404 não conta nada a quem está sondando.
    """
    if not get_settings().demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _require_signup_enabled() -> None:
    settings = get_settings()
    if not (settings.demo_mode and settings.signup_enabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# ------------------------------------------------------------------ autenticação


@router.post("/triage/authenticate", response_model=AuthResponse)
@limit("auth")
async def authenticate(request: Request, payload: AuthRequest) -> AuthResponse:
    return await triage_agent.authenticate(payload)


# ------------------------------------------------------------------ crédito


@router.get("/credit/limit", response_model=CreditLimitResponse)
async def get_credit_limit(cpf: str = Depends(get_current_cpf)) -> CreditLimitResponse:
    return await credit_agent.get_limit(cpf)


@router.post("/credit/request_increase", response_model=LimitIncreaseResponse)
async def request_limit_increase(
    payload: LimitIncreaseRequest,
    cpf: str = Depends(get_current_cpf),
) -> LimitIncreaseResponse:
    return await credit_agent.request_increase(cpf, payload)


@router.post("/interview/submit", response_model=InterviewResponse)
async def submit_interview(
    payload: InterviewRequest,
    cpf: str = Depends(get_current_cpf),
) -> InterviewResponse:
    return await interview_agent.submit(cpf, payload)


@router.get("/exchange", response_model=ExchangeRateResponse)
async def get_exchange_rate(
    from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
    to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    _cpf: str = Depends(get_current_cpf),
) -> ExchangeRateResponse:
    return await exchange_agent.get_rate(from_currency.upper(), to_currency.upper())


# ------------------------------------------------------------------ chat unificado


@router.post("/unified/init", response_model=UnifiedChatResponse)
async def init_unified_chat() -> UnifiedChatResponse:
    return await orchestrator.init_session()


@router.post("/unified/chat", response_model=UnifiedChatResponse)
@limit("chat")
async def unified_chat(request: Request, payload: UnifiedChatRequest) -> UnifiedChatResponse:
    return await orchestrator.process_message(payload)


@router.get("/unified/session/{session_id}", response_model=SessionSnapshotResponse)
async def get_session(session_id: str) -> SessionSnapshotResponse:
    """Permite ao front retomar a conversa depois de um F5, em vez de recomeçar."""
    snapshot = orchestrator.get_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada"
        )
    return SessionSnapshotResponse(**snapshot)


# ------------------------------------------------------------------ demonstração


@router.get("/demo/personas", response_model=DemoPersonasResponse)
async def list_demo_personas() -> DemoPersonasResponse:
    _require_demo_mode()
    settings = get_settings()
    return DemoPersonasResponse(
        demo_mode=True,
        signup_enabled=settings.signup_enabled,
        aviso=DEMO_NOTICE,
        personas=await demo_service.list_personas(),
    )


@router.post("/unified/demo-login", response_model=UnifiedChatResponse)
async def demo_login(payload: DemoLoginRequest) -> UnifiedChatResponse:
    """Entra como uma persona em uma chamada só.

    O front poderia mandar CPF e data como duas mensagens de chat, mas isso exibiria o
    CPF como se o visitante o tivesse digitado e deixaria a sessão autenticada pela
    metade se a segunda chamada falhasse.
    """
    _require_demo_mode()
    client = await demo_service.get_persona(payload.persona_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Persona não encontrada"
        )

    greeting = (
        f"Você entrou como {client.nome} (cliente de demonstração).\n"
        f"Score {client.score} · limite {format_brl(client.limite_atual)}"
    )
    return await orchestrator.login_as_client(
        payload.session_id, client, greeting=greeting
    )


# ------------------------------------------------------------------ auto-cadastro


@router.get("/signup/suggested-cpf", response_model=SuggestedCpfResponse)
@limit("signup")
async def suggested_cpf(request: Request) -> SuggestedCpfResponse:
    _require_signup_enabled()
    try:
        cpf = await signup_service.suggest_cpf()
    except SignupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    return SuggestedCpfResponse(
        cpf=cpf,
        cpf_formatado=format_cpf(cpf),
        aviso=(
            "CPF fictício gerado para testes: passa na validação de dígitos "
            "verificadores e não pertence a ninguém."
        ),
    )


@router.get("/address/{cep}", response_model=AddressResponse)
async def lookup_address(cep: str) -> AddressResponse:
    """Consulta de CEP via BrasilAPI, usada pelo cadastro para preencher cidade e UF."""
    address = await address_service.lookup(cep)
    if address is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="CEP não encontrado"
        )
    return AddressResponse(
        cep=address.cep,
        logradouro=address.logradouro,
        bairro=address.bairro,
        cidade=address.cidade,
        uf=address.uf,
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
@limit("signup")
async def signup(request: Request, payload: SignupRequest) -> SignupResponse:
    _require_signup_enabled()
    try:
        result = await signup_service.register(
            nome=payload.nome,
            cpf=payload.cpf,
            data_nascimento=payload.data_nascimento,
            email=str(payload.email) if payload.email else None,
            cep=payload.cep,
        )
    except SignupError as exc:
        code = (
            status.HTTP_409_CONFLICT
            if exc.code == "cpf_taken"
            else 422
        )
        raise HTTPException(
            status_code=code, detail={"message": exc.message, "code": exc.code}
        ) from exc

    client = result.client
    return SignupResponse(
        cpf=client.cpf,
        cpf_formatado=format_cpf(client.cpf),
        nome=client.nome,
        data_nascimento=client.data_nascimento,
        score=client.score,
        current_limit=client.limite_atual,
        max_limit_for_score=result.max_limit_for_score,
        cidade=client.cidade,
        uf=client.uf,
        endereco=result.address_label,
        cpf_provider=result.cpf_provider,
        cpf_verified_externally=result.cpf_verified_externally,
        message=(
            f"Conta criada para {client.first_name}. Entre com o CPF "
            f"{format_cpf(client.cpf)} e a data de nascimento informada."
        ),
    )
