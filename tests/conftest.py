from __future__ import annotations

# ruff: noqa: E402
import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

os.environ.setdefault("ZISTUDY_DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("ZISTUDY_JWT_SECRET", "test-secret-change-me!")
os.environ.setdefault("ZISTUDY_SKIP_MIGRATIONS", "1")
os.environ.setdefault("ZISTUDY_CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("ZISTUDY_GEMINI_API_KEY", "test-gemini-key")

from zistudy_api.app import create_app
from zistudy_api.config.settings import Settings, get_settings
from zistudy_api.db import Base
from zistudy_api.db.session import configure_engine_factory, get_session

get_settings.cache_clear()


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    def _engine_factory(_settings: Settings) -> AsyncEngine:
        return create_async_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
        )

    configure_engine_factory(_engine_factory)

    engine = _engine_factory(
        Settings(
            database_url=TEST_DATABASE_URL,
            jwt_secret=os.environ["ZISTUDY_JWT_SECRET"],
        )
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        jwt_secret=os.environ["ZISTUDY_JWT_SECRET"],
        environment="test",
        log_level="INFO",
    )


@pytest.fixture(scope="session")
def session_maker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def prepare_database(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture()
def app(settings: Settings, session_maker):
    application = create_app(settings)

    async def _get_session_override():
        async with session_maker() as session:
            yield session

    application.dependency_overrides[get_session] = _get_session_override
    return application


@pytest_asyncio.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with (
        LifespanManager(app),
        AsyncClient(transport=transport, base_url="http://test") as async_client,
    ):
        yield async_client
