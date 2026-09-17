"""Personas de demonstração: entrar no produto sem conhecer nenhum CPF.

As personas não são uma lista fixa no código. Elas saem do banco (coluna
`is_demo_persona`, definida no seed por faixa de score) e a descrição de cada uma é
montada a partir do score e da tabela de limites. Trocar o seed troca as personas, sem
editar código nem arriscar uma lista que diverge dos dados.
"""

import logging

from src.config import get_settings
from src.db.repositories import ClientRepository
from src.models.domain import Client
from src.models.schemas import DemoPersona
from src.services.score_service import ScoreService
from src.utils.cpf import format_cpf
from src.utils.formatting import format_brl

logger = logging.getLogger(__name__)

DEMO_NOTICE = (
    "Ambiente de demonstração com dados fictícios. Não use seu CPF real: "
    "escolha um cliente de demonstração ou crie uma conta de teste."
)


def _profile_line(client: Client, ceiling: float) -> str:
    """Uma linha dizendo o que esse perfil demonstra na prática."""
    if client.score < 400:
        desfecho = "pedidos de aumento acima do teto são negados e levam à entrevista"
    elif client.score < 600:
        desfecho = "aumentos modestos passam; os grandes são negados"
    elif client.score < 800:
        desfecho = "aumentos até 1,5x o teto vão para análise manual"
    else:
        desfecho = "quase tudo é aprovado na hora"

    return (
        f"Score {client.score} · limite {format_brl(client.limite_atual)} · "
        f"teto {format_brl(ceiling)} — {desfecho}"
    )


class DemoService:
    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        score_service: ScoreService | None = None,
    ) -> None:
        self._settings = get_settings()
        self._clients = client_repository or ClientRepository()
        self._score_service = score_service or ScoreService()

    async def list_personas(self) -> list[DemoPersona]:
        clients = await self._clients.list_demo_personas()
        personas: list[DemoPersona] = []

        for client in clients:
            ceiling = await self._score_service.get_limit_for_score(client.score)
            personas.append(
                DemoPersona(
                    # O CPF é o id: são dados fictícios e públicos na própria listagem,
                    # e isso evita um mapa de ids paralelo que pode sair do ar com o seed.
                    id=client.cpf,
                    nome=client.nome,
                    primeiro_nome=client.first_name,
                    cpf=client.cpf,
                    cpf_formatado=format_cpf(client.cpf),
                    data_nascimento=client.data_nascimento,
                    score=client.score,
                    limite_atual=client.limite_atual,
                    max_limit_for_score=ceiling,
                    perfil=_profile_line(client, ceiling),
                )
            )

        return personas

    async def get_persona(self, persona_id: str) -> Client | None:
        client = await self._clients.get_by_cpf(persona_id)
        if client is None or not client.is_demo_persona:
            return None
        return client
