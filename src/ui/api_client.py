import logging
from datetime import date
from typing import Literal, Optional

import httpx
import streamlit as st

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.timeout = 30.0

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if "token" in st.session_state and st.session_state.token:
            headers["Authorization"] = f"Bearer {st.session_state.token}"
        return headers

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def authenticate(
        self, cpf: str, birthdate: date, user_message: Optional[str] = None
    ) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "cpf": cpf,
                    "birthdate": birthdate.isoformat(),
                    "user_message": user_message,
                }
                response = await client.post(
                    f"{self.base_url}/triage/authenticate",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("token"):
                        st.session_state.token = data["token"]
                    return data
                else:
                    return {
                        "authenticated": False,
                        "token": None,
                        "redirect_intent": None,
                        "remaining_attempts": 3,
                        "error": response.json(),
                    }
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return {
                "authenticated": False,
                "token": None,
                "redirect_intent": None,
                "remaining_attempts": 3,
                "error": str(e),
            }

    async def get_credit_limit(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/credit/limit",
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": response.json()}
        except Exception as e:
            logger.error(f"Get credit limit failed: {e}")
            return {"error": str(e)}

    async def request_limit_increase(self, new_limit: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/credit/request_increase",
                    json={"new_limit": new_limit},
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": response.json()}
        except Exception as e:
            logger.error(f"Request limit increase failed: {e}")
            return {"error": str(e)}

    async def submit_interview(
        self,
        renda_mensal: float,
        tipo_emprego: Literal[
            "CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"
        ],
        despesas: float,
        num_dependentes: int,
        tem_dividas: bool,
    ) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "renda_mensal": renda_mensal,
                    "tipo_emprego": tipo_emprego,
                    "despesas": despesas,
                    "num_dependentes": num_dependentes,
                    "tem_dividas": tem_dividas,
                }
                response = await client.post(
                    f"{self.base_url}/interview/submit",
                    json=payload,
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": response.json()}
        except Exception as e:
            logger.error(f"Submit interview failed: {e}")
            return {"error": str(e)}

    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/exchange",
                    params={"from": from_currency, "to": to_currency},
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    return {"error": response.json()}
        except Exception as e:
            logger.error(f"Get exchange rate failed: {e}")
            return {"error": str(e)}

    async def chat(self, session_id: str, message: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat",
                    json={"session_id": session_id, "message": message},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("token"):
                        st.session_state.token = data["token"]
                    return data
                else:
                    return {"error": response.json(), "message": "Erro ao processar mensagem."}
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return {"error": str(e), "message": "Erro de conexão com o servidor."}
