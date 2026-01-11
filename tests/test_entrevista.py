import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_submit_interview_success(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": 8000.0,
            "tipo_emprego": "CLT",
            "despesas": 3000.0,
            "num_dependentes": 2,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cpf"] == "12345678901"
    assert data["previous_score"] == 750
    assert "new_score" in data
    assert "recommendation" in data
    assert data["redirect_to"] == "/credit/limit"


@pytest.mark.asyncio
async def test_submit_interview_high_income(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": 15000.0,
            "tipo_emprego": "FORMAL",
            "despesas": 4000.0,
            "num_dependentes": 0,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    # Nova fórmula: (15000/(4000+1))*30 + 300 + 100 + 100 = 589
    # Score médio com anterior (750): (750 + 589) / 2 = 669
    assert "new_score" in data
    assert data["new_score"] > 0


@pytest.mark.asyncio
async def test_submit_interview_with_debts(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": 5000.0,
            "tipo_emprego": "CLT",
            "despesas": 4000.0,
            "num_dependentes": 3,
            "tem_dividas": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "recommendation" in data


@pytest.mark.asyncio
async def test_submit_interview_unemployed(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": 1000.0,
            "tipo_emprego": "DESEMPREGADO",
            "despesas": 800.0,
            "num_dependentes": 0,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["new_score"] is not None


@pytest.mark.asyncio
async def test_submit_interview_invalid_employment_type(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": 5000.0,
            "tipo_emprego": "INVALID",
            "despesas": 2000.0,
            "num_dependentes": 0,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_interview_unauthorized(client: AsyncClient) -> None:
    response = await client.post(
        "/interview/submit",
        json={
            "renda_mensal": 5000.0,
            "tipo_emprego": "CLT",
            "despesas": 2000.0,
            "num_dependentes": 0,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_submit_interview_negative_values(client: AsyncClient, valid_token: str) -> None:
    response = await client.post(
        "/interview/submit",
        headers={"Authorization": f"Bearer {valid_token}"},
        json={
            "renda_mensal": -5000.0,
            "tipo_emprego": "CLT",
            "despesas": 2000.0,
            "num_dependentes": 0,
            "tem_dividas": False,
        },
    )
    assert response.status_code == 422
