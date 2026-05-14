from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)
_security = HTTPBearer()


class AuthService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create_token(self, cpf: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": cpf,
            "iat": now,
            "exp": now + timedelta(minutes=self._settings.jwt_expiration_minutes),
        }
        return jwt.encode(
            payload,
            self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
        )

    def verify_token(self, token: str) -> str | None:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret_key,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            logger.warning("Token verification failed: %s", exc)
            return None
        return payload.get("sub")


def get_current_cpf(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    settings: Settings = Depends(get_settings),
) -> str:
    cpf = AuthService(settings).verify_token(credentials.credentials)
    if cpf is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return cpf
