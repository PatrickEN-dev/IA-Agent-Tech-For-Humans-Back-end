import logging
from collections import defaultdict
from datetime import date

from src.config import get_settings
from src.models.schemas import AuthRequest, AuthResponse
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService
from src.utils.exceptions import AuthenticationError, MaxAttemptsExceededError

logger = logging.getLogger(__name__)


class TriageAgent:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._csv_service = CSVService()
        self._auth_service = AuthService()
        self._llm_service = LLMService()
        self._failed_attempts: dict[str, int] = defaultdict(int)

    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        cpf = request.cpf.replace(".", "").replace("-", "")
        remaining = self._settings.max_auth_attempts - self._failed_attempts[cpf]

        if remaining <= 0:
            logger.warning(f"Max attempts exceeded for CPF: {cpf[:3]}***")
            raise MaxAttemptsExceededError()

        client = await self._csv_service.get_client_by_cpf(cpf)

        if not client:
            self._failed_attempts[cpf] += 1
            remaining = self._settings.max_auth_attempts - self._failed_attempts[cpf]
            logger.info(f"Client not found: {cpf[:3]}***, attempts remaining: {remaining}")
            raise AuthenticationError(remaining_attempts=remaining)

        client_birthdate = date.fromisoformat(client.data_nascimento)
        if client_birthdate != request.birthdate:
            self._failed_attempts[cpf] += 1
            remaining = self._settings.max_auth_attempts - self._failed_attempts[cpf]
            logger.info(f"Invalid birthdate for CPF: {cpf[:3]}***, attempts remaining: {remaining}")
            raise AuthenticationError(remaining_attempts=remaining)

        self._failed_attempts[cpf] = 0

        token = self._auth_service.create_token(cpf)

        intent = await self._llm_service.classify_intent(request.user_message)

        logger.info(f"Authentication successful for CPF: {cpf[:3]}***, intent: {intent}")

        return AuthResponse(
            authenticated=True,
            token=token,
            redirect_intent=intent,
            remaining_attempts=self._settings.max_auth_attempts,
        )

    def reset_attempts(self, cpf: str) -> None:
        normalized_cpf = cpf.replace(".", "").replace("-", "")
        self._failed_attempts[normalized_cpf] = 0
