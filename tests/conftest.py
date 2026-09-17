import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Diretório de dados isolado para os testes. Precisa existir e estar no ambiente
# ANTES de importar `src`, porque os agentes são singletons criados no import de
# `src.api.routes` e leem `DATA_DIR` via `get_settings()` (lru_cache).
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="banco_agil_tests_"))

CLIENTS_CSV = (
    "cpf,nome,data_nascimento,score,limite_atual\n"
    "12345678901,Maria Silva,1990-05-15,750,15000.00\n"
    "98765432100,João Santos,1985-03-22,600,8000.00\n"
)

SCORE_LIMITS_CSV = (
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

LIMIT_REQUESTS_CSV = (
    "cpf_cliente,data_hora_solicitacao,limite_atual,novo_limite_solicitado,status_pedido\n"
)


def write_test_data() -> None:
    (TEST_DATA_DIR / "clientes.csv").write_text(CLIENTS_CSV, encoding="utf-8")
    (TEST_DATA_DIR / "score_limite.csv").write_text(SCORE_LIMITS_CSV, encoding="utf-8")
    (TEST_DATA_DIR / "solicitacoes_aumento_limite.csv").write_text(
        LIMIT_REQUESTS_CSV, encoding="utf-8"
    )


write_test_data()

os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"
os.environ["USE_LANGCHAIN"] = "false"
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)

from src.config import Settings, get_settings  # noqa: E402

get_settings.cache_clear()

from src.main import app  # noqa: E402
from src.services.auth_service import AuthService  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir():
    yield
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_test_data():
    """Entrevistas e solicitações gravam nos CSVs; restaura o estado a cada teste."""
    yield
    write_test_data()


@pytest.fixture
def test_settings() -> Settings:
    return get_settings()


@pytest.fixture
def auth_service(test_settings: Settings) -> AuthService:
    return AuthService(test_settings)


@pytest.fixture
def valid_token(auth_service: AuthService) -> str:
    return auth_service.create_token("12345678901")


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as ac:
        yield ac
