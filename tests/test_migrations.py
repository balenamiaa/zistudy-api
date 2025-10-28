from __future__ import annotations

import sqlite3
from pathlib import Path


def _fetch_version_sync(db_file: Path) -> str | None:
    with sqlite3.connect(db_file) as conn:
        cursor = conn.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
        return row[0] if row else None


def _table_names(db_file: Path) -> list[str]:
    with sqlite3.connect(db_file) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row[0] for row in cursor.fetchall()]


def _build_db_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def test_ensure_schema_created_bootstraps_when_missing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bootstrap.sqlite"
    db_url = _build_db_url(db_path)
    monkeypatch.setenv("ZISTUDY_DATABASE_URL", db_url)

    from zistudy_api.config.settings import get_settings

    get_settings.cache_clear()

    from zistudy_api.db.migrations import _ensure_schema_created

    _ensure_schema_created()

    tables = _table_names(db_path)
    assert "alembic_version" in tables
    assert _fetch_version_sync(db_path) == "0001_initial_schema"


def test_ensure_schema_created_skips_when_version_present(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bootstrap.sqlite"
    db_url = _build_db_url(db_path)
    monkeypatch.setenv("ZISTUDY_DATABASE_URL", db_url)

    from zistudy_api.config.settings import get_settings

    get_settings.cache_clear()

    from zistudy_api.db import Base
    from zistudy_api.db.migrations import _ensure_schema_created

    _ensure_schema_created()

    called_flag: dict[str, bool] = {"called": False}

    def _fail_create_all(*args, **kwargs) -> None:
        called_flag["called"] = True
        raise AssertionError("create_all should not run when alembic_version exists")

    monkeypatch.setattr(Base.metadata, "create_all", _fail_create_all)

    _ensure_schema_created()

    assert called_flag["called"] is False
    assert _fetch_version_sync(db_path) == "0001_initial_schema"
