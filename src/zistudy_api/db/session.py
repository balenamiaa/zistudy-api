from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from zistudy_api.config.settings import Settings, get_settings

EngineFactory = Callable[[Settings], AsyncEngine]

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_engine_factory: EngineFactory | None = None


def configure_engine_factory(factory: EngineFactory) -> None:
    """Allow tests to configure a custom engine factory."""

    global _engine_factory, _engine, _sessionmaker
    _engine_factory = factory
    _engine = None
    _sessionmaker = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the singleton async engine."""

    global _engine, _sessionmaker

    if _engine is not None:
        return _engine

    settings = settings or get_settings()
    factory = _engine_factory or _create_engine
    _engine = factory(settings)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the async sessionmaker, initialising it if necessary."""

    global _sessionmaker
    if _sessionmaker is None:
        get_engine(settings)
        assert _sessionmaker is not None  # For type-checkers
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a database session."""

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan_context() -> AsyncIterator[None]:
    """Gracefully dispose engine during FastAPI lifespan events."""

    try:
        yield
    finally:
        if _engine is not None:
            await _engine.dispose()


async def reset_engine() -> None:
    """Dispose the current engine/sessionmaker for tests."""

    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


__all__ = [
    "configure_engine_factory",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "lifespan_context",
    "reset_engine",
]
