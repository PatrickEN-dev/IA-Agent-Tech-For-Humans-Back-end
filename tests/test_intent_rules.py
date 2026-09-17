"""Classificação de intenção por regras e correções de fronteira de palavra."""

import pytest

from src.services.llm_service import LLMService
from src.utils.formatting import format_brl
from src.utils.text_normalizer import contains_word, parse_boolean_response
from src.utils.value_extractor import (
    extract_currency_codes,
    extract_employment_type,
    extract_integer,
    extract_monetary_value,
)

service = LLMService()


@pytest.mark.parametrize(
    "message,expected",
    [
        ("qual meu limite?", "credit_limit"),
        ("Quero ver meu limite de crédito", "credit_limit"),
        ("quanto tenho disponível", "credit_limit"),
        ("quero aumentar meu limite", "request_increase"),
        ("quero aumento de limite", "request_increase"),
        ("cotação do dólar", "exchange_rate"),
        ("quanto tá o euro hoje", "exchange_rate"),
        ("USD", "exchange_rate"),
        ("quero atualizar meu perfil", "interview"),
        ("quero fazer a entrevista", "interview"),
        ("quero melhorar meu score", "interview"),
        ("tchau", "goodbye"),
        ("era só isso, obrigado", "goodbye"),
        ("pode encerrar", "goodbye"),
        ("sim", "confirm"),
        ("pode ser", "confirm"),
        ("vamos lá!", "confirm"),
        ("não", "reject"),
        ("no", "reject"),
        ("agora não, obrigado", "reject"),
        ("cancelar", "reject"),
        ("oi", "greeting"),
        ("Bom dia!", "greeting"),
        ("quem descobriu o brasil?", None),
        ("15000", None),
        ("   ", None),
    ],
)
def test_rule_based_intent(message: str, expected: str | None) -> None:
    assert service.classify_with_rules(message) == expected


def test_banking_intent_beats_confirm_and_reject() -> None:
    assert service.classify_with_rules("sim, quero a entrevista") == "interview"
    assert service.classify_with_rules("não, quero ver o câmbio") == "exchange_rate"


def test_ambiguous_banking_intents_return_none() -> None:
    # "perfil" (interview) e "câmbio" (exchange) empatam: deixa o LLM decidir
    assert service.classify_with_rules("perfil ou câmbio?") is None


@pytest.mark.asyncio
async def test_classify_intent_uses_rules_when_llm_disabled() -> None:
    assert await service.classify_intent("meu limite") == "credit_limit"
    assert await service.classify_intent("qualquer coisa aleatória") is None
    assert await service.classify_intent("") is None


class TestWordBoundaryFixes:
    def test_contains_word_respects_boundaries(self) -> None:
        assert contains_word("bom dia", "ia") is False
        assert contains_word("tchau", "ha") is False
        assert contains_word("meus limites", "limite") is True

    def test_article_um_is_not_a_value(self) -> None:
        assert extract_monetary_value("quero aumentar meu limite") is None
        assert extract_monetary_value("quero um aumento") is None
        assert extract_monetary_value("dez mil") == 10000.0
        assert extract_monetary_value("um mil") == 1000.0

    def test_tchau_is_not_affirmative(self) -> None:
        assert parse_boolean_response("tchau") is None
        assert parse_boolean_response("olá") is None

    def test_negation_wins_over_affirmative(self) -> None:
        assert parse_boolean_response("não tenho dívidas") is False
        assert parse_boolean_response("sim, tenho algumas") is True

    def test_sem_only_matches_whole_word(self) -> None:
        assert extract_integer("toda semana são 2") == 2
        assert extract_integer("sem dependentes") == 0
        assert extract_integer("tenho um filho") == 1

    def test_mei_is_not_matched_inside_meio(self) -> None:
        assert extract_employment_type("trabalho meio período") is None
        assert extract_employment_type("tenho um MEI") == "MEI"

    def test_currency_pairs_keep_order(self) -> None:
        assert extract_currency_codes("dólar para real") == ["USD", "BRL"]
        assert extract_currency_codes("quanto tá o euro em reais") == ["EUR", "BRL"]
        assert extract_currency_codes("dólar canadense") == ["CAD"]
        assert extract_currency_codes("cotação") == []


def test_format_brl() -> None:
    assert format_brl(15000) == "R$ 15.000,00"
    assert format_brl(1234567.891) == "R$ 1.234.567,89"
    assert format_brl(0.5) == "R$ 0,50"
