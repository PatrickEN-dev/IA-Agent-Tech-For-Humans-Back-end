"""Personas de demonstração e login em um clique."""

import pytest
from httpx import AsyncClient

from src.config import get_settings


@pytest.mark.asyncio
async def test_personas_listadas_com_perfil(client: AsyncClient) -> None:
    response = await client.get("/demo/personas")
    assert response.status_code == 200

    data = response.json()
    assert data["demo_mode"] is True
    assert data["aviso"]
    assert data["personas"], "o seed precisa marcar ao menos uma persona"

    persona = data["personas"][0]
    assert persona["id"] == persona["cpf"]
    assert persona["cpf_formatado"].count(".") == 2
    assert persona["primeiro_nome"]
    assert persona["max_limit_for_score"] > 0
    # A descricao e montada a partir dos dados, nao escrita a mao.
    assert str(persona["score"]) in persona["perfil"]


@pytest.mark.asyncio
async def test_personas_404_sem_demo_mode(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    response = await client.get("/demo/personas")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_demo_login_autentica_em_uma_chamada(client: AsyncClient) -> None:
    personas = (await client.get("/demo/personas")).json()["personas"]
    persona = personas[0]

    response = await client.post(
        "/unified/demo-login", json={"persona_id": persona["id"]}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["authenticated"] is True
    assert data["state"] == "authenticated"
    assert data["token"]
    assert data["user_name"] == persona["primeiro_nome"]

    # A sessao devolvida esta realmente utilizavel, sem novo login.
    follow_up = await client.post(
        "/unified/chat",
        json={"session_id": data["session_id"], "message": "meu limite"},
    )
    assert follow_up.status_code == 200
    assert "R$" in follow_up.json()["message"]


@pytest.mark.asyncio
async def test_demo_login_reaproveita_sessao_existente(client: AsyncClient) -> None:
    session_id = (await client.post("/unified/init")).json()["session_id"]
    persona = (await client.get("/demo/personas")).json()["personas"][0]

    response = await client.post(
        "/unified/demo-login",
        json={"session_id": session_id, "persona_id": persona["id"]},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == session_id


@pytest.mark.asyncio
async def test_demo_login_persona_inexistente(client: AsyncClient) -> None:
    response = await client.post(
        "/unified/demo-login", json={"persona_id": "00000000000"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_conta_criada_por_visitante_nao_e_persona(client: AsyncClient) -> None:
    """Login por persona não pode virar uma porta para a conta de outro visitante.

    Uma conta criada pelo auto-cadastro é de alguém; entrar nela sem a data de
    nascimento transformaria o atalho de demonstração em um bypass de autenticação.
    """
    criada = await client.post(
        "/signup",
        json={"nome": "Visitante Teste", "data_nascimento": "1990-01-01"},
    )
    assert criada.status_code == 201
    cpf = criada.json()["cpf"]

    listadas = (await client.get("/demo/personas")).json()["personas"]
    assert cpf not in [p["id"] for p in listadas]

    response = await client.post("/unified/demo-login", json={"persona_id": cpf})
    assert response.status_code == 404
