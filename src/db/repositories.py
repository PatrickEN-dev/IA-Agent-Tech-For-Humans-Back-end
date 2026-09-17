"""Repositórios: a única parte do código que conhece SQLAlchemy.

Cada método abre e fecha sua própria unidade de trabalho. Isso é deliberado: as
operações desta aplicação são curtas e independentes (ler cliente, gravar pedido), e
uma sessão por requisição só acrescentaria uma dependência de contexto nos agentes sem
ganho real. Onde uma operação precisa ser atômica de ponta a ponta — aprovar aumento,
que altera o limite e registra o pedido — ela vive em um único método, em uma transação.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from src.db.models import (
    ClientModel,
    LimitRequestModel,
    ScoreEventModel,
    ScoreLimitModel,
)
from src.db.session import session_scope
from src.models.domain import Client, LimitRequest, ScoreEvent, ScoreLimit
from src.utils.cpf import mask_cpf, strip_cpf

logger = logging.getLogger(__name__)


def _to_client(row: ClientModel) -> Client:
    return Client(
        cpf=row.cpf,
        nome=row.nome,
        data_nascimento=row.data_nascimento,
        score=row.score,
        limite_atual=row.limite_atual,
        email=row.email,
        cidade=row.cidade,
        uf=row.uf,
        cep=row.cep,
        origem=row.origem,
        is_demo_persona=row.is_demo_persona,
    )


class ClientRepository:
    async def get_by_cpf(self, cpf: str) -> Client | None:
        normalized = strip_cpf(cpf)
        async with session_scope() as session:
            row = await session.get(ClientModel, normalized)
            return _to_client(row) if row else None

    async def exists(self, cpf: str) -> bool:
        return await self.get_by_cpf(cpf) is not None

    async def list_all(self) -> list[Client]:
        async with session_scope() as session:
            rows = (await session.scalars(select(ClientModel).order_by(ClientModel.nome))).all()
            return [_to_client(row) for row in rows]

    async def list_demo_personas(self) -> list[Client]:
        """Só os clientes marcados como persona: contas criadas por visitantes ficam de fora."""
        async with session_scope() as session:
            stmt = (
                select(ClientModel)
                .where(ClientModel.is_demo_persona.is_(True))
                .order_by(ClientModel.score)
            )
            rows = (await session.scalars(stmt)).all()
            return [_to_client(row) for row in rows]

    async def create(self, client: Client) -> Client:
        async with session_scope() as session:
            row = ClientModel(
                cpf=strip_cpf(client.cpf),
                nome=client.nome,
                data_nascimento=client.data_nascimento,
                score=client.score,
                limite_atual=client.limite_atual,
                email=client.email,
                cidade=client.cidade,
                uf=client.uf,
                cep=strip_cpf(client.cep) if client.cep else None,
                origem=client.origem,
                is_demo_persona=client.is_demo_persona,
            )
            session.add(row)
            await session.flush()
            logger.info("Cliente criado: %s (origem=%s)", mask_cpf(row.cpf), row.origem)
            return _to_client(row)

    async def update_limit(self, cpf: str, new_limit: float) -> bool:
        async with session_scope() as session:
            row = await session.get(ClientModel, strip_cpf(cpf))
            if row is None:
                return False
            row.limite_atual = new_limit
            return True

    async def update_score(
        self,
        cpf: str,
        new_score: int,
        new_limit: float | None = None,
        *,
        origem: str = "manual",
        detalhe: str | None = None,
    ) -> bool:
        """Altera o score e registra o evento na mesma transação.

        Score e histórico gravados juntos: se o histórico falhasse depois, o sistema
        teria um score que não sabe explicar.
        """
        async with session_scope() as session:
            row = await session.get(ClientModel, strip_cpf(cpf))
            if row is None:
                return False

            previous = row.score
            row.score = new_score
            if new_limit is not None:
                row.limite_atual = new_limit

            session.add(
                ScoreEventModel(
                    cpf_cliente=row.cpf,
                    score_anterior=previous,
                    score_novo=new_score,
                    origem=origem,
                    detalhe=detalhe,
                )
            )
            logger.info(
                "Score atualizado para %s: %s -> %s (%s)",
                mask_cpf(row.cpf),
                previous,
                new_score,
                origem,
            )
            return True

    async def list_score_events(self, cpf: str, limit: int = 10) -> list[ScoreEvent]:
        async with session_scope() as session:
            stmt = (
                select(ScoreEventModel)
                .where(ScoreEventModel.cpf_cliente == strip_cpf(cpf))
                .order_by(ScoreEventModel.criado_em.desc())
                .limit(limit)
            )
            rows = (await session.scalars(stmt)).all()
            return [
                ScoreEvent(
                    cpf_cliente=row.cpf_cliente,
                    score_anterior=row.score_anterior,
                    score_novo=row.score_novo,
                    origem=row.origem,
                    detalhe=row.detalhe,
                    criado_em=row.criado_em,
                )
                for row in rows
            ]

    async def count(self) -> int:
        async with session_scope() as session:
            return int((await session.scalar(select(func.count(ClientModel.cpf)))) or 0)


class ScoreLimitRepository:
    async def read_all(self) -> list[ScoreLimit]:
        async with session_scope() as session:
            stmt = select(ScoreLimitModel).order_by(ScoreLimitModel.score_min)
            rows = (await session.scalars(stmt)).all()
            return [
                ScoreLimit(
                    score_min=row.score_min, score_max=row.score_max, limite=row.limite
                )
                for row in rows
            ]

    async def limit_for_score(self, score: int) -> float | None:
        async with session_scope() as session:
            stmt = select(ScoreLimitModel).where(
                ScoreLimitModel.score_min <= score, ScoreLimitModel.score_max >= score
            )
            row = (await session.scalars(stmt)).first()
            return row.limite if row else None


class LimitRequestRepository:
    async def append(self, request: LimitRequest) -> None:
        async with session_scope() as session:
            session.add(
                LimitRequestModel(
                    cpf_cliente=strip_cpf(request.cpf_cliente),
                    data_hora_solicitacao=request.data_hora_solicitacao
                    or datetime.now(UTC),
                    limite_atual=request.limite_atual,
                    novo_limite_solicitado=request.novo_limite_solicitado,
                    status_pedido=request.status_pedido,
                    motivo=request.motivo,
                    score_no_pedido=request.score_no_pedido,
                )
            )

    async def list_by_cpf(self, cpf: str, limit: int = 10) -> list[LimitRequest]:
        async with session_scope() as session:
            stmt = (
                select(LimitRequestModel)
                .where(LimitRequestModel.cpf_cliente == strip_cpf(cpf))
                .order_by(LimitRequestModel.data_hora_solicitacao.desc())
                .limit(limit)
            )
            rows = (await session.scalars(stmt)).all()
            return [
                LimitRequest(
                    cpf_cliente=row.cpf_cliente,
                    data_hora_solicitacao=row.data_hora_solicitacao,
                    limite_atual=row.limite_atual,
                    novo_limite_solicitado=row.novo_limite_solicitado,
                    status_pedido=row.status_pedido,
                    motivo=row.motivo,
                    score_no_pedido=row.score_no_pedido,
                )
                for row in rows
            ]
