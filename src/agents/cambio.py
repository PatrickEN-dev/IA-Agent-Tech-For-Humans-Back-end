import logging
from datetime import datetime, timezone

import httpx

from src.config import get_settings
from src.models.schemas import ExchangeRateResponse
from src.services.llm_service import LLMService

logger = logging.getLogger(__name__)

MOCK_RATES: dict[str, dict[str, float]] = {
    "USD": {"BRL": 4.95, "EUR": 0.92, "GBP": 0.79},
    "EUR": {"BRL": 5.38, "USD": 1.09, "GBP": 0.86},
    "BRL": {"USD": 0.20, "EUR": 0.19, "GBP": 0.16},
    "GBP": {"BRL": 6.27, "USD": 1.27, "EUR": 1.16},
}


class ExchangeAgent:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm_service = LLMService()

    async def get_rate(self, from_currency: str, to_currency: str) -> ExchangeRateResponse:
        rate, timestamp, source = await self._fetch_rate(from_currency, to_currency)

        message = self._format_message(from_currency, to_currency, rate, source)

        return ExchangeRateResponse(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            timestamp=timestamp,
            message=message,
        )

    async def _fetch_rate(
        self, from_currency: str, to_currency: str
    ) -> tuple[float, datetime, str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self._settings.exchange_api_url}/{from_currency}"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                if to_currency in data.get("rates", {}):
                    return (
                        data["rates"][to_currency],
                        datetime.now(timezone.utc),
                        "live",
                    )
        except Exception as e:
            logger.warning(f"Failed to fetch exchange rate: {e}")

        rate = self._get_mock_rate(from_currency, to_currency)
        return rate, datetime.now(timezone.utc), "mock"

    def _get_mock_rate(self, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return 1.0
        if from_currency in MOCK_RATES and to_currency in MOCK_RATES[from_currency]:
            return MOCK_RATES[from_currency][to_currency]
        return 1.0

    def _format_message(
        self, from_currency: str, to_currency: str, rate: float, source: str
    ) -> str:
        source_text = "(live)" if source == "live" else "(indicative)"
        return f"1 {from_currency} = {rate:.4f} {to_currency} {source_text}"
