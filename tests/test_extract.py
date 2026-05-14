"""Unit tests for `src.utils.extract` — pure parsers, no I/O."""
from __future__ import annotations

import pytest

from src.utils.extract import (
    classify_intent_rule_based,
    extract_birthdate,
    extract_cpf,
    extract_currency,
    extract_employment,
    extract_integer,
    extract_money,
    normalize,
    parse_boolean,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12345678909", "12345678909"),
        ("123.456.789-09", "12345678909"),
        ("meu CPF é 123.456.789-09 ok?", "12345678909"),
        ("123", None),
        ("", None),
    ],
)
def test_extract_cpf(text: str, expected: str | None) -> None:
    assert extract_cpf(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("15/05/1990", (15, 5, 1990)),
        ("15-05-1990", (15, 5, 1990)),
        ("15 de maio de 1990", (15, 5, 1990)),
        ("15 maio 1990", (15, 5, 1990)),
        ("15/05/90", (15, 5, 1990)),
        ("15/05/25", (15, 5, 2025)),
        ("não sei", None),
    ],
)
def test_extract_birthdate(text: str, expected: tuple[int, int, int] | None) -> None:
    assert extract_birthdate(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5000", 5000.0),
        ("R$ 5.000,00", 5000.0),
        ("5k", 5000.0),
        ("5 mil", 5000.0),
        ("cinco mil", 5000.0),
        ("5 mil e meio", 5500.0),
        ("ganho uns 8 mil por mês", 8000.0),
        ("1 milhao", 1_000_000.0),
        ("dois milhoes", 2_000_000.0),
        ("nada", None),
    ],
)
def test_extract_money(text: str, expected: float | None) -> None:
    assert extract_money(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", 0),
        ("2", 2),
        ("nenhum", 0),
        ("dois", 2),
        ("zero", 0),
        ("tenho 3 filhos", 3),
    ],
)
def test_extract_integer(text: str, expected: int | None) -> None:
    assert extract_integer(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CLT", "CLT"),
        ("trabalho de carteira assinada", "CLT"),
        ("sou MEI", "MEI"),
        ("servidor público", "PUBLICO"),
        ("autonomo", "AUTONOMO"),
        ("estou desempregado", "DESEMPREGADO"),
    ],
)
def test_extract_employment(text: str, expected: str) -> None:
    assert extract_employment(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("USD", "USD"),
        ("dólar", "USD"),
        ("euro", "EUR"),
        ("libra esterlina", "GBP"),
        ("BRL", "BRL"),
        ("real", "BRL"),
    ],
)
def test_extract_currency(text: str, expected: str) -> None:
    assert extract_currency(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("sim", True),
        ("não", False),
        ("não tenho dívidas", False),
        ("tenho sim", True),
        ("acho que não sei", None),
        ("nenhuma dívida", False),
        ("tudo quitado", False),
    ],
)
def test_parse_boolean(text: str, expected: bool | None) -> None:
    assert parse_boolean(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("qual meu limite", "credit_limit"),
        ("quero aumento de limite", "request_increase"),
        ("solicitar aumento", "request_increase"),
        ("cotação do dólar", "exchange_rate"),
        ("converter euro", "exchange_rate"),
        ("quero atualizar meu perfil", "interview"),
        ("entrevista financeira", "interview"),
        ("tchau", "exit"),
        ("ola", "unknown"),
        ("blablabla", "unknown"),
    ],
)
def test_classify_intent_rule_based(text: str, expected: str) -> None:
    assert classify_intent_rule_based(text) == expected


def test_normalize_strips_accents_and_lowercase() -> None:
    assert normalize("Olá, MUNDO!") == "ola, mundo!"
