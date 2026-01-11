from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.api.routes import router
from src.config import get_settings
from src.utils.logging_config import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    yield


app = FastAPI(
    title="Agente Bancário Inteligente",
    description="Intelligent Banking Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
