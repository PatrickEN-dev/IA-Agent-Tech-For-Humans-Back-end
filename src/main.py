"""FastAPI application bootstrap.

Pulls Settings, sets up logging, validates boot-time invariants, wires the
router and applies two middlewares: CORS (spec-compliant) and a tiny
security-headers middleware.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routes import router
from src.config import get_settings
from src.utils.logging_config import setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.validate_for_boot()
    yield


app = FastAPI(
    title="Banco Ágil — Agente Bancário",
    description="Banking assistant with 4 specialized agents (triage, credit, interview, exchange).",
    version="1.0.0",
    lifespan=lifespan,
)


_settings = get_settings()
# `Access-Control-Allow-Credentials: true` with `Allow-Origin: *` is rejected
# by every browser. Disable credentials when the wildcard is in effect.
_allow_credentials = _settings.cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive headers without affecting business responses."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.include_router(router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
