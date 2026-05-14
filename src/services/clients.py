"""CSV-backed client repository.

Encapsulates all I/O so the rest of the codebase never sees the file format.
Swap this for SQL/NoSQL later by implementing the same interface.

I/O runs through `asyncio.to_thread` so the event loop is never blocked by
the synchronous `FileLock` + CSV operations.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from src.config import Settings, get_settings
from src.models.domain import Client, ScoreLimit
from src.utils.extract import normalize_cpf

logger = logging.getLogger(__name__)

_CLIENT_FIELDS = ("cpf", "nome", "data_nascimento", "score", "limite_atual")
_REQUEST_FIELDS = (
    "cpf_cliente",
    "data_hora_solicitacao",
    "limite_atual",
    "novo_limite_solicitado",
    "status_pedido",
)


def _row_to_client(row: dict[str, str]) -> Client:
    return Client(
        cpf=row["cpf"],
        name=row["nome"],
        birthdate=date.fromisoformat(row["data_nascimento"]),
        score=int(row.get("score", 0) or 0),
        current_limit=float(row.get("limite_atual", 0) or 0),
    )


class ClientRepository:
    """Read/write access to the clients and score-limit CSV files."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _lock(self, path: Path) -> FileLock:
        return FileLock(str(path.with_suffix(".lock")), timeout=10)

    async def get_by_cpf(self, cpf: str) -> Client | None:
        return await asyncio.to_thread(self._read_client, cpf)

    async def update_score(self, cpf: str, new_score: int) -> bool:
        return await asyncio.to_thread(self._write_score, cpf, new_score)

    async def append_limit_request(
        self,
        cpf: str,
        current_limit: float,
        requested_limit: float,
        status: str,
    ) -> None:
        await asyncio.to_thread(
            self._append_limit_request_sync,
            cpf, current_limit, requested_limit, status,
        )

    async def read_score_limits(self) -> list[ScoreLimit]:
        return await asyncio.to_thread(self._read_score_limits_sync)

    # ---- sync helpers (run in a worker thread) ----------------------------

    def _read_client(self, cpf: str) -> Client | None:
        normalized = normalize_cpf(cpf)
        path = self._settings.clients_csv_path
        with self._lock(path):
            if not path.exists():
                return None
            with path.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if normalize_cpf(row.get("cpf", "")) == normalized:
                        return _row_to_client(row)
        return None

    def _write_score(self, cpf: str, new_score: int) -> bool:
        normalized = normalize_cpf(cpf)
        path = self._settings.clients_csv_path
        with self._lock(path):
            if not path.exists():
                return False
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
                fieldnames = reader.fieldnames or list(_CLIENT_FIELDS)

            updated = False
            for row in rows:
                if normalize_cpf(row.get("cpf", "")) == normalized:
                    row["score"] = str(new_score)
                    updated = True
                    break

            if updated:
                with path.open("w", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                logger.info(
                    "Updated score for CPF %s***: %s", normalized[:3], new_score
                )
        return updated

    def _append_limit_request_sync(
        self,
        cpf: str,
        current_limit: float,
        requested_limit: float,
        status: str,
    ) -> None:
        path = self._settings.limit_requests_csv_path
        record: dict[str, Any] = {
            "cpf_cliente": cpf,
            "data_hora_solicitacao": datetime.now(timezone.utc).isoformat(),
            "limite_atual": current_limit,
            "novo_limite_solicitado": requested_limit,
            "status_pedido": status,
        }
        with self._lock(path):
            file_exists = path.exists()
            with path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(_REQUEST_FIELDS))
                if not file_exists:
                    writer.writeheader()
                writer.writerow(record)
        logger.info("Recorded limit request for CPF %s***: %s", cpf[:3], status)

    def _read_score_limits_sync(self) -> list[ScoreLimit]:
        path = self._settings.score_limits_csv_path
        with self._lock(path):
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8", newline="") as fh:
                return [
                    ScoreLimit(
                        score_min=int(row["score_min"]),
                        score_max=int(row["score_max"]),
                        limit=float(row["limite"]),
                    )
                    for row in csv.DictReader(fh)
                ]
