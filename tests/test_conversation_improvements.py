"""Comportamentos de conversa e resiliência adicionados ao orquestrador unificado."""

import re
import time

import pytest
from httpx import AsyncClient

from src.api.routes import client_repository, credit_agent, triage_agent
from src.config import get_settings
from tests.conftest import TEST_CPF


def _novo_score_na_mensagem(message: str) -> int:
    """Extrai o "Novo score: N" que o chat mostrou, para conferir contra o banco."""
    match = re.search(r"Novo score:\s*(\d+)", message)
    assert match, f"mensagem sem 'Novo score': {message!r}"
    return int(match.group(1))


async def say(client: AsyncClient, session_id: str | None, message: str) -> dict:
    response = await client.post(
        "/unified/chat", json={"session_id": session_id, "message": message}
    )
    assert response.status_code == 200
    return response.json()


async def start(client: AsyncClient) -> str:
    init = await client.post("/unified/init")
    return init.json()["session_id"]


async def authenticate(client: AsyncClient) -> str:
    session_id = await start(client)
    await say(client, session_id, "12345678909")
    data = await say(client, session_id, "15/05/1990")
    assert data["authenticated"] is True
    return session_id


class TestOfferAnsweredWithValue:
    @pytest.mark.asyncio
    async def test_value_after_limit_offer_processes_increase(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "meu limite")
        assert data["redirect_suggestion"]["target_agent"] == "credit_increase"

        # Responde "Deseja solicitar aumento?" direto com o valor, sem dizer "sim"
        data = await say(client, session_id, "10 mil")
        assert data["state"] == "authenticated"
        assert "aprovado" in data["message"].lower()
        assert "sim ou não" not in data["message"].lower()

    @pytest.mark.asyncio
    async def test_denied_value_after_offer_suggests_interview(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")
        data = await say(client, session_id, "100 mil")
        assert "entrevista" in data["message"].lower()
        assert data["redirect_suggestion"]["target_agent"] == "interview"

    @pytest.mark.asyncio
    async def test_negative_reply_with_number_is_still_a_rejection(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")
        data = await say(client, session_id, "não, 20 mil é muito")
        assert data["state"] == "authenticated"
        assert "tudo bem" in data["message"].lower()


class TestSessionExpiry:
    @pytest.mark.asyncio
    async def test_unknown_session_id_explains_restart(self, client: AsyncClient) -> None:
        data = await say(client, "sessao-que-nao-existe-mais", "quero ver meu limite")
        assert data["state"] == "collecting_cpf"
        assert "expirou" in data["message"].lower()
        assert "cpf" in data["message"].lower()

        # O aviso aparece uma unica vez
        data = await say(client, data["session_id"], "oi")
        assert "expirou" not in data["message"].lower()

    @pytest.mark.asyncio
    async def test_new_session_without_id_has_no_expiry_notice(
        self, client: AsyncClient
    ) -> None:
        data = await say(client, None, "olá")
        assert "expirou" not in data["message"].lower()


class TestInputGuards:
    @pytest.mark.asyncio
    async def test_incomplete_cpf_reports_digit_count(self, client: AsyncClient) -> None:
        session_id = await start(client)
        data = await say(client, session_id, "meu cpf é 1234567")
        assert data["state"] == "collecting_cpf"
        assert "7 dígitos" in data["message"]

    @pytest.mark.asyncio
    async def test_future_birthdate_is_flagged(self, client: AsyncClient) -> None:
        session_id = await start(client)
        await say(client, session_id, "12345678909")
        data = await say(client, session_id, "15/05/2090")
        assert data["state"] == "collecting_birthdate"
        assert "não parece" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_message_too_long_is_declined_gracefully(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        limit = get_settings().max_message_length
        data = await say(client, session_id, "a" * (limit + 1))
        assert data["state"] == "authenticated"
        assert "longa" in data["message"].lower()

        # A sessao continua utilizavel
        data = await say(client, session_id, "meu limite")
        assert "R$" in data["message"]


class TestFlowHelp:
    @pytest.mark.asyncio
    async def test_cancel_hint_after_repeated_misses(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")

        data = await say(client, session_id, "hmm")
        assert data["state"] == "interview_income"
        assert "cancelar" not in data["message"].lower()

        data = await say(client, session_id, "hmm")
        assert data["state"] == "interview_income"
        assert "cancelar" in data["message"].lower()

        data = await say(client, session_id, "cancelar")
        assert data["state"] == "authenticated"

    @pytest.mark.asyncio
    async def test_available_actions_include_cancel_only_inside_flows(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "oi")
        assert "cancelar" not in data["available_actions"]

        data = await say(client, session_id, "quero aumento")
        assert data["state"] == "credit_increase_flow"
        assert "cancelar" in data["available_actions"]

        data = await say(client, session_id, "cancelar")
        assert "cancelar" not in data["available_actions"]


class TestInterviewFeedback:
    @pytest.mark.asyncio
    async def test_result_explains_score_direction_and_updates_limit_column(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        await say(client, session_id, "8000")
        await say(client, session_id, "CLT")
        await say(client, session_id, "3000")
        await say(client, session_id, "2")
        data = await say(client, session_id, "não")

        message = data["message"].lower()
        assert "score anterior" in message
        assert "pontos" in message or "manteve" in message

        # A entrevista grava no banco: o estado persistido tem que bater com a resposta.
        stored = await client_repository.get_by_cpf(TEST_CPF)
        assert stored is not None
        assert stored.score != 750
        assert stored.score == _novo_score_na_mensagem(data["message"])

        ceiling = await credit_agent._score_service.get_limit_for_score(stored.score)
        # Limite nunca e reduzido por uma entrevista; ele acompanha o teto quando sobe.
        assert stored.limite_atual >= ceiling or stored.limite_atual >= 5000.0

        eventos = await client_repository.list_score_events(TEST_CPF)
        assert eventos, "a mudanca de score precisa deixar rastro"
        assert eventos[0].origem == "entrevista"
        assert eventos[0].score_anterior == 750


class TestResilience:
    @pytest.mark.asyncio
    async def test_agent_failure_does_not_break_the_conversation(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_id = await authenticate(client)

        async def boom(cpf: str):
            raise RuntimeError("csv indisponivel")

        monkeypatch.setattr(credit_agent, "get_limit", boom)
        data = await say(client, session_id, "meu limite")
        assert data["state"] == "authenticated"
        assert data["authenticated"] is True
        assert "problema técnico" in data["message"].lower()

        monkeypatch.undo()
        data = await say(client, session_id, "meu limite")
        assert "R$" in data["message"]

    @pytest.mark.asyncio
    async def test_health_reports_version_and_llm_flag(self, client: AsyncClient) -> None:
        response = await client.get("http://test/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"]
        assert data["llm_enabled"] is False


class TestTriageLockoutExpiry:
    @pytest.mark.asyncio
    async def test_lockout_is_lifted_after_window(self, client: AsyncClient) -> None:
        # CPF valido nos digitos verificadores, mas ausente da base: o bloqueio e por
        # tentativa de autenticacao, nao por numero malformado.
        cpf = "52998224725"
        payload = {"cpf": cpf, "birthdate": "1990-01-01"}
        for _ in range(3):
            response = await client.post("/triage/authenticate", json=payload)
            assert response.status_code == 401

        response = await client.post("/triage/authenticate", json=payload)
        assert response.status_code == 429

        # Simula a passagem da janela de bloqueio
        record = triage_agent._attempts._records[cpf]
        record.last_failure = time.monotonic() - (
            get_settings().auth_lockout_minutes * 60 + 1
        )

        response = await client.post("/triage/authenticate", json=payload)
        assert response.status_code == 401
        assert response.json()["detail"]["remaining_attempts"] == 2
