import logging

from src.db.repositories import ClientRepository
from src.models.schemas import InterviewRequest, InterviewResponse
from src.services.score_service import ScoreService
from src.utils.cpf import mask_cpf
from src.utils.exceptions import ClientNotFoundError
from src.utils.formatting import format_brl

logger = logging.getLogger(__name__)


class InterviewAgent:
    """Recalcula o score a partir do perfil financeiro declarado.

    O score novo combina histórico e entrevista com pesos fixos (0,6 / 0,4) em vez de
    média simples, e a resposta diz quais fatores pesaram — decisão de crédito que o
    cliente não consegue entender é decisão que o banco não consegue defender.
    """

    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        score_service: ScoreService | None = None,
    ) -> None:
        self._clients = client_repository or ClientRepository()
        self._score_service = score_service or ScoreService()

    async def submit(self, cpf: str, request: InterviewRequest) -> InterviewResponse:
        client = await self._clients.get_by_cpf(cpf)
        if not client:
            raise ClientNotFoundError(cpf)

        breakdown = self._score_service.calculate_interview_score(
            renda_mensal=request.renda_mensal,
            tipo_emprego=request.tipo_emprego,
            despesas=request.despesas,
            num_dependentes=request.num_dependentes,
            tem_dividas=request.tem_dividas,
        )

        final_score = self._score_service.blend_scores(
            client.score, breakdown.score_calculado
        )
        new_ceiling = await self._score_service.get_limit_for_score(final_score)

        # O teto subiu? O limite acompanha. Baixou? O limite atual é preservado:
        # reduzir limite concedido é decisão de risco, não efeito colateral de uma
        # entrevista que o próprio cliente resolveu fazer.
        new_limit = max(client.limite_atual, new_ceiling)

        await self._clients.update_score(
            cpf,
            final_score,
            new_limit,
            origem="entrevista",
            detalhe=(
                f"entrevista={breakdown.score_calculado}; "
                f"componentes={breakdown.componentes}"
            ),
        )

        explanation = self._score_service.explain_factors(breakdown, request.tipo_emprego)
        recommendation = self._build_recommendation(
            previous_score=client.score,
            final_score=final_score,
            previous_limit=client.limite_atual,
            new_limit=new_limit,
            explanation=explanation,
        )

        logger.info(
            "Entrevista concluida para %s: %s -> %s",
            mask_cpf(cpf),
            client.score,
            final_score,
        )

        return InterviewResponse(
            cpf=cpf,
            previous_score=client.score,
            new_score=final_score,
            interview_score=breakdown.score_calculado,
            score_factors=breakdown.componentes,
            current_limit=new_limit,
            recommendation=recommendation,
            redirect_to="/credit/limit",
        )

    @staticmethod
    def _build_recommendation(
        *,
        previous_score: int,
        final_score: int,
        previous_limit: float,
        new_limit: float,
        explanation: str,
    ) -> str:
        delta = final_score - previous_score

        if delta > 0:
            head = f"Seu score subiu de {previous_score} para {final_score}."
        elif delta < 0:
            head = f"Seu score foi ajustado de {previous_score} para {final_score}."
        else:
            head = f"Seu score permaneceu em {final_score}."

        if new_limit > previous_limit:
            limit_line = (
                f" Com isso, seu limite passou de {format_brl(previous_limit)} para "
                f"{format_brl(new_limit)}."
            )
        else:
            limit_line = f" Seu limite segue em {format_brl(new_limit)}."

        tail = f" {explanation}" if explanation else ""
        return f"{head}{limit_line}{tail}"
