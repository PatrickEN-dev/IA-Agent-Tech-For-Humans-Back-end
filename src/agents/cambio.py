import logging
from datetime import datetime, timezone

import httpx

from src.config import get_settings
from src.models.schemas import ExchangeRateResponse

logger = logging.getLogger(__name__)

FALLBACK_APIS = [
    "https://api.exchangerate-api.com/v4/latest",
    "https://open.er-api.com/v6/latest",
]

FALLBACK_RATES: dict[str, dict[str, float]] = {
    "USD": {"BRL": 5.38, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0, "ARS": 1450.0},
    "EUR": {"BRL": 5.85, "USD": 1.09, "GBP": 0.86, "JPY": 163.0, "ARS": 1580.0},
    "BRL": {"USD": 0.186, "EUR": 0.171, "GBP": 0.147, "JPY": 27.9, "ARS": 270.0},
    "GBP": {"BRL": 6.80, "USD": 1.27, "EUR": 1.16, "JPY": 190.0, "ARS": 1840.0},
    "JPY": {"BRL": 0.036, "USD": 0.0067, "EUR": 0.0061, "GBP": 0.0053, "ARS": 9.67},
    "ARS": {"BRL": 0.0037, "USD": 0.00069, "EUR": 0.00063, "GBP": 0.00054, "JPY": 0.103},
}


class ExchangeAgent:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._rate_cache: dict[str, tuple[float, datetime]] = {}
        self._cache_ttl_seconds = 300

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
        cache_key = f"{from_currency}_{to_currency}"
        cached = self._rate_cache.get(cache_key)
        if cached:
            rate, cached_time = cached
            if (datetime.now(timezone.utc) - cached_time).total_seconds() < self._cache_ttl_seconds:
                return rate, cached_time, "cached"

        for api_url in FALLBACK_APIS:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    url = f"{api_url}/{from_currency}"
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()

                    rates_key = "rates"
                    if rates_key in data and to_currency in data[rates_key]:
                        rate = data[rates_key][to_currency]
                        now = datetime.now(timezone.utc)
                        self._rate_cache[cache_key] = (rate, now)
                        logger.info(f"Exchange rate fetched: {from_currency}/{to_currency} = {rate}")
                        return rate, now, "live"
            except Exception as e:
                logger.warning(f"API {api_url} failed: {e}")
                continue

        rate = self._get_fallback_rate(from_currency, to_currency)
        logger.warning(f"Using fallback rate for {from_currency}/{to_currency}")
        return rate, datetime.now(timezone.utc), "fallback"

    def _get_fallback_rate(self, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return 1.0
        if from_currency in FALLBACK_RATES and to_currency in FALLBACK_RATES[from_currency]:
            return FALLBACK_RATES[from_currency][to_currency]
        if to_currency in FALLBACK_RATES and from_currency in FALLBACK_RATES[to_currency]:
            return 1.0 / FALLBACK_RATES[to_currency][from_currency]
        return 1.0

    def _format_message(
        self, from_currency: str, to_currency: str, rate: float, source: str
    ) -> str:
        if source == "live":
            source_text = "(cotacao em tempo real)"
        elif source == "cached":
            source_text = "(cotacao recente)"
        else:
            source_text = "(cotacao indicativa)"
        return f"1 {from_currency} = {rate:.4f} {to_currency} {source_text}"
