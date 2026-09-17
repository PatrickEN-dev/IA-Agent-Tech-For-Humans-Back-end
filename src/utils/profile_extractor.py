"""Extração de vários campos do perfil financeiro a partir de uma frase só.

"Ganho 8 mil, sou CLT, gasto 3 mil, dois filhos, sem dívidas" contém as cinco respostas
que o fluxo pergunta uma a uma. Perguntar de novo o que a pessoa acabou de dizer é o que
faz um assistente parecer um formulário.

A extração é determinística e **ancorada em rótulos**: cada valor só é aceito quando
aparece perto de uma palavra que diz o que ele é ("ganho", "gasto", "filhos"). Dois
valores monetários sem rótulo continuam ambíguos — nesse caso o extrator não adivinha, e
o fluxo pergunta a pergunta assume o que faltou. Errar a renda de alguém em silêncio é
pior do que fazer mais uma pergunta.

Nada aqui é gravado sem confirmação: o orquestrador mostra o resumo antes de enviar.
"""

import re
from dataclasses import dataclass, field

from src.utils.text_normalizer import contains_any, normalize_text
from src.utils.value_extractor import (
    NUMBERS_MAP,
    EmploymentType,
    extract_employment_type,
    extract_monetary_value,
)

# Rótulos que identificam cada campo. A ordem importa: "não tenho dívidas" precisa ser
# lido como dívida, não como despesa, então dívida é testada antes.
INCOME_LABELS = [
    "ganho",
    "ganhando",
    "recebo",
    "recebendo",
    "renda",
    "salario",
    "sálario",
    "remuneracao",
    "faturo",
    "tiro",
    "entra",
]

EXPENSE_LABELS = [
    "gasto",
    "gastos",
    "despesa",
    "despesas",
    "pago",
    "custo",
    "custos",
    "contas",
    "sai",
    "saem",
    "comprometido",
]

DEPENDENT_LABELS = [
    "filho",
    "filhos",
    "filha",
    "filhas",
    "dependente",
    "dependentes",
    "crianca",
    "criancas",
]

DEBT_LABELS = [
    "divida",
    "dividas",
    "devendo",
    "devo",
    "emprestimo",
    "emprestimos",
    "financiamento",
    "parcelado",
    "negativado",
    "nome sujo",
    "atrasado",
    "inadimplente",
    "serasa",
    "spc",
]

NO_DEBT_MARKERS = [
    "sem divida",
    "sem dividas",
    "nao tenho divida",
    "nao tenho dividas",
    "nenhuma divida",
    "zero divida",
    "nao devo",
    "nao estou devendo",
    "tudo pago",
    "tudo quitado",
    "quitado",
    "quitei",
    "nome limpo",
    "limpo",
    "sem emprestimo",
    "sem emprestimos",
    "nao tenho emprestimo",
]

# "sem filhos", "nenhum dependente"
NO_DEPENDENT_MARKERS = [
    "sem filho",
    "sem filhos",
    "sem dependente",
    "sem dependentes",
    "nenhum filho",
    "nenhum dependente",
    "nao tenho filho",
    "nao tenho filhos",
    "nao tenho dependente",
    "nao tenho dependentes",
    "moro sozinho",
    "moro sozinha",
]

# Quantos caracteres depois do rótulo ainda contam como "perto dele".
LABEL_WINDOW = 40

MAX_INCOME = 1_000_000.0
MAX_DEPENDENTS = 20


@dataclass
class ProfileDraft:
    """O que foi possível extrair, e o que ficou faltando."""

    renda_mensal: float | None = None
    tipo_emprego: EmploymentType | None = None
    despesas: float | None = None
    num_dependentes: int | None = None
    tem_dividas: bool | None = None
    # Campos que o extrator viu mas descartou por ambiguidade ou valor implausível.
    descartados: list[str] = field(default_factory=list)

    FIELDS = (
        "renda_mensal",
        "tipo_emprego",
        "despesas",
        "num_dependentes",
        "tem_dividas",
    )

    def filled(self) -> list[str]:
        return [name for name in self.FIELDS if getattr(self, name) is not None]

    def missing(self) -> list[str]:
        return [name for name in self.FIELDS if getattr(self, name) is None]

    @property
    def is_complete(self) -> bool:
        return not self.missing()

    def merge_into(self, data: dict) -> None:
        """Copia o que foi extraído para o dicionário do fluxo, sem sobrescrever."""
        for name in self.FIELDS:
            value = getattr(self, name)
            if value is not None and data.get(name) is None:
                data[name] = value


