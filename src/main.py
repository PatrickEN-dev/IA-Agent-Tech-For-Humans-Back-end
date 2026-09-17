import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import exchange_agent, orchestrator, router
from src.config import get_settings
from src.models.schemas import HealthResponse
from src.utils.logging_config import setup_logging

APP_VERSION = "0.2.0"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.uses_default_jwt_secret():
        logger.warning(
            "JWT_SECRET_KEY is using the development default; set a real secret in production"
        )
    logger.info(
        "Starting %s v%s (llm_enabled=%s, provider=%s)",
        app.title,
        APP_VERSION,
        settings.llm_enabled(),
        settings.llm_provider,
    )

    orchestrator.warmup()
    yield
    await exchange_agent.aclose()


app = FastAPI(
    title="Agente Bancário Inteligente",
    description="Intelligent Banking Agent API",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")


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
    return HealthResponse(
        status="healthy", version=APP_VERSION, llm_enabled=settings.llm_enabled()
    )
