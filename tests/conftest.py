import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing"
os.environ["USE_LANGCHAIN"] = "false"

from src.config import Settings, get_settings
from src.main import app
from src.services.auth_service import AuthService


# Backup original CSV data
ORIGINAL_DATA_DIR = Path("src/data")
BACKUP_CLIENTS = None


def backup_csv():
    global BACKUP_CLIENTS
    clients_csv = ORIGINAL_DATA_DIR / "clientes.csv"
    if clients_csv.exists():
        BACKUP_CLIENTS = clients_csv.read_text()


def restore_csv():
    global BACKUP_CLIENTS
    if BACKUP_CLIENTS:
        clients_csv = ORIGINAL_DATA_DIR / "clientes.csv"
        clients_csv.write_text(BACKUP_CLIENTS)


@pytest.fixture(scope="session", autouse=True)
def session_setup_teardown():
    backup_csv()
    yield
    restore_csv()


@pytest.fixture(autouse=True)
def reset_csv_after_test():
    yield
    restore_csv()


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    clients_csv = tmp_path / "clientes.csv"
    clients_csv.write_text(
        "cpf,nome,data_nascimento,score,limite_atual\n"
        "12345678901,Maria Silva,1990-05-15,750,15000.00\n"
        "98765432100,João Santos,1985-03-22,600,8000.00\n"
    )

    score_csv = tmp_path / "score_limite.csv"
    score_csv.write_text(
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

    requests_csv = tmp_path / "solicitacoes_aumento_limite.csv"
    requests_csv.write_text(
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


@pytest.fixture
def auth_service(test_settings: Settings) -> AuthService:
    return AuthService(test_settings)


@pytest.fixture
def valid_token(auth_service: AuthService) -> str:
    return auth_service.create_token("12345678901")


@pytest.fixture
async def client(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    # Patch get_settings to use test_settings
    monkeypatch.setattr("src.config.get_settings", lambda: test_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
