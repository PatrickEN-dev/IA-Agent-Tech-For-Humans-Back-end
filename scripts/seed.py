"""Carrega o banco a partir dos CSVs.

Uso:
    python scripts/seed.py            # idempotente, preserva contas de visitantes
    python scripts/seed.py --reset    # derruba tudo e recria
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.db.seed import seed_database  # noqa: E402
from src.db.session import dispose_engine  # noqa: E402
from src.utils.logging_config import setup_logging  # noqa: E402


async def run(reset: bool) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    print(f"Banco: {settings.database_url}")
    try:
        result = await seed_database(reset=reset)
    finally:
        await dispose_engine()
    print(f"Clientes inseridos: {result['clients']}")
    print(f"Faixas de score inseridas: {result['score_limits']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="derruba as tabelas antes")
    args = parser.parse_args()
    asyncio.run(run(args.reset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
