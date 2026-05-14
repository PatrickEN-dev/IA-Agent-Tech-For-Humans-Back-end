"""Text parsing helpers for free-form Portuguese user input.

Single-file module that consolidates the previous text_normalizer + value_extractor.
All extractors are pure functions: input goes in, value (or None) comes out.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

from src.models.schemas import EmploymentType

_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14,
    "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
    "dezoito": 18, "dezenove": 19, "vinte": 20,
}

_MULTIPLIERS: dict[str, int] = {
    "mil": 1000, "k": 1000,
    "milhao": 1_000_000, "milhoes": 1_000_000, "mi": 1_000_000,
}

_EMPLOYMENT_SYNONYMS: list[tuple[EmploymentType, tuple[str, ...]]] = [
    ("DESEMPREGADO", (
        "desempregado", "sem emprego", "sem trabalho", "procurando emprego",
        "desocupado", "nao trabalho", "estou parado", "afastado", "sem renda",
    )),
    ("PUBLICO", (
        "servidor publico", "funcionario publico", "setor publico", "concursado",
        "governo", "servidor", "municipal", "federal", "prefeitura", "publico",
    )),
    ("AUTONOMO", (
        "autonomo", "por conta propria", "conta propria", "freelancer", "freela",
        "profissional liberal", "liberal", "independente", "prestador de servico",
        "pj", "pessoa juridica", "cnpj",
    )),
    ("MEI", (
        "mei", "microempreendedor", "micro empreendedor",
        "empreendedor individual", "pequeno negocio",
    )),
    ("FORMAL", ("empresa privada", "setor privado", "formal")),
    ("CLT", (
        "clt", "carteira assinada", "carteira", "registrado", "empregado",
        "contratado", "assalariado", "trabalhador formal", "regime clt",
        "emprego fixo", "funcionario",
    )),
]

_CURRENCY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "BRL": ("brl", "real", "reais", "brasileiro"),
    "USD": ("usd", "dolar", "dollar", "dolares"),
    "EUR": ("eur", "euro", "euros"),
    "GBP": ("gbp", "libra", "libras", "esterlina", "pound"),
    "JPY": ("jpy", "iene", "yen"),
    "ARS": ("ars", "peso argentino"),
    "CNY": ("cny", "yuan", "renminbi"),
    "CHF": ("chf", "franco suico"),
    "CAD": ("cad", "dolar canadense"),
    "AUD": ("aud", "dolar australiano"),
    "MXN": ("mxn", "peso mexicano"),
}

_MONTHS: dict[str, int] = {
    "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4, "maio": 5, "mai": 5, "junho": 6, "jun": 6,
    "julho": 7, "jul": 7, "agosto": 8, "ago": 8, "setembro": 9, "set": 9,
    "outubro": 10, "out": 10, "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12,
}

_AFFIRMATIVE = ("sim", "yes", "verdade", "verdadeiro", "true", "com certeza",
                "claro", "isso", "exato", "correto", "tenho", "possuo")
_NEGATIVE = ("nao", "no", "falso", "false", "negativo", "nunca", "nenhum",
             "nenhuma", "zero", "nada", "sem", "quitado", "limpo")
_UNCERTAIN = ("nao sei", "nao lembro", "nao tenho certeza", "talvez", "acho que")
_ZERO_INDICATORS = ("nenhum", "nenhuma", "zero", "nao tenho", "sem",
                    "nao possuo", "nada", "ninguem")


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower().strip())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents)


def extract_cpf(text: str) -> str | None:
    """Return the first 11 digits found in the text, or None."""
    digits = re.sub(r"\D", "", text or "")
    return digits[:11] if len(digits) >= 11 else None


def normalize_cpf(cpf: str) -> str:
    """Strip non-digits — the canonical representation used everywhere."""
    return re.sub(r"\D", "", cpf or "")


def is_valid_cpf(cpf: str) -> bool:
    """Run the Brazilian CPF checksum.

    Reject 11-equal-digits sequences (000..., 111..., ..., 999...) which pass
    the math but are forbidden by Receita Federal.
    """
    digits = normalize_cpf(cpf)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    nums = [int(d) for d in digits]
    for k in (9, 10):
        check = sum(nums[i] * (k + 1 - i) for i in range(k)) * 10 % 11 % 10
        if check != nums[k]:
            return False
    return True


def extract_birthdate(text: str) -> tuple[int, int, int] | None:
    """Parse a date in formats DD/MM/AAAA, DD-MM-AAAA or '15 de maio de 1990'.

    Returns (day, month, year) — caller validates ranges.
    """
    if not text:
        return None

    numeric = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", text)
    if numeric:
        day, month, year = (int(g) for g in numeric.groups())
        return (day, month, _normalize_year(year))

    normalized = normalize(text)
    for month_name, month_num in _MONTHS.items():
        match = re.search(
            rf"(\d{{1,2}})\s*(?:de\s*)?{month_name}\s*(?:de\s*)?(\d{{2,4}})",
            normalized,
        )
        if match:
            day = int(match.group(1))
            year = _normalize_year(int(match.group(2)))
            return (day, month_num, year)
    return None


def _normalize_year(year: int) -> int:
    if year >= 100:
        return year
    return 1900 + year if year > 30 else 2000 + year


def extract_money(text: str) -> float | None:
    """Extract a monetary value from natural language.

    Handles "5000", "R$ 5.000,00", "5k", "5 mil", "cinco mil", "5 mil e meio".
    """
    if not text:
        return None

    normalized = normalize(text)
    normalized = re.sub(
        r"^(minha renda e|minha renda|ganho|recebo|faco|tenho|eh de|e de|sao|"
        r"cerca de|aproximadamente|perto de|por volta de|mais ou menos|uns|umas|"
        r"tipo|algo em torno de|em media|na faixa de|entre|quase|beirando|"
        r"chegando a|chegando em|por mes|mensal|mensalmente|ao mes|mensais)\s*",
        "",
        normalized,
    )
    normalized = re.sub(r"r\$\s*", "", normalized)
    normalized = re.sub(r"reais?", "", normalized)

    if m := re.search(r"(\d{1,3})\.(\d{3}),(\d{2})", normalized):
        return float(f"{m.group(1)}{m.group(2)}.{m.group(3)}")
    if m := re.search(r"(\d{1,3})\.(\d{3})(?!\d)", normalized):
        return float(f"{m.group(1)}{m.group(2)}")
    if m := re.search(r"(\d+),(\d{1,2})", normalized):
        return float(f"{m.group(1)}.{m.group(2)}")
    if m := re.search(r"(\d+)\s*(?:k|mil)\s*e\s*meio", normalized):
        return float(m.group(1)) * 1000 + 500
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(milhoes|milhao|mil|mi|k)\b", normalized):
        return float(m.group(1).replace(",", ".")) * _MULTIPLIERS[m.group(2)]

    for word, number in _WORD_NUMBERS.items():
        for mult_word, mult_value in _MULTIPLIERS.items():
            if re.search(rf"\b{word}\s*{mult_word}\b", normalized):
                return float(number * mult_value)

    if m := re.search(r"(\d+(?:[.,]\d+)?)", normalized):
        return float(m.group(1).replace(",", "."))

    for word, number in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", normalized):
            return float(number)
    return None


def extract_integer(text: str) -> int | None:
    """Extract a small non-negative integer (e.g. number of dependents)."""
    if not text:
        return None

    normalized = normalize(text)
    if any(token in normalized for token in _ZERO_INDICATORS):
        return 0
    if m := re.search(r"(\d+)", normalized):
        return int(m.group(1))
    for word, number in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", normalized):
            return number
    return None


def extract_employment(text: str) -> EmploymentType | None:
    normalized = normalize(text)
    for emp_type, synonyms in _EMPLOYMENT_SYNONYMS:
        if any(syn in normalized for syn in synonyms):
            return emp_type
    return None


def extract_currency(text: str) -> str | None:
    """Resolve a currency code from text (handles synonyms in pt-br)."""
    if not text:
        return None

    normalized = normalize(text)
    for code, synonyms in _CURRENCY_SYNONYMS.items():
        if any(syn in normalized for syn in synonyms):
            return code

    if m := re.search(r"\b([A-Z]{3})\b", text.strip().upper()):
        if m.group(1) in _CURRENCY_SYNONYMS:
            return m.group(1)
    return None


def parse_boolean(text: str) -> bool | None:
    """Yes/no parser. Returns None when the answer is unclear."""
    normalized = normalize(text)
    if any(p in normalized for p in _UNCERTAIN):
        return None
    if normalized == "s":
        return True
    if normalized == "n":
        return False

    has_negative = any(re.search(rf"\b{re.escape(n)}\b", normalized) for n in _NEGATIVE)
    has_affirmative = any(re.search(rf"\b{re.escape(a)}\b", normalized) for a in _AFFIRMATIVE)

    # Negation always wins ("não tenho dívidas" is no, not yes).
    if has_negative:
        return False
    if has_affirmative:
        return True
    return None


Intent = Literal["credit_limit", "request_increase", "exchange_rate",
                 "interview", "exit", "unknown"]


_INTENT_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    "request_increase": (
        "aumento", "aumentar", "aumenta", "subir limite", "elevar limite",
        "mais limite", "novo limite", "pedir aumento", "solicitar aumento",
        "quero mais", "preciso de mais",
    ),
    "credit_limit": (
        "limite", "credito", "saldo disponivel", "quanto tenho", "meu limite",
        "ver limite", "consultar limite", "disponivel",
    ),
    "exchange_rate": (
        "cambio", "cotacao", "dolar", "euro", "moeda", "converter",
        "conversao", "libra", "iene", "peso",
    ),
    "interview": (
        "entrevista", "questionario", "atualizar perfil", "atualizar dados",
        "atualizar cadastro", "perfil financeiro", "melhorar score",
        "refazer score", "atualizar score",
    ),
    "exit": (
        "tchau", "sair", "encerrar", "bye", "adeus", "ate logo", "ate mais",
    ),
}


_FILLER_PATTERN = re.compile(
    r"\b(meu|minha|meus|minhas|um|uma|o|a|os|as|de|do|da|dos|das|para|pra|por|"
    r"que|qual|quais|quero|gostaria|preciso|posso|tem|tens|favor|me)\b"
)


def classify_intent_rule_based(text: str) -> Intent:
    """Heuristic intent classifier — used as fallback when the LLM is offline.

    Order matters: 'request_increase' is checked before 'credit_limit' because
    'aumento de limite' contains 'limite'.
    Filler words ('meu', 'minha', 'quero', ...) are stripped so phrases like
    'atualizar meu perfil' match the 'atualizar perfil' keyword.
    """
    cleaned = _FILLER_PATTERN.sub(" ", normalize(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for intent in ("request_increase", "exchange_rate", "interview", "exit", "credit_limit"):
        if any(kw in cleaned for kw in _INTENT_KEYWORDS[intent]):  # type: ignore[index]
            return intent  # type: ignore[return-value]
    return "unknown"
