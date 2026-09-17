import re
from typing import Literal, Optional

from src.utils.text_normalizer import contains_any, normalize_text


NUMBERS_MAP = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
}

MULTIPLIERS = {"mil": 1000, "k": 1000, "milhao": 1_000_000, "milhoes": 1_000_000, "mi": 1_000_000}

# Artigos em portugues; sozinhos geram falso positivo como valor monetario ("um" em "quero um aumento")
AMBIGUOUS_NUMBER_WORDS = {"um", "uma"}

EmploymentType = Literal["CLT", "FORMAL", "PUBLICO", "AUTONOMO", "MEI", "DESEMPREGADO"]

EMPLOYMENT_SYNONYMS: list[tuple[EmploymentType, list[str]]] = [
    ("DESEMPREGADO", ["desempregado", "desempregada", "sem emprego", "sem trabalho", "procurando emprego", "desocupado", "nao trabalho", "estou parado", "parado", "parada", "afastado", "afastada", "sem renda fixa"]),
    ("PUBLICO", ["servidor publico", "servidora publica", "funcionario publico", "funcionaria publica", "setor publico", "concursado", "concursada", "governo", "servidor", "servidora", "municipal", "federal", "estadual", "prefeitura", "publico"]),
    ("AUTONOMO", ["autonomo", "autonoma", "por conta propria", "conta propria", "freelancer", "freela", "profissional liberal", "liberal", "independente", "prestador de servico", "pj", "pessoa juridica", "cnpj"]),
    ("MEI", ["mei", "microempreendedor", "microempreendedora", "micro empreendedor", "empreendedor individual", "pequeno negocio"]),
    ("FORMAL", ["empresa privada", "setor privado", "formal"]),
    ("CLT", ["clt", "carteira assinada", "carteira", "registrado", "registrada", "empregado", "empregada", "contratado", "contratada", "assalariado", "assalariada", "trabalhador formal", "regime clt", "emprego fixo", "funcionario", "funcionaria"]),
]

CURRENCY_MAP: dict[str, list[str]] = {
    "BRL": ["brl", "real", "reais", "real brasileiro"],
    "USD": ["usd", "dolar", "dollar", "dolares", "dolar americano"],
    "EUR": ["eur", "euro", "euros"],
    "GBP": ["gbp", "libra", "libras", "esterlina", "pound"],
    "JPY": ["jpy", "iene", "ienes", "yen"],
    "ARS": ["ars", "peso argentino", "pesos argentinos"],
    "CNY": ["cny", "yuan", "renminbi"],
    "CHF": ["chf", "franco suico"],
    "CAD": ["cad", "dolar canadense"],
    "AUD": ["aud", "dolar australiano"],
    "MXN": ["mxn", "peso mexicano"],
}

LEADING_FILLER = (
    r"^(minha renda e|minha renda|ganho|recebo|faco|tenho|eh de|e de|sao|cerca de|"
    r"aproximadamente|perto de|por volta de|mais ou menos|uns|umas|tipo|algo em torno de|"
    r"em media|na faixa de|entre|quase|beirando|chegando a|chegando em|por mes|mensal|"
    r"mensalmente|ao mes|mensais)\s*"
)


def _find_number_word(normalized: str, *, allow_ambiguous: bool) -> Optional[int]:
    for word, number in NUMBERS_MAP.items():
        if not allow_ambiguous and word in AMBIGUOUS_NUMBER_WORDS:
            continue
        if re.search(rf"(?<!\w){word}(?!\w)", normalized):
            return number
    return None


def extract_monetary_value(text: str) -> Optional[float]:
    if not text:
        return None

    normalized = normalize_text(text)
    normalized = re.sub(LEADING_FILLER, "", normalized)
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

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|mil|milhao|milhoes|mi)(?!\w)", normalized)
    if match:
        value = float(match.group(1).replace(",", "."))
        return value * MULTIPLIERS.get(match.group(2).lower(), 1)

    for word, number in NUMBERS_MAP.items():
        for mult_word, mult_value in MULTIPLIERS.items():
            if re.search(rf"(?<!\w){word}\s*{mult_word}(?!\w)", normalized):
                return float(number * mult_value)

    match = re.search(r"(\d+(?:[.,]\d+)?)", normalized)
    if match:
        return float(match.group(1).replace(",", "."))

    number = _find_number_word(normalized, allow_ambiguous=False)
    if number is not None:
        return float(number)

    return None


ZERO_PATTERNS = ["nenhum", "nenhuma", "zero", "nao tenho", "sem", "nao possuo", "nada", "ninguem"]


def extract_integer(text: str) -> Optional[int]:
    if not text:
        return None

    normalized = normalize_text(text)

    if contains_any(normalized, ZERO_PATTERNS):
        return 0

    match = re.search(r"(\d+)", normalized)
    if match:
        return int(match.group(1))

    return _find_number_word(normalized, allow_ambiguous=True)


def extract_employment_type(text: str) -> Optional[EmploymentType]:
    if not text:
        return None

    normalized = normalize_text(text)

    for emp_type, synonyms in EMPLOYMENT_SYNONYMS:
        if contains_any(normalized, synonyms):
            return emp_type

    return None


def extract_currency_codes(text: str) -> list[str]:
    """Retorna os codigos de moeda citados no texto, na ordem em que aparecem.

    "dolar para real" -> ["USD", "BRL"]; "cotacao do euro" -> ["EUR"].
    """
    if not text:
        return []

    normalized = normalize_text(text)
    matches: list[tuple[int, int, str]] = []

    for code, synonyms in CURRENCY_MAP.items():
        for synonym in synonyms:
            for m in re.finditer(rf"(?<!\w){re.escape(synonym)}(?!\w)", normalized):
                matches.append((m.start(), m.end(), code))

    # Ordena por posicao; em empate, o sinonimo mais longo vence ("dolar canadense" > "dolar")
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    result: list[str] = []
    last_end = -1
    for start, end, code in matches:
        if start < last_end:
            continue
        last_end = end
        if code not in result:
            result.append(code)

    return result


def extract_currency_code(text: str) -> Optional[str]:
    codes = extract_currency_codes(text)
    return codes[0] if codes else None
