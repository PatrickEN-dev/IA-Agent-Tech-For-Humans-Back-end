import logging
from datetime import date

from src.config import get_settings
from src.db.repositories import ClientRepository
from src.models.schemas import AuthRequest, AuthResponse
from src.services.auth_attempts import AuthAttemptTracker, auth_attempt_tracker
from src.services.auth_service import AuthService
from src.services.llm_service import LLMService
from src.utils.cpf import is_valid_cpf, mask_cpf
from src.utils.exceptions import (
    AuthenticationError,
    InvalidCPFError,
    MaxAttemptsExceededError,
)
from src.utils.text_normalizer import normalize_cpf

logger = logging.getLogger(__name__)


class TriageAgent:
    """Autenticacao por CPF + data de nascimento com limite de tentativas por CPF.

    A contagem de tentativas vive no `AuthAttemptTracker`, compartilhado com o chat:
    trocar de canal (ou abrir sessao nova) nao zera o contador.
    """

    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        auth_service: AuthService | None = None,
        llm_service: LLMService | None = None,
        attempt_tracker: AuthAttemptTracker | None = None,
    ) -> None:
        self._settings = get_settings()
        self._clients = client_repository or ClientRepository()
        self._auth_service = auth_service or AuthService()
        self._llm_service = llm_service or LLMService()
        self._attempts = attempt_tracker or auth_attempt_tracker

    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        cpf = normalize_cpf(request.cpf)

        if self._attempts.is_locked(cpf):
            logger.warning("Max attempts exceeded for CPF: %s", mask_cpf(cpf))
            raise MaxAttemptsExceededError()

        if not is_valid_cpf(cpf):
            remaining = self._attempts.register_failure(cpf)
            logger.info("Invalid CPF check digits: %s", mask_cpf(cpf))
            raise InvalidCPFError(remaining_attempts=remaining)

        client = await self._clients.get_by_cpf(cpf)

        if not client:
            remaining = self._attempts.register_failure(cpf)
            logger.info("Client not found: %s, attempts remaining: %s", mask_cpf(cpf), remaining)
            raise AuthenticationError(remaining_attempts=remaining)

        client_birthdate = date.fromisoformat(client.data_nascimento)
        if client_birthdate != request.birthdate:
            remaining = self._attempts.register_failure(cpf)
            logger.info(
                "Invalid birthdate for CPF: %s, attempts remaining: %s",
                mask_cpf(cpf),
                remaining,
            )
            raise AuthenticationError(remaining_attempts=remaining)

        self.reset_attempts(cpf)

        token = self._auth_service.create_token(cpf)

        intent = await self._llm_service.classify_intent(request.user_message)

        logger.info("Authentication successful for CPF: %s, intent: %s", mask_cpf(cpf), intent)

        return AuthResponse(
            authenticated=True,
            token=token,
            redirect_intent=intent,
            remaining_attempts=self._settings.max_auth_attempts,
        )

    def reset_attempts(self, cpf: str) -> None:
        self._attempts.reset(cpf)
