import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from src.api.routes import (
    address_service,
    cpf_provider,
    exchange_agent,
    orchestrator,
    router,
)
from src.config import get_settings
from src.db.seed import seed_database
from src.db.session import dispose_engine
from src.models.schemas import HealthResponse
from src.services.rate_limit import limiter
from src.services.telemetry import telemetry
from src.utils.logging_config import request_id_var, setup_logging

APP_VERSION = "0.3.0"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level, json_logs=settings.json_logs)

    if settings.uses_default_jwt_secret():
        logger.warning(
            "JWT_SECRET_KEY is using the development default; set a real secret in production"
        )

    # O disco do Render gratuito é efêmero, então o banco precisa existir a cada boot.
    # Com DEMO_RESET_ON_START a demo também volta sempre a um estado conhecido.
    await seed_database(reset=settings.demo_reset_on_start)

    logger.info(
        "Starting %s v%s (llm=%s, provider=%s, demo=%s, cpf_provider=%s)",
        app.title,
        APP_VERSION,
        settings.llm_enabled(),
        settings.llm_provider,
        settings.demo_mode,
        settings.cpf_provider,
    )

    orchestrator.warmup()
    yield

    await exchange_agent.aclose()
    await address_service.aclose()
    await cpf_provider.aclose()
    await dispose_engine()


app = FastAPI(
    title="Agente Bancário Inteligente",
    description="Intelligent Banking Agent API",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.include_router(router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Um id por requisição, propagado para todos os logs daquele turno.

    Sem ele, investigar "a conversa do fulano travou" em um log concorrente é
    impossível: as linhas de várias sessões se intercalam.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    logger.warning("Rate limit atingido em %s", request.url.path)
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                "Muitas requisições em pouco tempo. Aguarde alguns segundos e tente "
                "novamente."
            )
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Erro inesperado: registra o traceback e devolve um JSON previsivel para o front."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno. Tente novamente em instantes."},
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    snapshot = telemetry.snapshot()
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        llm_enabled=settings.llm_enabled(),
        demo_mode=settings.demo_mode,
        signup_enabled=settings.signup_enabled,
        cpf_provider=settings.cpf_provider,
        turns_total=snapshot["turns_total"],
        llm_turns_total=snapshot["llm_turns_total"],
        llm_turn_ratio=snapshot["llm_turn_ratio"],
    )
