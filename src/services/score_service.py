import logging

from src.services.csv_service import CSVService

logger = logging.getLogger(__name__)


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
    3: 30,
}

PESO_DIVIDAS: dict[bool, int] = {
    True: -100,
    False: 100,
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
        if requested_limit <= current_limit:
            return "approved"

        max_limit_for_score = await self.get_limit_for_score(score)

        if requested_limit <= max_limit_for_score:
            return "approved"

        return "denied"

    def calculate_interview_score(
        self,
        renda_mensal: float,
        tipo_emprego: str,
        despesas: float,
        num_dependentes: int,
        tem_dividas: bool,
    ) -> int:
        componente_renda = (renda_mensal / (despesas + 1)) * PESO_RENDA

        tipo_emprego_upper = tipo_emprego.upper()
        componente_emprego = PESO_EMPREGO.get(tipo_emprego_upper, 0)

        dependentes_key = min(num_dependentes, 3)
        componente_dependentes = PESO_DEPENDENTES.get(dependentes_key, 30)

        componente_dividas = PESO_DIVIDAS.get(tem_dividas, 0)

        score = (
            componente_renda
            + componente_emprego
            + componente_dependentes
            + componente_dividas
        )

        return max(0, min(1000, int(score)))
