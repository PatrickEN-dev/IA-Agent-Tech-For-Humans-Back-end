"""Limite de requisições por IP, desligável por configuração.

O `slowapi` exige um parâmetro `request: Request` na assinatura do endpoint para
descobrir o IP. O decorador `limit` daqui embrulha isso e, quando
`RATE_LIMIT_ENABLED=false`, devolve a função intacta — sem isso a suíte inteira
receberia 429 na segunda dezena de testes.
"""

import logging
from collections.abc import Callable
from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import get_settings

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, enabled=get_settings().rate_limit_enabled)

_LIMIT_KEYS = {
    "chat": "rate_limit_chat",
    "auth": "rate_limit_auth",
    "signup": "rate_limit_signup",
}


def limit(kind: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Aplica o limite configurado para `kind` ("chat", "auth", "signup")."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return func
        value = getattr(settings, _LIMIT_KEYS[kind])
        return limiter.limit(value)(func)

    return decorator
