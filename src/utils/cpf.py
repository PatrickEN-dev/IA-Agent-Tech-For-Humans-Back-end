"""Validação e geração de CPF pelo algoritmo oficial de dígitos verificadores.

Não há consulta externa aqui: o algoritmo é aritmético e determinístico. A verificação
de que o CPF *existe* e pertence ao titular é responsabilidade do
`src/services/cpf_provider.py`, que isola a integração com a Receita Federal.
"""

import re

CPF_LENGTH = 11


def strip_cpf(cpf: str) -> str:
    """Mantém apenas os dígitos de um CPF ("529.982.247-25" -> "52998224725")."""
    return re.sub(r"\D", "", cpf or "")


def _check_digit(digits: list[int], weight_start: int) -> int:
    total = sum(digit * (weight_start - i) for i, digit in enumerate(digits))
    remainder = (total * 10) % 11
    return 0 if remainder == 10 else remainder


def is_valid_cpf(cpf: str) -> bool:
    """Valida os dois dígitos verificadores.

    Rejeita tamanho diferente de 11 e sequências de dígitos iguais ("11111111111"),
    que passam na conta mas são inválidas por convenção da Receita Federal.
    """
    digits_str = strip_cpf(cpf)

    if len(digits_str) != CPF_LENGTH:
        return False

    if digits_str == digits_str[0] * CPF_LENGTH:
        return False

    digits = [int(d) for d in digits_str]

    if _check_digit(digits[:9], 10) != digits[9]:
        return False

    return _check_digit(digits[:10], 11) == digits[10]


def format_cpf(cpf: str) -> str:
    """Aplica a máscara 000.000.000-00. Devolve a entrada intacta se não tiver 11 dígitos."""
    digits = strip_cpf(cpf)
    if len(digits) != CPF_LENGTH:
        return cpf
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def mask_cpf(cpf: str) -> str:
    """Versão para log e para exibição: 529.***.***-25."""
    digits = strip_cpf(cpf)
    if len(digits) != CPF_LENGTH:
        return "***"
    return f"{digits[:3]}.***.***-{digits[9:]}"


def generate_valid_cpf(seed: int) -> str:
    """Gera um CPF sinteticamente válido e determinístico a partir de `seed`.

    Mesma seed, mesmo CPF: usado pelo seed do banco e por `scripts/fix_client_cpfs.py`,
    que precisa ser idempotente. Não usa `random` justamente para não depender do estado
    global do módulo.
    """
    # Congruência linear simples: espalha a seed em 9 dígitos sem depender de `random`.
    state = (seed * 1_103_515_245 + 12_345) & 0x7FFFFFFF
    base: list[int] = []
    for _ in range(9):
        state = (state * 1_103_515_245 + 12_345) & 0x7FFFFFFF
        base.append((state >> 16) % 10)

    # Evita a sequência de dígitos iguais, que seria rejeitada por `is_valid_cpf`.
    if len(set(base)) == 1:
        base[0] = (base[0] + 1) % 10

    d1 = _check_digit(base, 10)
    d2 = _check_digit(base + [d1], 11)
    return "".join(str(d) for d in base + [d1, d2])
