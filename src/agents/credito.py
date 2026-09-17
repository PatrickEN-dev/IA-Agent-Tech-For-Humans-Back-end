import logging
from datetime import UTC, datetime

from src.db.repositories import ClientRepository, LimitRequestRepository
from src.models.domain import LimitRequest
from src.models.schemas import (
    CreditLimitResponse,
    LimitIncreaseRequest,
    LimitIncreaseResponse,
)
from src.services.score_service import ScoreService
from src.utils.cpf import mask_cpf
from src.utils.exceptions import ClientNotFoundError
from src.utils.formatting import format_brl

logger = logging.getLogger(__name__)


class CreditAgent:
    """Consulta de limite e decisão de aumento.

    O limite atual é o valor persistido do cliente, não o teto da faixa de score: são
    coisas diferentes, e confundi-las fazia um pedido "aprovado" não alterar nada.
    """

    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        score_service: ScoreService | None = None,
        limit_request_repository: LimitRequestRepository | None = None,
    ) -> None:
        self._clients = client_repository or ClientRepository()
        self._score_service = score_service or ScoreService()
        self._limit_requests = limit_request_repository or LimitRequestRepository()

    async def get_limit(self, cpf: str) -> CreditLimitResponse:
        client = await self._clients.get_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        ceiling = await self._score_service.get_limit_for_score(client.score)

        logger.info("Consulta de limite para %s", mask_cpf(cpf))

        return CreditLimitResponse(
            cpf=cpf,
            current_limit=client.limite_atual,
            max_limit_for_score=ceiling,
            score=client.score,
        )

    async def request_increase(
        self, cpf: str, request: LimitIncreaseRequest
    ) -> LimitIncreaseResponse:
        client = await self._clients.get_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        current_limit = client.limite_atual
        evaluation = await self._score_service.evaluate_limit_request(
            score=client.score,
            current_limit=current_limit,
            requested_limit=request.new_limit,
        )

        # Aprovado altera o limite de verdade. Sem isso, "aprovado" era só uma palavra.
        new_current_limit = current_limit
        if evaluation.decision == "approved" and request.new_limit > current_limit:
            await self._clients.update_limit(cpf, request.new_limit)
            new_current_limit = request.new_limit

        await self._limit_requests.append(
            LimitRequest(
                cpf_cliente=cpf,
                data_hora_solicitacao=datetime.now(UTC),
                limite_atual=current_limit,
                novo_limite_solicitado=request.new_limit,
                status_pedido=evaluation.decision,
                motivo=evaluation.motivo,
                score_no_pedido=client.score,
            )
        )

        logger.info(
            "Pedido de aumento para %s: %s (%s)",
            mask_cpf(cpf),
            evaluation.decision,
            evaluation.motivo,
        )

        message = self._build_message(
            decision=evaluation.decision,
            requested=request.new_limit,
            previous_limit=current_limit,
            ceiling=evaluation.ceiling,
        )

        offer_interview = evaluation.decision == "denied"
        interview_message = None
        if offer_interview:
            interview_message = (
                "Quer fazer uma entrevista financeira rápida? Com renda, despesas e "
                "vínculo de trabalho atualizados, posso reavaliar seu score e seu limite "
                "na hora."
            )

        return LimitIncreaseResponse(
            cpf=cpf,
            requested_limit=request.new_limit,
            status=evaluation.decision,
            current_limit=new_current_limit,
            max_limit_for_score=evaluation.ceiling,
            message=message,
            offer_interview=offer_interview,
            interview_message=interview_message,
        )

    @staticmethod
    def _build_message(
        *, decision: str, requested: float, previous_limit: float, ceiling: float
    ) -> str:
        if decision == "approved":
            if requested <= previous_limit:
                return (
                    f"O valor de {format_brl(requested)} já está disponível: seu limite "
                    f"atual é de {format_brl(previous_limit)}."
                )
            return (
                f"Aprovado! Seu limite passou de {format_brl(previous_limit)} para "
                f"{format_brl(requested)}, já valendo a partir de agora."
            )

        if decision == "pending_analysis":
            return (
                f"Seu pedido de {format_brl(requested)} ficou acima do limite que aprovo "
                f"automaticamente ({format_brl(ceiling)}), mas seu score permite análise "
                "manual. Encaminhei para o time de crédito e a resposta sai em até 2 dias "
                f"úteis. Seu limite segue em {format_brl(previous_limit)} até lá."
            )

        return (
            f"Não consigo aprovar {format_brl(requested)} agora. Com o seu score atual, o "
            f"teto é {format_brl(ceiling)} e seu limite é {format_brl(previous_limit)}."
        )
