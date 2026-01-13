import logging
from datetime import datetime, timezone

from src.models.schemas import (
    CreditLimitResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
)
from src.services.csv_service import CSVService
from src.services.score_service import ScoreService
from src.utils.exceptions import ClientNotFoundError

logger = logging.getLogger(__name__)


class CreditAgent:
    def __init__(self) -> None:
        self._csv_service = CSVService()
        self._score_service = ScoreService()

    async def get_limit(self, cpf: str) -> CreditLimitResponse:
        client = await self._csv_service.get_client_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        score = client.score
        current_limit = await self._score_service.get_limit_for_score(score)
        available_limit = current_limit * 0.8

        logger.info(f"Retrieved credit limit for CPF: {cpf[:3]}***")

        return CreditLimitResponse(
            cpf=cpf,
            current_limit=current_limit,
            available_limit=available_limit,
            score=score,
        )

    async def request_increase(
        self, cpf: str, request: LimitIncreaseRequest
    ) -> LimitIncreaseResponse:
        client = await self._csv_service.get_client_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        current_limit = await self._score_service.get_limit_for_score(client.score)

        status = await self._score_service.evaluate_limit_request(
            score=client.score,
            current_limit=current_limit,
            requested_limit=request.new_limit,
        )

        request_record = {
            "cpf_cliente": cpf,
            "data_hora_solicitacao": datetime.now(timezone.utc).isoformat(),
            "limite_atual": current_limit,
            "novo_limite_solicitado": request.new_limit,
            "status_pedido": status,
        }

        await self._csv_service.append_limit_request(request_record)

        logger.info(f"Limit increase request for CPF: {cpf[:3]}***, status: {status}")

        message = self._get_status_message(status, request.new_limit)

        offer_interview = status == "denied"
        interview_message = None
        if offer_interview:
            interview_message = (
                "Gostaria de realizar uma entrevista financeira para melhorar seu score? "
                "Com base nas suas informações, podemos reavaliar seu limite de crédito."
            )

        return LimitIncreaseResponse(
            cpf=cpf,
            requested_limit=request.new_limit,
            status=status,
            message=message,
            offer_interview=offer_interview,
            interview_message=interview_message,
        )

    def _get_status_message(self, status: str, requested_limit: float) -> str:
        messages = {
            "approved": f"Sua solicitação de limite de R$ {requested_limit:,.2f} foi aprovada!",
            "pending_analysis": "Sua solicitação está em análise. Entraremos em contato em breve.",
            "denied": "Infelizmente, sua solicitação não pôde ser aprovada no momento.",
        }
        return messages.get(status, "Solicitação processada.")
