def format_brl(value: float) -> str:
    """Formata valores no padrao brasileiro: R$ 15.000,00."""
    text = f"{value:,.2f}"
    text = text.replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {text}"
