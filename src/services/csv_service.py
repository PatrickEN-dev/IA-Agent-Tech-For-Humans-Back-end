import csv
import logging
from pathlib import Path
from typing import Any

from filelock import FileLock

from src.config import get_settings
from src.models.domain import Client

logger = logging.getLogger(__name__)


class CSVService:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _get_lock(self, file_path: Path) -> FileLock:
        lock_path = file_path.with_suffix(".lock")
        return FileLock(str(lock_path), timeout=10)

    async def get_client_by_cpf(self, cpf: str) -> Client | None:
        file_path = self._settings.clients_csv_path
        normalized_cpf = cpf.replace(".", "").replace("-", "")

        with self._get_lock(file_path):
            if not file_path.exists():
                return None

            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_cpf = row.get("cpf", "").replace(".", "").replace("-", "")
                    if row_cpf == normalized_cpf:
                        return Client(
                            cpf=row["cpf"],
                            nome=row["nome"],
                            data_nascimento=row["data_nascimento"],
                            score=int(row.get("score", 0)),
                            limite_atual=float(row.get("limite_atual", 0)),
                        )
        return None

    async def read_clients(self) -> list[Client]:
        file_path = self._settings.clients_csv_path
        clients: list[Client] = []

        with self._get_lock(file_path):
            if not file_path.exists():
                return clients

            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    clients.append(
                        Client(
                            cpf=row["cpf"],
                            nome=row["nome"],
                            data_nascimento=row["data_nascimento"],
                            score=int(row.get("score", 0)),
                            limite_atual=float(row.get("limite_atual", 0)),
                        )
                    )
        return clients

    async def update_client_score(self, cpf: str, new_score: int) -> bool:
        file_path = self._settings.clients_csv_path
        normalized_cpf = cpf.replace(".", "").replace("-", "")
        updated = False

        with self._get_lock(file_path):
            if not file_path.exists():
                return False

            rows: list[dict[str, Any]] = []
            fieldnames: list[str] = []

            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                for row in reader:
                    row_cpf = row.get("cpf", "").replace(".", "").replace("-", "")
                    if row_cpf == normalized_cpf:
                        row["score"] = str(new_score)
                        updated = True
                    rows.append(row)

            if updated:
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                logger.info(f"Updated score for CPF: {cpf[:3]}*** to {new_score}")

        return updated

    async def append_limit_request(self, request_data: dict[str, Any]) -> None:
        file_path = self._settings.limit_requests_csv_path
        fieldnames = [
            "cpf_cliente",
            "data_hora_solicitacao",
            "limite_atual",
            "novo_limite_solicitado",
            "status_pedido",
        ]

        with self._get_lock(file_path):
            file_exists = file_path.exists()

            with open(file_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(request_data)

        logger.info(
            f"Appended limit request for CPF: {request_data['cpf_cliente'][:3]}***"
        )

    async def read_score_limits(self) -> list[dict[str, Any]]:
        file_path = self._settings.score_limits_csv_path
        limits: list[dict[str, Any]] = []

        with self._get_lock(file_path):
            if not file_path.exists():
                return limits

            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    limits.append(
                        {
                            "score_min": int(row["score_min"]),
                            "score_max": int(row["score_max"]),
                            "limite": float(row["limite"]),
                        }
                    )

        return limits
