import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unified_init_session(client: AsyncClient) -> None:
    response = await client.post("/unified/init")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "Banco Ágil" in data["message"]
    assert data["state"] == "collecting_cpf"
    assert data["current_agent"] == "triage"
    assert data["authenticated"] is False


@pytest.mark.asyncio
async def test_unified_cpf_collection_valid(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "collecting_birthdate"


@pytest.mark.asyncio
async def test_unified_cpf_collection_invalid(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "inválido" in data["message"].lower() or "11 dígitos" in data["message"]
    assert data["state"] == "collecting_cpf"


@pytest.mark.asyncio
async def test_unified_cpf_not_found(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "99999999999"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "não encontrado" in data["message"].lower()


@pytest.mark.asyncio
async def test_unified_full_authentication_flow(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["state"] == "authenticated"
    assert data["token"] is not None


@pytest.mark.asyncio
async def test_unified_birthdate_invalid(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "01/01/2000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "incorreta" in data["message"].lower()


@pytest.mark.asyncio
async def test_unified_credit_limit_query(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "qual meu limite de crédito?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "limite" in data["message"].lower() or "R$" in data["message"]


@pytest.mark.asyncio
async def test_unified_credit_increase_flow(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero solicitar aumento de limite"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "credit_increase_flow"


@pytest.mark.asyncio
async def test_unified_credit_increase_with_value(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero aumento de limite"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert (
        "approved" in data["message"].lower() or "aprovado" in data["message"].lower()
    )


@pytest.mark.asyncio
async def test_unified_credit_denied_offers_interview(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero aumento de limite"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "100000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert (
        data["redirect_suggestion"] is not None
        or "entrevista" in data["message"].lower()
    )


@pytest.mark.asyncio
async def test_unified_interview_full_flow(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero atualizar meu perfil"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "6000"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "CLT"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "3000"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "2"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "não"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data["message"].lower() or "concluída" in data["message"].lower()


@pytest.mark.asyncio
async def test_unified_exchange_flow(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "cotação do dólar"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "exchange_from"


@pytest.mark.asyncio
async def test_unified_exchange_complete(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "cotação do dólar"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "USD"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "BRL"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "USD" in data["message"] and "BRL" in data["message"]


@pytest.mark.asyncio
async def test_unified_exit_command(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "tchau"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "goodbye"
    assert (
        "obrigado" in data["message"].lower() or "até logo" in data["message"].lower()
    )


@pytest.mark.asyncio
async def test_unified_cpf_formatted(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "123.456.789-01"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "collecting_birthdate"


@pytest.mark.asyncio
async def test_unified_date_alternative_format(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15-05-1990"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True


@pytest.mark.asyncio
async def test_unified_available_actions(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "o que posso fazer?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["available_actions"]) > 0


@pytest.mark.asyncio
async def test_unified_multiple_sessions(client: AsyncClient) -> None:
    init1 = await client.post("/unified/init")
    init2 = await client.post("/unified/init")

    session_id1 = init1.json()["session_id"]
    session_id2 = init2.json()["session_id"]

    assert session_id1 != session_id2

    await client.post(
        "/unified/chat",
        json={"session_id": session_id1, "message": "12345678901"},
    )

    response2 = await client.post(
        "/unified/chat",
        json={"session_id": session_id2, "message": "olá"},
    )
    assert response2.json()["state"] == "collecting_cpf"


@pytest.mark.asyncio
async def test_unified_redirect_acceptance(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero aumento de limite"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "100000"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "sim, quero fazer a entrevista"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "interview_income" or "renda" in data["message"].lower()


@pytest.mark.asyncio
async def test_unified_redirect_rejection(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero aumento de limite"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "100000"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "não, obrigado"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "authenticated"


@pytest.mark.asyncio
async def test_unified_interview_with_natural_language(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero atualizar meu perfil"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "ganho uns 8 mil"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "trabalho de carteira assinada"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "gasto cerca de 4k por mês"},
    )

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "tenho 2 filhos"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "não tenho dívidas"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data["message"].lower()


@pytest.mark.asyncio
async def test_unified_interview_mei_employment(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero atualizar meu perfil"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "5000"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "MEI"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "interview_expenses"


@pytest.mark.asyncio
async def test_unified_interview_publico_employment(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "quero atualizar meu perfil"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "10000"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "servidor público"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "interview_expenses"


@pytest.mark.asyncio
async def test_unified_currency_jpy(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "12345678901"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "15/05/1990"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "cotação"},
    )
    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "JPY"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "BRL"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "JPY" in data["message"]


@pytest.mark.asyncio
async def test_unified_second_client(client: AsyncClient) -> None:
    init_response = await client.post("/unified/init")
    session_id = init_response.json()["session_id"]

    await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "98765432100"},
    )

    response = await client.post(
        "/unified/chat",
        json={"session_id": session_id, "message": "22/03/1985"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
