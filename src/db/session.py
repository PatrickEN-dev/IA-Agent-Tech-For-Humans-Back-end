"""Engine e sessão do SQLAlchemy async.

O engine é criado sob demanda (não no import) para que os testes consigam apontar
`DATABASE_URL` para um arquivo temporário depois que `src` já foi importado.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings
from src.db.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """SQLite não cria o diretório do arquivo sozinho; o primeiro deploy quebraria."""
    if not database_url.startswith("sqlite"):
        return
    _, _, path_part = database_url.partition(":///")
    if not path_part or path_part == ":memory:":
        return
    Path(path_part).expanduser().parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        _ensure_sqlite_dir(url)
        # `pool_pre_ping` evita a primeira query falhar contra um Postgres que
        # derrubou a conexão ociosa (comum em planos gratuitos).
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True, future=True)
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Database engine criado (%s)", url.split("://")[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Unidade de trabalho: commit no sucesso, rollback em qualquer exceção."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def dispose_engine() -> None:
    """Fecha o pool e esquece o engine, para que o próximo `get_engine` releia as settings."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
