from datetime import UTC, datetime, timedelta, timezone

# Brasil nao tem horario de verao desde 2019: offset fixo evita depender de tzdata no Windows.
BRAZIL_TZ = timezone(timedelta(hours=-3), name="BRT")


def _to_brazilian_separators(text: str) -> str:
    return text.replace(",", "@").replace(".", ",").replace("@", ".")


def format_brl(value: float) -> str:
    """Formata valores no padrao brasileiro: R$ 15.000,00."""
    return f"R$ {_to_brazilian_separators(f'{value:,.2f}')}"


def format_rate(rate: float) -> str:
    """Taxa de cambio legivel: 5,15 para taxas >= 1, quatro casas para fracoes (0,0360)."""
    text = f"{rate:,.2f}" if rate >= 1 else f"{rate:.4f}"
    return _to_brazilian_separators(text)


def format_datetime_brt(moment: datetime) -> str:
    """Data e hora no horario de Brasilia: 17/09/2026 12:12."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(BRAZIL_TZ).strftime("%d/%m/%Y %H:%M")
