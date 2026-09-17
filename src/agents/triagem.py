import logging
import time
from dataclasses import dataclass
from datetime import date

from src.config import get_settings
from src.models.schemas import AuthRequest, AuthResponse
from src.services.auth_service import AuthService
from src.services.csv_service import CSVService
from src.services.llm_service import LLMService
from src.utils.exceptions import AuthenticationError, MaxAttemptsExceededError
from src.utils.text_normalizer import normalize_cpf

logger = logging.getLogger(__name__)


@dataclass
class _AttemptRecord:
    failures: int = 0
    last_failure: float = 0.0


class TriageAgent:
    """Autenticacao por CPF + data de nascimento com limite de tentativas por CPF.

    O bloqueio expira depois de `auth_lockout_minutes`: sem isso, tres erros
    (inclusive de terceiros) trancariam o CPF ate o processo reiniciar.
    """

    def __init__(
        self,
        csv_service: CSVService | None = None,
        auth_service: AuthService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self._settings = get_settings()
        self._csv_service = csv_service or CSVService()
        self._auth_service = auth_service or AuthService()
        self._llm_service = llm_service or LLMService()
        self._attempts: dict[str, _AttemptRecord] = {}

    def _record_for(self, cpf: str) -> _AttemptRecord:
        record = self._attempts.get(cpf)
        if record is None:
            record = _AttemptRecord()
            self._attempts[cpf] = record
            return record

        lockout_seconds = self._settings.auth_lockout_minutes * 60
        if record.failures and time.monotonic() - record.last_failure > lockout_seconds:
            record.failures = 0
        return record

    def _register_failure(self, record: _AttemptRecord) -> int:
        record.failures += 1
        record.last_failure = time.monotonic()
        return max(0, self._settings.max_auth_attempts - record.failures)

    async def authenticate(self, request: AuthRequest) -> AuthResponse:
        cpf = normalize_cpf(request.cpf)
        record = self._record_for(cpf)

        if record.failures >= self._settings.max_auth_attempts:
            logger.warning(f"Max attempts exceeded for CPF: {cpf[:3]}***")
            raise MaxAttemptsExceededError()

        client = await self._csv_service.get_client_by_cpf(cpf)

        if not client:
            remaining = self._register_failure(record)
            logger.info(f"Client not found: {cpf[:3]}***, attempts remaining: {remaining}")
            raise AuthenticationError(remaining_attempts=remaining)

        client_birthdate = date.fromisoformat(client.data_nascimento)
        if client_birthdate != request.birthdate:
            remaining = self._register_failure(record)
            logger.info(
                f"Invalid birthdate for CPF: {cpf[:3]}***, attempts remaining: {remaining}"
            )
            raise AuthenticationError(remaining_attempts=remaining)

        self.reset_attempts(cpf)

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
        self._attempts.pop(normalize_cpf(cpf), None)
