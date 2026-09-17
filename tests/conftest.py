"""Isolamento dos testes: banco SQLite temporário, semeado a partir de CSVs de teste.

O ambiente precisa estar montado ANTES de importar `src`, porque os agentes são
singletons criados no import de `src.api.routes` e leem as settings via `get_settings()`,
que é `lru_cache`.

Cada teste recebe um banco recém-semeado: entrevistas e pedidos de aumento escrevem de
verdade, então sem isso o teste seguinte herdaria o score alterado pelo anterior.
"""

import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="banco_agil_tests_"))
TEST_DB_PATH = TEST_DATA_DIR / "test.db"

# 12345678909 e 98765432100 passam na validacao de digitos verificadores.
CLIENTS_CSV = (
    "cpf,nome,data_nascimento,score,limite_atual\n"
    # Maria: limite ABAIXO do teto da faixa (15.000), para que um aumento possa ser
    # aprovado de verdade nos testes, em vez de cair sempre em "ja coberto".
    "12345678909,Maria Silva,1990-05-15,750,5000.00\n"
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


def write_test_data() -> None:
    (TEST_DATA_DIR / "clientes.csv").write_text(CLIENTS_CSV, encoding="utf-8")
    (TEST_DATA_DIR / "score_limite.csv").write_text(SCORE_LIMITS_CSV, encoding="utf-8")


write_test_data()

os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"
os.environ["USE_LANGCHAIN"] = "false"
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
# Sem isso a suite inteira leva 429 na segunda dezena de testes.
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Consulta de CEP e provedor de CPF nao podem sair para a rede em teste.
os.environ["CPF_PROVIDER"] = "mock"
os.environ["DEMO_MODE"] = "true"
os.environ["SIGNUP_ENABLED"] = "true"

from src.config import Settings, get_settings  # noqa: E402

get_settings.cache_clear()

from src.db.seed import seed_database  # noqa: E402
from src.db.session import dispose_engine  # noqa: E402
from src.main import app  # noqa: E402
from src.services.auth_attempts import auth_attempt_tracker  # noqa: E402
from src.services.auth_service import AuthService  # noqa: E402
from src.services.telemetry import telemetry  # noqa: E402

TEST_CPF = "12345678909"
SECOND_TEST_CPF = "98765432100"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir():
    yield
    asyncio.run(dispose_engine())
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
async def _reset_test_data():
    """Recria o banco a cada teste, a partir dos CSVs de teste."""
    await seed_database(reset=True)
    # Todos os testes autenticam com o mesmo CPF: sem este reset, o bloqueio por CPF
    # do terceiro teste de autenticacao derrubaria todos os seguintes.
    auth_attempt_tracker.reset_all()
    telemetry.reset()
    yield


@pytest.fixture
def test_settings() -> Settings:
    return get_settings()


@pytest.fixture
def auth_service(test_settings: Settings) -> AuthService:
    return AuthService(test_settings)


@pytest.fixture
def valid_token(auth_service: AuthService) -> str:
    return auth_service.create_token(TEST_CPF)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as ac:
        yield ac


@pytest.fixture
async def root_client() -> AsyncGenerator[AsyncClient, None]:
    """Cliente sem o prefixo /api, para /health."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
