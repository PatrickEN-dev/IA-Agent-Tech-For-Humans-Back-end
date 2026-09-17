"""Objetos de domínio devolvidos pelos repositórios.

São dataclasses simples, não entidades do SQLAlchemy: os agentes não importam ORM,
então trocar SQLite por Postgres (ou por um mock em teste) não toca em regra de negócio.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Client:
    cpf: str
    nome: str
    data_nascimento: str
    score: int
    limite_atual: float
    email: str | None = None
    cidade: str | None = None
    uf: str | None = None
    cep: str | None = None
    origem: str = "seed"
    is_demo_persona: bool = False

    @property
    def first_name(self) -> str:
        return self.nome.split()[0] if self.nome else ""


@dataclass
class ScoreLimit:
    score_min: int
    score_max: int
    limite: float


@dataclass
class LimitRequest:
    cpf_cliente: str
    data_hora_solicitacao: datetime
    limite_atual: float
    novo_limite_solicitado: float
    status_pedido: str
    motivo: str | None = None
    score_no_pedido: int | None = None


@dataclass
class ScoreEvent:
    cpf_cliente: str
    score_anterior: int
    score_novo: int
    origem: str
    detalhe: str | None = None
    criado_em: datetime | None = None
