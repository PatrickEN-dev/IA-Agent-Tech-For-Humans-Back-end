import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_credit_limit_success(client: AsyncClient, valid_token: str) -> None:
    response = await client.get(
        "/credit/limit",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cpf"] == "12345678901"
    assert data["score"] == 750
    assert data["current_limit"] == 15000.0
    assert data["available_limit"] == 12000.0


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
        json={"new_limit": 20000.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cpf"] == "12345678901"
    assert data["requested_limit"] == 20000.0
    assert data["status"] in ["approved", "pending_analysis", "denied"]


@pytest.mark.asyncio
async def test_request_limit_increase_same_limit(
    client: AsyncClient, valid_token: str
) -> None:
    response = await client.post(
        "/credit/request_increase",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={"new_limit": 15000.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"


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
