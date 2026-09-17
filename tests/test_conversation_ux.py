"""Cenários de conversa do orquestrador unificado que fazem diferença para o usuário."""

import pytest
from httpx import AsyncClient


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


class TestBeforeAuthentication:
    @pytest.mark.asyncio
    async def test_intent_before_auth_is_remembered(self, client: AsyncClient) -> None:
        session_id = await start(client)

        data = await say(client, session_id, "quero ver meu limite")
        assert data["state"] == "collecting_cpf"
        assert "cpf" in data["message"].lower()

        data = await say(client, session_id, "12345678909")
        assert data["state"] == "collecting_birthdate"

        data = await say(client, session_id, "15/05/1990")
        assert data["authenticated"] is True
        assert "R$" in data["message"]
        assert "limite" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_first_message_with_cpf_without_init(self, client: AsyncClient) -> None:
        data = await say(client, None, "meu cpf é 123.456.789-09")
        assert data["state"] == "collecting_birthdate"

    @pytest.mark.asyncio
    async def test_greeting_does_not_count_as_failed_attempt(
        self, client: AsyncClient
    ) -> None:
        session_id = await start(client)
        for _ in range(4):
            data = await say(client, session_id, "oi")
            assert data["state"] == "collecting_cpf"

    @pytest.mark.asyncio
    async def test_lockout_after_three_failed_attempts(self, client: AsyncClient) -> None:
        session_id = await start(client)

        await say(client, session_id, "99999999999")
        await say(client, session_id, "99999999999")
        data = await say(client, session_id, "99999999999")
        assert data["state"] == "goodbye"
        assert "segurança" in data["message"].lower()

        data = await say(client, session_id, "12345678909")
        assert data["state"] == "goodbye"
        assert data["authenticated"] is False

    @pytest.mark.asyncio
    async def test_wrong_birthdate_counts_toward_lockout(self, client: AsyncClient) -> None:
        session_id = await start(client)
        await say(client, session_id, "12345678909")

        await say(client, session_id, "01/01/2000")
        await say(client, session_id, "02/02/2000")
        data = await say(client, session_id, "03/03/2000")
        assert data["state"] == "goodbye"


class TestExchange:
    @pytest.mark.asyncio
    async def test_currency_in_intent_answers_directly(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "cotação do dólar")
        assert data["state"] == "authenticated"
        assert "USD" in data["message"] and "BRL" in data["message"]

    @pytest.mark.asyncio
    async def test_pair_in_one_message(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "quanto tá o euro em reais?")
        assert "1 EUR" in data["message"] and "BRL" in data["message"]

    @pytest.mark.asyncio
    async def test_generic_request_asks_currency(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "câmbio")
        assert data["state"] == "exchange_from"

        data = await say(client, session_id, "libra")
        assert data["state"] == "authenticated"
        assert "GBP" in data["message"] and "BRL" in data["message"]

    @pytest.mark.asyncio
    async def test_brl_as_source_asks_target(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "cotação do real")
        assert data["state"] == "exchange_to"

        data = await say(client, session_id, "euro")
        assert "1 BRL" in data["message"] and "EUR" in data["message"]


class TestCreditIncrease:
    @pytest.mark.asyncio
    async def test_value_in_intent_message_is_used(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "quero aumentar meu limite para 100 mil")
        assert data["state"] == "authenticated"
        assert "entrevista" in data["message"].lower()
        assert data["redirect_suggestion"] is not None

    @pytest.mark.asyncio
    async def test_limit_uses_brazilian_currency_format(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "meu limite")
        assert "R$ 5.000,00" in data["message"]
        assert "R$ 15.000,00" in data["message"]

    @pytest.mark.asyncio
    async def test_value_below_current_limit_is_explained(self, client: AsyncClient) -> None:
        """Pedir o que ja se tem nao e "aprovado": e explicar que ja esta disponivel."""
        session_id = await authenticate(client)
        await say(client, session_id, "quero aumento")
        data = await say(client, session_id, "3 mil")
        assert "já está disponível" in data["message"].lower()
        assert "R$ 5.000,00" in data["message"]

    @pytest.mark.asyncio
    async def test_value_within_ceiling_is_approved_and_persisted(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "quero aumento")
        data = await say(client, session_id, "12 mil")
        assert "aprovado" in data["message"].lower()

        # O limite mudou de verdade: a consulta seguinte precisa refletir isso.
        data = await say(client, session_id, "meu limite")
        assert "R$ 12.000,00" in data["message"]


