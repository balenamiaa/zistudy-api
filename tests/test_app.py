from __future__ import annotations

import pytest
from fastapi.middleware.cors import CORSMiddleware

from zistudy_api.app import create_app
from zistudy_api.config.settings import Settings


def test_create_app_requires_configured_cors_in_production() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./test.db",
        jwt_secret="x" * 32,
        environment="production",
        cors_origins=["*"],
    )
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_create_app_configures_cors_for_non_production() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./test.db",
        jwt_secret="y" * 32,
        environment="local",
        cors_origins=["*"],
    )
    app = create_app(settings)
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)