def _segments_near(normalized: str, labels: list[str]) -> list[str]:
    """Trechos do texto que começam em um dos rótulos.

    Recortar em volta do rótulo é o que impede "gasto 3 mil" de ser lido como renda
    quando a frase também diz "ganho 8 mil".
    """
    segments: list[str] = []
    for label in labels:
        for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", normalized):
            segments.append(normalized[match.end() : match.end() + LABEL_WINDOW])
    return segments


def _value_near(normalized: str, labels: list[str]) -> float | None:
    for segment in _segments_near(normalized, labels):
        value = extract_monetary_value(segment)
        if value is not None:
            return value
    return None


# Número imediatamente colado ao rótulo, em algarismo ou por extenso.
_NUMBER_WORDS = "|".join(sorted(NUMBERS_MAP, key=len, reverse=True))
_NUMBER_BEFORE = re.compile(rf"(?:(\d+)|(?<!\w)({_NUMBER_WORDS}))\s*$")
_NUMBER_AFTER = re.compile(rf"^\s*(?:(\d+)|({_NUMBER_WORDS})(?!\w))")


def _as_int(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    digits, word = match.group(1), match.group(2)
    if digits is not None:
        return int(digits)
    return NUMBERS_MAP.get(word) if word else None


def _count_near(normalized: str, labels: list[str]) -> int | None:
    """Conta dependentes a partir do número colado ao rótulo ("dois filhos").

    Precisa ser o número *adjacente*, não qualquer número da frase: em "gasto 3 mil,
    dois filhos" um extrator ganancioso lê o 3 das despesas e dá três dependentes.
    """
    for label in labels:
        for match in re.finditer(rf"(?<!\w){re.escape(label)}(?!\w)", normalized):
            antes = normalized[max(0, match.start() - 20) : match.start()]
            valor = _as_int(_NUMBER_BEFORE.search(antes))
            if valor is not None:
                return valor

            depois = normalized[match.end() : match.end() + 20]
            valor = _as_int(_NUMBER_AFTER.search(depois))
            if valor is not None:
                return valor
    return None


def _extract_debts(normalized: str) -> bool | None:
    # A negação é testada primeiro: "não tenho dívidas" contém "dívidas".
    if contains_any(normalized, NO_DEBT_MARKERS):
        return False
    if contains_any(normalized, DEBT_LABELS):
        return True
    return None


def extract_profile(text: str) -> ProfileDraft:
    """Lê o que der da frase. O que não for inequívoco fica como `None`."""
    draft = ProfileDraft()
    if not text or not text.strip():
        return draft

    normalized = normalize_text(text)

    renda = _value_near(normalized, INCOME_LABELS)
    if renda is not None:
        if 0 < renda <= MAX_INCOME:
            draft.renda_mensal = renda
        else:
            draft.descartados.append("renda_mensal")

    despesas = _value_near(normalized, EXPENSE_LABELS)
    if despesas is not None:
        if 0 <= despesas <= MAX_INCOME:
            draft.despesas = despesas
        else:
            draft.descartados.append("despesas")

    # Renda menor que a despesa declarada e possivel, mas renda igual a despesa quase
    # sempre significa que o mesmo numero foi lido duas vezes.
    if (
        draft.renda_mensal is not None
        and draft.despesas is not None
        and draft.renda_mensal == draft.despesas
    ):
        draft.despesas = None
        draft.descartados.append("despesas")

    draft.tipo_emprego = extract_employment_type(normalized)

    if contains_any(normalized, NO_DEPENDENT_MARKERS):
        draft.num_dependentes = 0
    else:
        dependentes = _count_near(normalized, DEPENDENT_LABELS)
        if dependentes is not None:
            if 0 <= dependentes <= MAX_DEPENDENTS:
                draft.num_dependentes = dependentes
            else:
                draft.descartados.append("num_dependentes")

    draft.tem_dividas = _extract_debts(normalized)

    return draft
