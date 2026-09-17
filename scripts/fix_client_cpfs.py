"""Reescreve `src/data/clientes.csv` trocando CPFs inválidos por CPFs sintéticos válidos.

Idempotente: rodar duas vezes não altera nada na segunda. A seed de cada linha é o
índice da linha, então o resultado é reproduzível em qualquer máquina.

Uso:
    python scripts/fix_client_cpfs.py [--check]

`--check` não escreve nada e sai com código 1 se houver CPF inválido (usado no CI).
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.cpf import generate_valid_cpf, is_valid_cpf  # noqa: E402

CLIENTS_CSV = Path(__file__).resolve().parent.parent / "src" / "data" / "clientes.csv"


def _unique_valid_cpf(seed: int, taken: set[str]) -> str:
    """Gera um CPF válido determinístico que ainda não está em uso."""
    attempt = seed
    while True:
        cpf = generate_valid_cpf(attempt)
        if cpf not in taken:
            return cpf
        attempt += 10_000


def fix(path: Path = CLIENTS_CSV, *, check_only: bool = False) -> int:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    taken = {row["cpf"] for row in rows if is_valid_cpf(row["cpf"])}
    changes: list[tuple[str, str, str]] = []

    for index, row in enumerate(rows):
        original = row["cpf"]
        if is_valid_cpf(original):
            continue
        new_cpf = _unique_valid_cpf(index, taken)
        taken.add(new_cpf)
        row["cpf"] = new_cpf
        changes.append((row["nome"], original, new_cpf))

    if check_only:
        for nome, old, new in changes:
            print(f"INVALIDO  {nome}: {old} (sugestao: {new})")
        return 1 if changes else 0

    if not changes:
        print("Nenhuma alteracao: todos os CPFs ja sao validos.")
        return 0

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    for nome, old, new in changes:
        print(f"{nome}: {old} -> {new}")
    print(f"\n{len(changes)} CPF(s) corrigido(s) em {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="apenas verifica, sem escrever; sai com 1 se houver CPF invalido",
    )
    args = parser.parse_args()
    return fix(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
