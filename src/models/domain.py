from dataclasses import dataclass


@dataclass
class Client:
    cpf: str
    nome: str
    data_nascimento: str
    score: int
    limite_atual: float


@dataclass
class ScoreLimit:
    score_min: int
    score_max: int
    limite: float


@dataclass
class LimitRequest:
    cpf_cliente: str
    data_hora_solicitacao: str
    limite_atual: float
    novo_limite_solicitado: float
    status_pedido: str
