import logging

from src.services.csv_service import CSVService

logger = logging.getLogger(__name__)

# Pesos conforme especificação do desafio técnico
PESO_RENDA = 30

PESO_EMPREGO: dict[str, int] = {
    "FORMAL": 300,
    "CLT": 300,
    "AUTONOMO": 200,
    "DESEMPREGADO": 0,
}

PESO_DEPENDENTES: dict[int, int] = {
    0: 100,
    1: 80,
    2: 60,
    3: 30,  # 3+ dependentes
}

PESO_DIVIDAS: dict[bool, int] = {
    True: -100,  # tem dívidas
    False: 100,  # não tem dívidas
}


class ScoreService:
    def __init__(self) -> None:
        self._csv_service = CSVService()

    async def get_limit_for_score(self, score: int) -> float:
        limits = await self._csv_service.read_score_limits()

        for limit_range in limits:
            if limit_range["score_min"] <= score <= limit_range["score_max"]:
                return limit_range["limite"]

        if score < 300:
            return 500.0
        elif score >= 900:
            return 50000.0

        return 1000.0

    async def evaluate_limit_request(
        self, score: int, current_limit: float, requested_limit: float
    ) -> str:
        """
        Avalia solicitação de aumento de limite conforme especificação:
        - Verifica se o valor solicitado é permitido para o score atual
        - Usa a tabela score_limite.csv para determinar o limite máximo
        - Se score permite o valor solicitado: 'aprovado'
        - Caso contrário: 'rejeitado'
        """
        # Se está pedindo menos ou igual ao atual, aprova
        if requested_limit <= current_limit:
            return "approved"

        # Obtém o limite máximo permitido para o score atual
        max_limit_for_score = await self.get_limit_for_score(score)

        # Verifica se o valor solicitado está dentro do permitido pelo score
        if requested_limit <= max_limit_for_score:
            return "approved"

        # Score não permite o valor solicitado
        return "denied"

    def calculate_interview_score(
        self,
        renda_mensal: float,
        tipo_emprego: str,
        despesas: float,
        num_dependentes: int,
        tem_dividas: bool,
    ) -> int:
        """
        Calcula o score de crédito conforme fórmula especificada no desafio:

        score = (
            (renda_mensal / (despesas + 1)) * peso_renda +
            peso_emprego[tipo_emprego] +
            peso_dependentes[num_dependentes] +
            peso_dividas[tem_dividas]
        )
        """
        # Componente de renda: (renda_mensal / (despesas + 1)) * peso_renda
        componente_renda = (renda_mensal / (despesas + 1)) * PESO_RENDA

        # Componente de emprego
        tipo_emprego_upper = tipo_emprego.upper()
        componente_emprego = PESO_EMPREGO.get(tipo_emprego_upper, 0)

        # Componente de dependentes (3+ usa o valor de 3)
        dependentes_key = min(num_dependentes, 3)
        componente_dependentes = PESO_DEPENDENTES.get(dependentes_key, 30)

        # Componente de dívidas
        componente_dividas = PESO_DIVIDAS.get(tem_dividas, 0)

        # Cálculo final
        score = (
            componente_renda
            + componente_emprego
            + componente_dependentes
            + componente_dividas
        )

        # Limita entre 0 e 1000
        return max(0, min(1000, int(score)))
