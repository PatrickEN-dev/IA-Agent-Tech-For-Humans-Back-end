import logging

from src.models.schemas import InterviewRequest, InterviewResponse
from src.services.csv_service import CSVService
from src.services.score_service import ScoreService
from src.utils.exceptions import ClientNotFoundError

logger = logging.getLogger(__name__)


class InterviewAgent:
    def __init__(self) -> None:
        self._csv_service = CSVService()
        self._score_service = ScoreService()

    async def submit(self, cpf: str, request: InterviewRequest) -> InterviewResponse:
        client = await self._csv_service.get_client_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        new_score = self._score_service.calculate_interview_score(
            renda_mensal=request.renda_mensal,
            tipo_emprego=request.tipo_emprego,
            despesas=request.despesas,
            num_dependentes=request.num_dependentes,
            tem_dividas=request.tem_dividas,
        )

        final_score = min(1000, max(0, (client.score + new_score) // 2))

        await self._csv_service.update_client_score(cpf, final_score)

        recommendation = self._get_recommendation(final_score)

        logger.info(f"Interview submitted for CPF: {cpf[:3]}***, new score: {final_score}")

        return InterviewResponse(
            cpf=cpf,
            previous_score=client.score,
            new_score=final_score,
            recommendation=recommendation,
            redirect_to="/credit/limit",
        )

    def _get_recommendation(self, score: int) -> str:
        if score >= 800:
            return "Perfil excelente! Você se qualifica para nossas opções de crédito premium."
        elif score >= 600:
            return "Bom perfil! Você tem acesso aos produtos de crédito padrão."
        elif score >= 400:
            return "Perfil moderado. Considere reduzir despesas para melhorar seu score."
        else:
            return "Seu perfil precisa de melhorias. Recomendamos uma consultoria financeira."