class TestFlowEscapes:
    @pytest.mark.asyncio
    async def test_asking_limit_mid_increase_flow(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "quero aumento")
        assert data["state"] == "credit_increase_flow"

        data = await say(client, session_id, "qual meu limite atual?")
        assert data["state"] == "authenticated"
        assert "R$" in data["message"]

    @pytest.mark.asyncio
    async def test_cancel_mid_interview(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        data = await say(client, session_id, "5000")
        assert data["state"] == "interview_employment"

        data = await say(client, session_id, "cancelar")
        assert data["state"] == "authenticated"
        assert "cancelei" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_goodbye_mid_interview(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        data = await say(client, session_id, "tchau")
        assert data["state"] == "goodbye"

    @pytest.mark.asyncio
    async def test_exchange_request_mid_interview(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        data = await say(client, session_id, "na verdade quero a cotação do dólar")
        assert data["state"] == "authenticated"
        assert "USD" in data["message"]

    @pytest.mark.asyncio
    async def test_unparseable_answer_gets_helpful_message(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        data = await say(client, session_id, "não sei exatamente")
        assert data["state"] == "interview_income"
        assert "aproximado" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_debts_question_handles_natural_negation(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        await say(client, session_id, "8 mil")
        await say(client, session_id, "carteira assinada")
        await say(client, session_id, "3k")
        await say(client, session_id, "nenhum")
        data = await say(client, session_id, "não tenho dívidas, tudo pago")

        # Coleta completa: o fluxo mostra o resumo e so grava depois do aceite.
        assert data["state"] == "interview_confirm"
        assert "dívidas em aberto: não" in data["message"].lower()

        data = await say(client, session_id, "sim")
        assert "score" in data["message"].lower()
        assert data["redirect_suggestion"] is not None


class TestPendingOffers:
    @pytest.mark.asyncio
    async def test_negated_offer_is_rejected(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")
        data = await say(client, session_id, "não quero aumento")
        assert data["state"] == "authenticated"
        assert "tudo bem" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_negated_request_without_offer_shows_menu(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "não quero aumento")
        assert data["state"] == "authenticated"
        assert "tudo bem" in data["message"].lower()

        # negacao que nao e recusa continua sendo atendida
        data = await say(client, session_id, "não sei meu limite, pode ver?")
        assert "R$" in data["message"]

    @pytest.mark.asyncio
    async def test_topic_change_clears_offer(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")
        data = await say(client, session_id, "cotação do dólar")
        assert "USD" in data["message"]

        data = await say(client, session_id, "sim")
        assert data["state"] == "authenticated"
        assert "posso te ajudar" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_unclear_reply_keeps_offer(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")
        data = await say(client, session_id, "hmm talvez")
        assert "sim ou não" in data["message"].lower()

        data = await say(client, session_id, "sim")
        assert data["state"] == "credit_increase_flow"

    @pytest.mark.asyncio
    async def test_yes_after_interview_shows_new_limit(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")
        await say(client, session_id, "8000")
        await say(client, session_id, "CLT")
        await say(client, session_id, "3000")
        await say(client, session_id, "2")
        await say(client, session_id, "não")
        data = await say(client, session_id, "sim")
        assert "novo limite" in data["message"].lower()
        assert "R$" in data["message"]


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_session_restarts_after_goodbye(self, client: AsyncClient) -> None:
        session_id = await start(client)
        data = await say(client, session_id, "tchau")
        assert data["state"] == "goodbye"

        data = await say(client, session_id, "oi")
        assert data["state"] == "collecting_cpf"

    @pytest.mark.asyncio
    async def test_goodbye_uses_first_name(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "era só isso, tchau")
        assert data["state"] == "goodbye"
        assert "Maria" in data["message"]

    @pytest.mark.asyncio
    async def test_empty_message_reprompts(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "   ")
        assert data["state"] == "authenticated"
        assert data["message"]

    @pytest.mark.asyncio
    async def test_off_topic_without_llm_shows_menu(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        data = await say(client, session_id, "quem descobriu o brasil?")
        assert data["state"] == "authenticated"
        assert "limite" in data["message"].lower()


class TestOfertaRespondidaComValor:
    @pytest.mark.asyncio
    async def test_aceite_com_valor_nao_repete_a_pergunta(
        self, client: AsyncClient
    ) -> None:
        """"quero 1 milhao" e aceite e valor na mesma frase.

        "quero" sozinho e confirmacao; com um numero junto, o valor nao pode ser
        descartado para perguntar de novo o que o cliente ja respondeu.
        """
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")

        data = await say(client, session_id, "quero 1 milhao")
        assert data["state"] == "authenticated"
        assert "qual valor" not in data["message"].lower()
        assert "R$ 1.000.000,00" in data["message"]

    @pytest.mark.asyncio
    async def test_aceite_sem_valor_ainda_pergunta(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "meu limite")

        data = await say(client, session_id, "quero sim")
        assert data["state"] == "credit_increase_flow"
        assert "qual valor" in data["message"].lower()
