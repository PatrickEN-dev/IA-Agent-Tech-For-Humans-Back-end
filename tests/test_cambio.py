import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_exchange_rate_success(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "USD", "to": "BRL"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "BRL"
    assert data["rate"] > 0
    assert "timestamp" in data
    assert "message" in data


@pytest.mark.asyncio
async def test_get_exchange_rate_eur_to_brl(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "EUR", "to": "BRL"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["from_currency"] == "EUR"
    assert data["to_currency"] == "BRL"


@pytest.mark.asyncio
async def test_get_exchange_rate_same_currency(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "USD", "to": "USD"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rate"] == 1.0


@pytest.mark.asyncio
async def test_get_exchange_rate_lowercase(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "usd", "to": "brl"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "BRL"


@pytest.mark.asyncio
async def test_get_exchange_rate_unauthorized(client: AsyncClient) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "USD", "to": "BRL"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_exchange_rate_missing_params(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_exchange_rate_invalid_currency_length(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/exchange",
        params={"from": "US", "to": "BRL"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 422
