"""Exchange agent — converts between currencies."""
from __future__ import annotations

import logging

from src.agents.base import Agent, AgentReply
from src.core.session import (
    AGENT_EXCHANGE,
    STATE_AUTHENTICATED,
    STATE_EXCHANGE_FROM,
    STATE_EXCHANGE_TO,
    Session,
)
from src.models.schemas import ExchangeRateResponse
from src.services.exchange_api import ExchangeRateAPI
from src.utils.extract import extract_currency

logger = logging.getLogger(__name__)

_SOURCE_LABEL = {
    "live": "cotação em tempo real",
    "cached": "cotação recente",
    "fallback": "cotação indicativa",
}


class ExchangeAgent(Agent):
    name = AGENT_EXCHANGE

    def __init__(self, api: ExchangeRateAPI | None = None) -> None:
        self._api = api or ExchangeRateAPI()

    async def get_rate(self, from_currency: str, to_currency: str) -> ExchangeRateResponse:
        rate, timestamp, source = await self._api.get_rate(from_currency, to_currency)
        message = (
            f"1 {from_currency} = {rate:.4f} {to_currency} ({_SOURCE_LABEL[source]})"
        )
        return ExchangeRateResponse(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            timestamp=timestamp,
            message=message,
        )

    async def handle(self, session: Session, message: str) -> AgentReply:
        if session.state == STATE_AUTHENTICATED:
            session.collected = {}
            return AgentReply(
                text="Qual moeda você quer converter? Por exemplo: USD, EUR, GBP, JPY.",
                next_state=STATE_EXCHANGE_FROM,
            )

        if session.state == STATE_EXCHANGE_FROM:
            currency = extract_currency(message)
            if currency is None:
                return AgentReply(
                    text="Não reconheci essa moeda. Tente USD, EUR, GBP, JPY ou ARS. "
                         "(Ou diga 'cancelar' para sair.)",
                    next_state=STATE_EXCHANGE_FROM,
                    humanize=False,
                )
            session.collected["from_currency"] = currency
            return AgentReply(
                text=f"Converter {currency} para qual moeda? (BRL = Real, por exemplo)",
                next_state=STATE_EXCHANGE_TO,
            )

        if session.state == STATE_EXCHANGE_TO:
            currency = extract_currency(message)
            if currency is None:
                return AgentReply(
                    text="Não reconheci a moeda de destino. Tente BRL, USD, EUR, GBP. "
                         "(Ou diga 'cancelar' para sair.)",
                    next_state=STATE_EXCHANGE_TO,
                    humanize=False,
                )
            from_currency = session.collected.get("from_currency", "USD")
            result = await self.get_rate(from_currency, currency)
            session.collected = {}
            return AgentReply(
                text=f"{result.message}. Posso te ajudar com mais alguma coisa?",
                next_state=STATE_AUTHENTICATED,
            )

        # Fallback: should not happen, but if so reset the flow.
        return AgentReply(
            text="Qual moeda você quer converter?",
            next_state=STATE_EXCHANGE_FROM,
        )
