import re
import unicodedata
from typing import Optional


def remove_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    text = remove_accents(text.lower().strip())
    text = re.sub(r"\s+", " ", text)
    return text


def extract_cpf_from_text(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 11:
        return digits[:11]
    return None


def parse_boolean_response(text: str) -> Optional[bool]:
    normalized = normalize_text(text)

    uncertainty = ["nao sei", "nao lembro", "nao tenho certeza", "talvez", "acho que", "nao me lembro"]
    for p in uncertainty:
        if p in normalized:
            return None

    negative = [
        "nao", "falso", "false", "negativo", "nunca", "nem pensar", "de jeito nenhum",
        "nao tenho", "nenhum", "nenhuma", "zero", "nada", "sem divida", "sem dividas",
        "estou limpo", "limpo", "tudo pago", "quitado", "nao possuo", "nao ha",
    ]

    affirmative = [
        "sim", "yes", "verdade", "verdadeiro", "true", "com certeza", "claro",
        "isso", "exato", "exatamente", "correto", "tenho", "possuo", "ha",
        "infelizmente sim", "sim tenho", "tem sim", "tenho sim", "tenho divida",
    ]

    if normalized == "s":
        return True

    for p in negative:
        if p in normalized:
            if p.startswith("nao") or p in ["sem divida", "sem dividas", "estou limpo", "limpo", "tudo pago", "quitado", "nenhum", "nenhuma", "zero", "nada", "nunca", "falso", "false", "negativo"]:
                return False

    for p in affirmative:
        if p in normalized:
            has_neg = any(n in normalized for n in ["nao", "sem", "nenhum", "nunca"])
            if not has_neg:
                return True

    if "nao" in normalized or "sem" in normalized:
        return False
    if "sim" in normalized or "tenho" in normalized:
        return True

    return None


def parse_date_from_text(text: str) -> Optional[tuple[int, int, int]]:
    text = text.strip()

    months_map = {
        "janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "marco": 3, "mar": 3,
        "abril": 4, "abr": 4, "maio": 5, "mai": 5, "junho": 6, "jun": 6,
        "julho": 7, "jul": 7, "agosto": 8, "ago": 8, "setembro": 9, "set": 9,
        "outubro": 10, "out": 10, "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12,
    }

    match = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", text)
    if match:
        day, month, year = map(int, match.groups())
        if year < 100:
            year = 1900 + year if year > 30 else 2000 + year
        return (day, month, year)

    normalized = normalize_text(text)
    for month_name, month_num in months_map.items():
        pattern = rf"(\d{{1,2}})\s*(?:de\s*)?{month_name}\s*(?:de\s*)?(\d{{2,4}})"
        match = re.search(pattern, normalized)
        if match:
            day = int(match.group(1))
            year = int(match.group(2))
            if year < 100:
                year = 1900 + year if year > 30 else 2000 + year
            return (day, month_num, year)

    return None


CLARIFICATION_MESSAGES = {
    "cpf": "Desculpe, não consegui identificar seu CPF. Por favor, digite os 11 números.",
    "birthdate": "Não consegui entender a data. Informe no formato dia/mês/ano, ex: 15/05/1990",
    "income": "Não consegui identificar o valor. Informe sua renda, ex: 5000, 5k, ou cinco mil.",
    "expenses": "Não entendi o valor das despesas. Qual o valor aproximado, ex: 2000 ou 2k?",
    "employment_type": "Qual seu tipo de trabalho? CLT, autônomo, MEI, servidor público ou desempregado?",
    "dependents": "Quantas pessoas dependem financeiramente de você? Se nenhuma, diga 'zero'.",
    "debts": "Você possui alguma dívida em aberto? Responda sim ou não.",
    "currency": "Informe o código da moeda: USD, EUR, GBP, JPY ou ARS.",
    "limit_value": "Qual valor de limite deseja? Ex: 10000, 10k, ou dez mil.",
}


def get_clarification_message(field_type: str, context: str = "") -> str:
    msg = CLARIFICATION_MESSAGES.get(field_type, "Desculpe, não entendi. Poderia reformular?")
    return f"{msg}\n\n{context}" if context else msg
