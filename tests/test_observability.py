"""Retomada de sessão, contadores de uso e cabeçalho de rastreio."""

import pytest
from httpx import AsyncClient


async def say(client: AsyncClient, session_id: str | None, message: str) -> dict:
    response = await client.post(
        "/unified/chat", json={"session_id": session_id, "message": message}
    )
    assert response.status_code == 200
    return response.json()


class TestSessionSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_devolve_historico_para_retomar(
        self, client: AsyncClient
    ) -> None:
        session_id = (await client.post("/unified/init")).json()["session_id"]
        await say(client, session_id, "12345678909")
        await say(client, session_id, "15/05/1990")

        response = await client.get(f"/unified/session/{session_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == session_id
        assert data["authenticated"] is True
        assert data["user_name"] == "Maria"
        assert data["state"] == "authenticated"
        # O front redesenha a conversa a partir daqui, em vez de recomecar do zero.
        assert any(m["role"] == "user" for m in data["messages"])

    @pytest.mark.asyncio
    async def test_snapshot_404_para_sessao_desconhecida(self, client: AsyncClient) -> None:
        response = await client.get("/unified/session/nao-existe")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_snapshot_nao_vaza_o_token(self, client: AsyncClient) -> None:
        """O snapshot é lido no carregamento da página; token só sai pelo chat."""
        session_id = (await client.post("/unified/init")).json()["session_id"]
        await say(client, session_id, "12345678909")
        await say(client, session_id, "15/05/1990")

        data = (await client.get(f"/unified/session/{session_id}")).json()
        assert "token" not in data


class TestTelemetria:
    @pytest.mark.asyncio
    async def test_health_conta_turnos_sem_llm(self, root_client: AsyncClient) -> None:
        chat = AsyncClient(
            transport=root_client._transport, base_url="http://test/api"
        )
        session_id = (await chat.post("/unified/init")).json()["session_id"]
        await chat.post(
            "/unified/chat", json={"session_id": session_id, "message": "12345678909"}
        )
        await chat.post(
            "/unified/chat", json={"session_id": session_id, "message": "15/05/1990"}
        )
        await chat.aclose()

        data = (await root_client.get("/health")).json()
        assert data["turns_total"] == 2
        # Com USE_LANGCHAIN=false, nenhum turno custa uma chamada ao modelo.
        assert data["llm_turns_total"] == 0
        assert data["llm_turn_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_health_expoe_configuracao_da_demo(self, root_client: AsyncClient) -> None:
        data = (await root_client.get("/health")).json()
        assert data["status"] == "healthy"
        assert data["demo_mode"] is True
        assert data["signup_enabled"] is True
        assert data["cpf_provider"] == "mock"


class TestRequestId:
    @pytest.mark.asyncio
    async def test_request_id_e_devolvido(self, root_client: AsyncClient) -> None:
        response = await root_client.get("/health")
        assert response.headers.get("X-Request-ID")

    @pytest.mark.asyncio
    async def test_request_id_do_cliente_e_preservado(
        self, root_client: AsyncClient
    ) -> None:
        response = await root_client.get(
            "/health", headers={"X-Request-ID": "trace-123"}
        )
        assert response.headers["X-Request-ID"] == "trace-123"
