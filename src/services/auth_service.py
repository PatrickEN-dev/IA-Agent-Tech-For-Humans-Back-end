import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer()


class AuthService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create_token(self, cpf: str) -> str:
        expires = datetime.now(timezone.utc) + timedelta(
            minutes=self._settings.jwt_expiration_minutes
        )
        payload = {
            "sub": cpf,
            "exp": expires,
            "iat": datetime.now(timezone.utc),
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
            cpf: str | None = payload.get("sub")
            if cpf is None:
                return None
            return cpf
        except JWTError as e:
            logger.warning(f"Token verification failed: {e}")
            return None


def get_current_cpf(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> str:
    auth_service = AuthService(settings)
    cpf = auth_service.verify_token(credentials.credentials)

    if cpf is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return cpf
