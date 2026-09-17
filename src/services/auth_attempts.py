"""Contagem de tentativas de autenticação por CPF, compartilhada entre chat e endpoint.

Antes, o chat contava tentativas por sessão e o `TriageAgent` contava por CPF, em
estruturas separadas: abrir uma sessão nova zerava o contador do chat, então três erros
por sessão eram infinitos. Aqui a contagem é por CPF e vale para os dois caminhos.

O estado vive em memória de propósito: é um freio contra força bruta casual em uma
demo de processo único, não um controle de segurança distribuído. Em produção isso
seria Redis com a mesma interface (ver `SessionStore` em `session_store.py`).
"""

import logging
import time
from dataclasses import dataclass, field

from src.config import get_settings
from src.utils.cpf import mask_cpf, strip_cpf

logger = logging.getLogger(__name__)


@dataclass
class AttemptRecord:
    failures: int = 0
    last_failure: float = 0.0


@dataclass
class AuthAttemptTracker:
    """Janela deslizante de falhas por CPF.

    O bloqueio expira depois de `auth_lockout_minutes`: sem isso, três erros
    (inclusive de terceiros) trancariam o CPF até o processo reiniciar.
    """

    _records: dict[str, AttemptRecord] = field(default_factory=dict)

    @property
    def _settings(self):  # type: ignore[no-untyped-def]
        return get_settings()

    def _record_for(self, cpf: str) -> AttemptRecord:
        key = strip_cpf(cpf)
        record = self._records.get(key)
        if record is None:
            record = AttemptRecord()
            self._records[key] = record
            return record

        lockout_seconds = self._settings.auth_lockout_minutes * 60
        if record.failures and time.monotonic() - record.last_failure > lockout_seconds:
            record.failures = 0
        return record

    def is_locked(self, cpf: str) -> bool:
        return self._record_for(cpf).failures >= self._settings.max_auth_attempts

    def remaining(self, cpf: str) -> int:
        record = self._record_for(cpf)
        return max(0, self._settings.max_auth_attempts - record.failures)

    def register_failure(self, cpf: str) -> int:
        """Registra uma falha e devolve quantas tentativas ainda restam."""
        record = self._record_for(cpf)
        record.failures += 1
        record.last_failure = time.monotonic()
        remaining = max(0, self._settings.max_auth_attempts - record.failures)
        if remaining == 0:
            logger.warning("CPF %s bloqueado por excesso de tentativas", mask_cpf(cpf))
        return remaining

    def reset(self, cpf: str) -> None:
        self._records.pop(strip_cpf(cpf), None)

    def reset_all(self) -> None:
        """Usado pela fixture de testes: todos os testes autenticam com o mesmo CPF."""
        self._records.clear()


# Instância compartilhada pelo TriageAgent e pelo Orchestrator (ambos singletons
# criados em src/api/routes.py).
auth_attempt_tracker = AuthAttemptTracker()
