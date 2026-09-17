import csv
from pathlib import Path

import pytest

from src.utils.cpf import (
    format_cpf,
    generate_valid_cpf,
    is_valid_cpf,
    mask_cpf,
    strip_cpf,
)

PRODUCTION_CLIENTS_CSV = Path("src/data/clientes.csv")


@pytest.mark.parametrize(
    "cpf",
    [
        "98765432100",
        "12345678909",
        "529.982.247-25",
        "52998224725",
    ],
)
def test_valid_cpfs(cpf: str) -> None:
    assert is_valid_cpf(cpf) is True


@pytest.mark.parametrize(
    "cpf",
    [
        "12345678901",  # digito verificador errado
        "11122233344",  # digito verificador errado
        "99999999999",  # digitos todos iguais
        "00000000000",
        "1234567890",  # 10 digitos
        "123456789012",  # 12 digitos
        "",
        "abcdefghijk",
    ],
)
def test_invalid_cpfs(cpf: str) -> None:
    assert is_valid_cpf(cpf) is False


def test_strip_cpf_removes_punctuation() -> None:
    assert strip_cpf("529.982.247-25") == "52998224725"


def test_format_cpf_applies_mask() -> None:
    assert format_cpf("52998224725") == "529.982.247-25"


def test_format_cpf_leaves_short_input_untouched() -> None:
    assert format_cpf("123") == "123"


def test_mask_cpf_hides_middle_digits() -> None:
    assert mask_cpf("52998224725") == "529.***.***-25"
    assert mask_cpf("123") == "***"


def test_generated_cpfs_are_valid_and_deterministic() -> None:
    for seed in range(200):
        cpf = generate_valid_cpf(seed)
        assert len(cpf) == 11
        assert is_valid_cpf(cpf), f"seed {seed} gerou CPF invalido: {cpf}"
        assert cpf == generate_valid_cpf(seed), "geracao deve ser deterministica"


def test_generated_cpfs_are_mostly_distinct() -> None:
    generated = {generate_valid_cpf(seed) for seed in range(200)}
    assert len(generated) == 200


@pytest.mark.skipif(
    not PRODUCTION_CLIENTS_CSV.exists(), reason="CSV de producao ausente"
)
def test_all_client_cpfs_are_valid() -> None:
    """A base que a demo usa não pode conter CPF que o próprio app rejeitaria."""
    with open(PRODUCTION_CLIENTS_CSV, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows, "clientes.csv esta vazio"
    invalid = [row["cpf"] for row in rows if not is_valid_cpf(row["cpf"])]
    assert not invalid, f"CPFs invalidos na base: {invalid}"


@pytest.mark.skipif(
    not PRODUCTION_CLIENTS_CSV.exists(), reason="CSV de producao ausente"
)
def test_client_cpfs_are_unique() -> None:
    with open(PRODUCTION_CLIENTS_CSV, encoding="utf-8", newline="") as f:
        cpfs = [row["cpf"] for row in csv.DictReader(f)]
    assert len(cpfs) == len(set(cpfs))
