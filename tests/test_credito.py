import unicodedata

import pytest
from httpx import AsyncClient


def _fold(text: str) -> str:
    """Minusculas sem acento, para asserts de mensagem nao quebrarem por acentuacao."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@pytest.mark.asyncio
async def test_get_credit_limit_success(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/credit/limit",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cpf"] == "12345678909"
    assert data["score"] == 750
    assert data["current_limit"] == 5000.0
    # Teto da faixa 700-799, que e onde o score 750 cai.
    assert data["max_limit_for_score"] == 15000.0


@pytest.mark.asyncio
async def test_get_credit_limit_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/credit/limit")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_credit_limit_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        "/credit/limit",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_request_limit_increase_approved(
    client: AsyncClient, valid_token: str
) -> None:
    response = await client.post(
        "/credit/request_increase",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"new_limit": 12000.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cpf"] == "12345678909"
    assert data["requested_limit"] == 12000.0
    # Dentro do teto de 15.000: aprovado, e o limite passa a valer de verdade.
    assert data["status"] == "approved"
    assert data["current_limit"] == 12000.0


@pytest.mark.asyncio
async def test_request_limit_increase_same_limit(
    client: AsyncClient, valid_token: str
) -> None:
    response = await client.post(
        "/credit/request_increase",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"new_limit": 5000.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert "ja esta disponivel" in _fold(data["message"])


@pytest.mark.asyncio
async def test_request_limit_increase_invalid_amount(
    client: AsyncClient, valid_token: str
) -> None:
    response = await client.post(
        "/credit/request_increase",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"new_limit": -1000.0},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_request_limit_increase_unauthorized(client: AsyncClient) -> None:
    response = await client.post(
        "/credit/request_increase",
        json={"new_limit": 20000.0},
    )
    assert response.status_code == 401
