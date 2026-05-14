"""Foreign exchange API client.

Hits one or more public providers, caches the result for a short window, and
falls back to an offline table if every provider fails — so the UX never
breaks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final, Literal

import httpx

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

_PROVIDERS: Final[tuple[str, ...]] = (
    "https://api.exchangerate-api.com/v4/latest",
    "https://open.er-api.com/v6/latest",
)

_FALLBACK: Final[dict[str, dict[str, float]]] = {
    "USD": {"BRL": 5.38, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0, "ARS": 1450.0},
    "EUR": {"BRL": 5.85, "USD": 1.09, "GBP": 0.86, "JPY": 163.0, "ARS": 1580.0},
    "BRL": {"USD": 0.186, "EUR": 0.171, "GBP": 0.147, "JPY": 27.9, "ARS": 270.0},
    "GBP": {"BRL": 6.80, "USD": 1.27, "EUR": 1.16, "JPY": 190.0, "ARS": 1840.0},
    "JPY": {"BRL": 0.036, "USD": 0.0067, "EUR": 0.0061, "GBP": 0.0053, "ARS": 9.67},
    "ARS": {"BRL": 0.0037, "USD": 0.00069, "EUR": 0.00063, "GBP": 0.00054, "JPY": 0.103},
}

Source = Literal["live", "cached", "fallback"]


class ExchangeRateAPI:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache: dict[str, tuple[float, datetime]] = {}

    async def get_rate(
        self, from_currency: str, to_currency: str
    ) -> tuple[float, datetime, Source]:
        if from_currency == to_currency:
            return 1.0, datetime.now(timezone.utc), "live"

        key = f"{from_currency}_{to_currency}"
        if cached := self._cached(key):
            return cached[0], cached[1], "cached"

        for provider in _PROVIDERS:
            rate = await self._fetch(provider, from_currency, to_currency)
            if rate is not None:
                now = datetime.now(timezone.utc)
                self._cache[key] = (rate, now)
                return rate, now, "live"

        logger.warning("All providers failed for %s/%s — using fallback", from_currency, to_currency)
        return self._fallback(from_currency, to_currency), datetime.now(timezone.utc), "fallback"

    def _cached(self, key: str) -> tuple[float, datetime] | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        rate, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age >= self._settings.exchange_cache_ttl_seconds:
            return None
        return rate, fetched_at

    async def _fetch(
        self, provider: str, from_currency: str, to_currency: str
    ) -> float | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{provider}/{from_currency}")
                response.raise_for_status()
                rates = response.json().get("rates") or {}
        except Exception as exc:
            logger.warning("Exchange provider %s failed: %s", provider, exc)
            return None
        rate = rates.get(to_currency)
        if rate is None:
            return None
        return float(rate)

    def _fallback(self, from_currency: str, to_currency: str) -> float:
        forward = _FALLBACK.get(from_currency, {}).get(to_currency)
        if forward is not None:
            return forward
        inverse = _FALLBACK.get(to_currency, {}).get(from_currency)
        if inverse:
            return 1.0 / inverse
        return 1.0
