"""Modelo relacional do Banco Ágil.

Substitui os CSVs. Os nomes das colunas seguem os CSVs originais (`limite_atual`,
`novo_limite_solicitado`) para que o seed e a documentação do desafio continuem
legíveis; o que muda é onde o dado vive e quem garante a consistência.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ClientModel(Base):
    __tablename__ = "clients"

    cpf: Mapped[str] = mapped_column(String(11), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    data_nascimento: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limite_atual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Preenchidos pelo auto-cadastro; nulos para os clientes vindos do seed.
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cidade: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Distingue os clientes do seed (usados como personas) dos criados pelo visitante,
    # para que `DEMO_RESET_ON_START` saiba o que recriar e a listagem de personas
    # não exponha contas de terceiros.
    origem: Mapped[str] = mapped_column(String(20), nullable=False, default="seed")
    is_demo_persona: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    limit_requests: Mapped[list["LimitRequestModel"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    score_events: Mapped[list["ScoreEventModel"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_clients_is_demo_persona", "is_demo_persona"),)


class ScoreLimitModel(Base):
    """Tabela de teto de limite por faixa de score (antigo `score_limite.csv`)."""

    __tablename__ = "score_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_min: Mapped[int] = mapped_column(Integer, nullable=False)
    score_max: Mapped[int] = mapped_column(Integer, nullable=False)
    limite: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("score_min", "score_max", name="uq_score_range"),)


class LimitRequestModel(Base):
    """Cada pedido de aumento, aprovado ou não. É a trilha de auditoria da decisão."""

    __tablename__ = "limit_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpf_cliente: Mapped[str] = mapped_column(
        String(11), ForeignKey("clients.cpf", ondelete="CASCADE"), nullable=False
    )
    data_hora_solicitacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    limite_atual: Mapped[float] = mapped_column(Float, nullable=False)
    novo_limite_solicitado: Mapped[float] = mapped_column(Float, nullable=False)
    status_pedido: Mapped[str] = mapped_column(String(20), nullable=False)
    # Por que a decisão foi essa: o que o atendente humano leria na tela.
    motivo: Mapped[str | None] = mapped_column(String(400), nullable=True)
    score_no_pedido: Mapped[int | None] = mapped_column(Integer, nullable=True)

    client: Mapped[ClientModel] = relationship(back_populates="limit_requests")

    __table_args__ = (Index("ix_limit_requests_cpf", "cpf_cliente"),)


class ScoreEventModel(Base):
    """Histórico de mudanças de score, com a origem da mudança.

    Sem isso, "seu score subiu" é uma afirmação que o sistema não consegue justificar
    depois — e justificar decisão de crédito é requisito, não enfeite.
    """

    __tablename__ = "score_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpf_cliente: Mapped[str] = mapped_column(
        String(11), ForeignKey("clients.cpf", ondelete="CASCADE"), nullable=False
    )
    score_anterior: Mapped[int] = mapped_column(Integer, nullable=False)
    score_novo: Mapped[int] = mapped_column(Integer, nullable=False)
    origem: Mapped[str] = mapped_column(String(30), nullable=False)
    detalhe: Mapped[str | None] = mapped_column(String(400), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped[ClientModel] = relationship(back_populates="score_events")

    __table_args__ = (Index("ix_score_events_cpf", "cpf_cliente"),)
