import re
from typing import Literal, Optional

from src.utils.text_normalizer import normalize_text


NUMBERS_MAP = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
}

MULTIPLIERS = {"mil": 1000, "k": 1000, "milhao": 1_000_000, "milhoes": 1_000_000, "mi": 1_000_000}

EMPLOYMENT_SYNONYMS = [
    ("DESEMPREGADO", ["desempregado", "sem emprego", "sem trabalho", "procurando emprego", "desocupado", "nao trabalho", "estou parado", "parado", "afastado", "sem renda fixa"]),
    ("PUBLICO", ["servidor publico", "funcionario publico", "setor publico", "concursado", "governo", "servidor", "municipal", "federal", "prefeitura", "publico"]),
    ("AUTONOMO", ["autonomo", "por conta propria", "conta propria", "freelancer", "freela", "profissional liberal", "liberal", "independente", "prestador de servico", "pj", "pessoa juridica", "cnpj"]),
    ("MEI", ["mei", "microempreendedor", "micro empreendedor", "empreendedor individual", "pequeno negocio"]),
    ("FORMAL", ["empresa privada", "setor privado", "formal"]),
    ("CLT", ["clt", "carteira assinada", "carteira", "registrado", "empregado", "contratado", "assalariado", "trabalhador formal", "regime clt", "emprego fixo", "funcionario"]),
]

CURRENCY_MAP = {
    "USD": ["usd", "dolar", "dollar", "dolares"],
    "EUR": ["eur", "euro", "euros"],
    "GBP": ["gbp", "libra", "libras", "esterlina", "pound"],
    "JPY": ["jpy", "iene", "yen"],
    "ARS": ["ars", "peso argentino"],
    "CNY": ["cny", "yuan", "renminbi"],
    "CHF": ["chf", "franco suico"],
    "CAD": ["cad", "dolar canadense"],
    "AUD": ["aud", "dolar australiano"],
    "MXN": ["mxn", "peso mexicano"],
}


def extract_monetary_value(text: str) -> Optional[float]:
    if not text:
        return None

    normalized = normalize_text(text)
    normalized = re.sub(r"^(minha renda e|minha renda|ganho|recebo|faco|tenho|eh de|e de|sao|cerca de|aproximadamente|perto de|por volta de|mais ou menos|uns|umas|tipo|algo em torno de|em media|na faixa de|entre|quase|beirando|chegando a|chegando em|por mes|mensal|mensalmente|ao mes|mensais)\s*", "", normalized)
    normalized = re.sub(r"[rR]\$\s*", "", normalized)
    normalized = re.sub(r"reais?", "", normalized)

    match = re.search(r"(\d{1,3})\.(\d{3}),(\d{2})", normalized)
    if match:
        return float(f"{match.group(1)}{match.group(2)}.{match.group(3)}")

    match = re.search(r"(\d{1,3})\.(\d{3})(?!\d)", normalized)
    if match:
        return float(f"{match.group(1)}{match.group(2)}")

    match = re.search(r"(\d+),(\d{1,2})", normalized)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")

    match = re.search(r"(\d+)\s*(?:k|mil)\s*e\s*meio", normalized)
    if match:
        return float(match.group(1)) * 1000 + 500

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|mil|milhao|milhoes|mi)", normalized)
    if match:
        value = float(match.group(1).replace(",", "."))
        return value * MULTIPLIERS.get(match.group(2).lower(), 1)

    for word, number in NUMBERS_MAP.items():
        for mult_word, mult_value in MULTIPLIERS.items():
            if re.search(rf"\b{word}\s*{mult_word}\b", normalized):
                return float(number * mult_value)

    match = re.search(r"(\d+(?:[.,]\d+)?)", normalized)
    if match:
        return float(match.group(1).replace(",", "."))

    for word, number in NUMBERS_MAP.items():
        if word in normalized:
            return float(number)

    return None


def extract_integer(text: str) -> Optional[int]:
    if not text:
        return None

    normalized = normalize_text(text)

    for p in ["nenhum", "nenhuma", "zero", "nao tenho", "sem", "nao possuo", "nada", "ninguem"]:
        if p in normalized:
            return 0

    match = re.search(r"(\d+)", normalized)
    if match:
        return int(match.group(1))

    for word, number in NUMBERS_MAP.items():
        if word in normalized:
            return number

    return None


def extract_employment_type(text: str) -> Optional[Literal["CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"]]:
    if not text:
        return None

    normalized = normalize_text(text)

    for emp_type, synonyms in EMPLOYMENT_SYNONYMS:
        for synonym in synonyms:
            if synonym in normalized:
                return emp_type

    return None


def extract_currency_code(text: str) -> Optional[str]:
    if not text:
        return None

    normalized = normalize_text(text)
    upper_text = text.strip().upper()
    known_codes = set(CURRENCY_MAP.keys())

    for code, synonyms in CURRENCY_MAP.items():
        for synonym in synonyms:
            if synonym in normalized:
                return code

    match = re.search(r"\b([A-Z]{3})\b", upper_text)
    if match and match.group(1) in known_codes:
        return match.group(1)

    return None
