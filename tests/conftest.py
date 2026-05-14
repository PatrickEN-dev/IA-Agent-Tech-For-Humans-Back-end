"""Test fixtures.

Strategy:
  - Replace the global Settings with one pointing to a tmp data dir.
  - Seed the tmp CSV files with the data the tests expect.
  - Reset the cached singletons in routes.py so they pick up the new Settings.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["USE_LANGCHAIN"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"

from src.api.routes import reset_orchestrator
from src.config import Settings, set_settings_override
from src.main import app
from src.services.auth import AuthService


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    (tmp_path / "clientes.csv").write_text(
        "cpf,nome,data_nascimento,score,limite_atual\n"
        "12345678909,Maria Silva,1990-05-15,750,15000.00\n"
        "98765432100,João Santos,1985-03-22,600,8000.00\n"
        "11122233396,Ana Oliveira,1992-11-08,850,25000.00\n"
        "55566677720,Carlos Souza,1978-07-30,450,3000.00\n"
        "99988877714,Beatriz Lima,1995-01-12,300,500.00\n"
    )
    (tmp_path / "score_limite.csv").write_text(
        "score_min,score_max,limite\n"
        "0,299,500.00\n"
        "300,399,1000.00\n"
        "400,499,3000.00\n"
        "500,599,5000.00\n"
        "600,699,8000.00\n"
        "700,799,15000.00\n"
        "800,899,25000.00\n"
        "900,1000,50000.00\n"
    )
    (tmp_path / "solicitacoes_aumento_limite.csv").write_text(
        "cpf_cliente,data_hora_solicitacao,limite_atual,novo_limite_solicitado,status_pedido\n"
    )
    return tmp_path


@pytest.fixture
def test_settings(temp_data_dir: Path) -> Settings:
    return Settings(
        jwt_secret_key="test-secret-key-for-testing",
        use_langchain=False,
        data_dir=temp_data_dir,
    )


@pytest.fixture(autouse=True)
def apply_settings(test_settings: Settings):
    """Inject the test Settings globally and reset the cached singletons."""
    set_settings_override(test_settings)
    reset_orchestrator()
    yield
    set_settings_override(None)
    reset_orchestrator()


@pytest.fixture
def auth_service(test_settings: Settings) -> AuthService:
    return AuthService(test_settings)


@pytest.fixture
def valid_token(auth_service: AuthService) -> str:
    return auth_service.create_token("12345678909")


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as ac:
        yield ac
