import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_authenticate_success(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={"cpf": "12345678901", "birthdate": "1990-05-15"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["token"] is not None
    assert data["remaining_attempts"] == 3


@pytest.mark.asyncio
async def test_authenticate_with_formatted_cpf(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={"cpf": "123.456.789-01", "birthdate": "1990-05-15"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True


@pytest.mark.asyncio
async def test_authenticate_invalid_cpf(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={"cpf": "00000000000", "birthdate": "1990-05-15"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["remaining_attempts"] == 2


@pytest.mark.asyncio
async def test_authenticate_invalid_birthdate(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={"cpf": "12345678901", "birthdate": "1990-01-01"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["remaining_attempts"] == 2


@pytest.mark.asyncio
async def test_authenticate_max_attempts_exceeded(client: AsyncClient) -> None:
    for i in range(3):
        response = await client.post(
            "/triage/authenticate",
            json={"cpf": "99999999999", "birthdate": "1990-01-01"},
        )
        if i < 2:
            assert response.status_code == 401
        else:
            assert response.status_code == 401

    response = await client.post(
        "/triage/authenticate",
        json={"cpf": "99999999999", "birthdate": "1990-01-01"},
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_authenticate_with_intent_message(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={
            "cpf": "12345678901",
            "birthdate": "1990-05-15",
            "user_message": "Quero ver meu limite de crédito",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["redirect_intent"] == "credit_limit"


@pytest.mark.asyncio
async def test_authenticate_with_exchange_intent(client: AsyncClient) -> None:
    response = await client.post(
        "/triage/authenticate",
        json={
            "cpf": "12345678901",
            "birthdate": "1990-05-15",
            "user_message": "Qual a cotação do dólar hoje?",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["redirect_intent"] == "exchange_rate"
