import pytest
from httpx import AsyncClient


class TestTriageAgent:
    @pytest.mark.asyncio
    async def test_cpf_with_spaces(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "123 456 789 01"},
        )
        data = response.json()
        assert data["state"] == "collecting_birthdate"

    @pytest.mark.asyncio
    async def test_cpf_in_sentence(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "meu cpf é 12345678901"},
        )
        data = response.json()
        assert data["state"] == "collecting_birthdate"

    @pytest.mark.asyncio
    async def test_birthdate_written_format(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "12345678901"},
        )

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "15 de maio de 1990"},
        )
        data = response.json()
        assert data["authenticated"] is True


class TestCreditAgent:
    @pytest.mark.asyncio
    async def test_limit_check_different_scores(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.get(
            "/credit/limit",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        data = response.json()
        assert data["current_limit"] > 0
        assert data["available_limit"] == data["current_limit"] * 0.8

    @pytest.mark.asyncio
    async def test_request_increase_zero_value(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/credit/request_increase",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"new_limit": 0},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_request_increase_very_high_value(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/credit/request_increase",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"new_limit": 1000000},
        )
        data = response.json()
        assert data["status"] == "denied"
        assert data["offer_interview"] is True

    @pytest.mark.asyncio
    async def test_request_increase_lower_than_current(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/credit/request_increase",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"new_limit": 5000},
        )
        data = response.json()
        assert data["status"] == "approved"


class TestInterviewAgent:
    @pytest.mark.asyncio
    async def test_interview_autonomo(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 6000.0,
                "tipo_emprego": "AUTONOMO",
                "despesas": 3000.0,
                "num_dependentes": 1,
                "tem_dividas": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_score"] is not None

    @pytest.mark.asyncio
    async def test_interview_mei(self, client: AsyncClient, valid_token: str) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 4000.0,
                "tipo_emprego": "MEI",
                "despesas": 2000.0,
                "num_dependentes": 0,
                "tem_dividas": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_score"] > 0

    @pytest.mark.asyncio
    async def test_interview_publico(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 12000.0,
                "tipo_emprego": "PUBLICO",
                "despesas": 5000.0,
                "num_dependentes": 2,
                "tem_dividas": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_score"] > 0

    @pytest.mark.asyncio
    async def test_interview_high_expenses(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 5000.0,
                "tipo_emprego": "CLT",
                "despesas": 4500.0,
                "num_dependentes": 3,
                "tem_dividas": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] is not None

    @pytest.mark.asyncio
    async def test_interview_zero_income(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 0,
                "tipo_emprego": "DESEMPREGADO",
                "despesas": 500.0,
                "num_dependentes": 0,
                "tem_dividas": False,
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_interview_many_dependents(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.post(
            "/interview/submit",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={
                "renda_mensal": 10000.0,
                "tipo_emprego": "FORMAL",
                "despesas": 8000.0,
                "num_dependentes": 5,
                "tem_dividas": False,
            },
        )
        assert response.status_code == 200


class TestExchangeAgent:
    @pytest.mark.asyncio
    async def test_exchange_gbp_to_brl(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.get(
            "/exchange",
            params={"from": "GBP", "to": "BRL"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rate"] > 0

    @pytest.mark.asyncio
    async def test_exchange_eur_to_usd(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.get(
            "/exchange",
            params={"from": "EUR", "to": "USD"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rate"] > 0

    @pytest.mark.asyncio
    async def test_exchange_brl_to_eur(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.get(
            "/exchange",
            params={"from": "BRL", "to": "EUR"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rate"] < 1

    @pytest.mark.asyncio
    async def test_exchange_jpy_to_brl(
        self, client: AsyncClient, valid_token: str
    ) -> None:
        response = await client.get(
            "/exchange",
            params={"from": "JPY", "to": "BRL"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert response.status_code == 200


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_message(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "   "},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_special_characters(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "!@#$%^&*()"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_very_long_message(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        long_message = "a" * 1000
        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": long_message},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_unicode_message(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "Olá 你好 مرحبا 🏦"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_session_id(self, client: AsyncClient) -> None:
        response = await client.post(
            "/unified/chat",
            json={"session_id": "invalid-uuid", "message": "olá"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_null_session_id(self, client: AsyncClient) -> None:
        response = await client.post(
            "/unified/chat",
            json={"session_id": None, "message": "olá"},
        )
        assert response.status_code == 200


class TestSecurityCases:
    @pytest.mark.asyncio
    async def test_sql_injection_attempt(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "'; DROP TABLE clientes; --"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_xss_attempt(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "<script>alert('xss')</script>"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_expired_token(self, client: AsyncClient) -> None:
        response = await client.get(
            "/credit/limit",
            headers={
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwMSIsImV4cCI6MTYwMDAwMDAwMH0.invalid"
            },
        )
        assert response.status_code == 401


class TestFlowTransitions:
    @pytest.mark.asyncio
    async def test_transition_credit_to_interview(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "12345678901"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "15/05/1990"}
        )
        await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "aumento de limite"},
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "100000"}
        )

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "sim, quero a entrevista"},
        )
        data = response.json()
        assert "renda" in data["message"].lower() or data["state"] == "interview_income"

    @pytest.mark.asyncio
    async def test_transition_interview_to_credit(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "12345678901"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "15/05/1990"}
        )
        await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "atualizar perfil"},
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "8000"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "CLT"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "3000"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "0"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "não"}
        )

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "sim"},
        )
        data = response.json()
        assert "limite" in data["message"].lower() or "R$" in data["message"]

    @pytest.mark.asyncio
    async def test_back_to_main_menu(self, client: AsyncClient) -> None:
        init = await client.post("/unified/init")
        session_id = init.json()["session_id"]

        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "12345678901"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "15/05/1990"}
        )
        await client.post(
            "/unified/chat", json={"session_id": session_id, "message": "meu limite"}
        )

        response = await client.post(
            "/unified/chat",
            json={"session_id": session_id, "message": "cotação do dólar"},
        )
        data = response.json()
        assert data["state"] == "exchange_from" or "moeda" in data["message"].lower()
