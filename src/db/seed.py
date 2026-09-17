"""Popula o banco a partir dos CSVs do desafio.

Os CSVs deixam de ser o banco de dados e passam a ser o *fixture* de dados iniciais —
é a mesma relação que um `seeds/` tem com um Postgres de produção.

`limite_atual` do CSV é ignorado de propósito quando for incoerente com a tabela de
score: a base original trazia Maria com score 315 e limite R$ 15.000, o que a própria
regra de negócio recusaria. O seed grava o menor entre o valor do CSV e o teto da faixa.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import select

from src.config import get_settings
from src.db.models import ClientModel, ScoreLimitModel
from src.db.session import create_all, drop_all, session_scope
from src.utils.cpf import is_valid_cpf, strip_cpf

logger = logging.getLogger(__name__)

# Personas escolhidas por faixa de score, não por nome: cobrem os quatro desfechos
# que a demo precisa mostrar (negado, limítrofe, aprovado, premium).
PERSONA_SCORE_TARGETS = [315, 550, 720, 920]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        logger.warning("CSV de seed ausente: %s", path)
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _limit_for_score(score: int, ranges: list[tuple[int, int, float]]) -> float:
    for score_min, score_max, limite in ranges:
        if score_min <= score <= score_max:
            return limite
    return 500.0


def _pick_persona_cpfs(clients: list[dict[str, str]], count: int) -> set[str]:
    """Escolhe as personas cujo score é o mais próximo de cada faixa alvo."""
    chosen: set[str] = set()
    for target in PERSONA_SCORE_TARGETS[:count]:
        candidates = [c for c in clients if c["cpf"] not in chosen]
        if not candidates:
            break
        best = min(candidates, key=lambda c: abs(int(c["score"]) - target))
        chosen.add(best["cpf"])
    return chosen


async def seed_database(*, reset: bool = False) -> dict[str, int]:
    """Cria o schema e carrega os CSVs. Com `reset`, derruba as tabelas antes.

    Sem `reset`, é idempotente: clientes já existentes não são sobrescritos, e
    contas criadas por visitantes sobrevivem a um restart.
    """
    settings = get_settings()

    if reset:
        await drop_all()
    await create_all()

    score_rows = _read_csv(settings.score_limits_csv_path)
    client_rows = _read_csv(settings.clients_csv_path)

    ranges = [
        (int(r["score_min"]), int(r["score_max"]), float(r["limite"])) for r in score_rows
    ]
    persona_cpfs = _pick_persona_cpfs(client_rows, settings.demo_persona_count)

    inserted_limits = 0
    inserted_clients = 0

    async with session_scope() as session:
        existing_ranges = {
            (row.score_min, row.score_max)
            for row in (await session.scalars(select(ScoreLimitModel))).all()
        }
        for score_min, score_max, limite in ranges:
            if (score_min, score_max) in existing_ranges:
                continue
            session.add(
                ScoreLimitModel(score_min=score_min, score_max=score_max, limite=limite)
            )
            inserted_limits += 1

        for row in client_rows:
            cpf = strip_cpf(row["cpf"])
            if not is_valid_cpf(cpf):
                # `scripts/fix_client_cpfs.py` existe justamente para isso não acontecer.
                logger.error("Seed ignorou CPF invalido para %s", row.get("nome"))
                continue
            if await session.get(ClientModel, cpf):
                continue

            score = int(row.get("score", 0))
            ceiling = _limit_for_score(score, ranges)
            csv_limit = float(row.get("limite_atual", 0) or 0)
            session.add(
                ClientModel(
                    cpf=cpf,
                    nome=row["nome"],
                    data_nascimento=row["data_nascimento"],
                    score=score,
                    limite_atual=min(csv_limit, ceiling) if csv_limit else ceiling,
                    origem="seed",
                    is_demo_persona=row["cpf"] in persona_cpfs,
                )
            )
            inserted_clients += 1

    logger.info(
        "Seed concluido: %s cliente(s), %s faixa(s) de score",
        inserted_clients,
        inserted_limits,
    )
    return {"clients": inserted_clients, "score_limits": inserted_limits}
