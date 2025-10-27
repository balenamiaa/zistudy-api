from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from zistudy_api.config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CFG_PATH = PROJECT_ROOT / "alembic.ini"
DEFAULT_SCRIPT_PATH = PROJECT_ROOT / "alembic"


def _resolve_path(
    *,
    env_var: str,
    default: Path,
    fallback: Path,
) -> Path:
    candidate = os.environ.get(env_var)
    if candidate:
        path = Path(candidate)
        if path.exists():
            return path

    if default.exists():
        return default
    if fallback.exists():
        return fallback
    raise RuntimeError(
        f"Alembic resource not found. Checked: {default}, {fallback}. "
        f"Set {env_var} to the correct location."
    )


def run_migrations(target_revision: str = "head") -> None:
    if os.environ.get("ZISTUDY_SKIP_MIGRATIONS", "").lower() in {"1", "true"}:
        return

    settings = get_settings()

    project_cwd = Path.cwd()
    cfg_path = _resolve_path(
        env_var="ZISTUDY_ALEMBIC_CONFIG",
        default=DEFAULT_CFG_PATH,
        fallback=project_cwd / "alembic.ini",
    )
    script_location = _resolve_path(
        env_var="ZISTUDY_ALEMBIC_PATH",
        default=DEFAULT_SCRIPT_PATH,
        fallback=project_cwd / "alembic",
    )
    try:
        candidates = ", ".join(str(path) for path in script_location.iterdir())
    except Exception:
        candidates = "<unavailable>"
    print(f"[migrations] Using script directory: {script_location} (contents: {candidates})")

    config = Config(str(cfg_path))
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", settings.database_url)

    print(f"[migrations] Running migrations using {cfg_path} -> {script_location}")
    try:
        command.upgrade(config, target_revision)
    except Exception as exc:  # pragma: no cover - surfaced during startup
        raise RuntimeError(f"Failed to apply database migrations: {exc}") from exc

    _ensure_schema_created()


def _ensure_schema_created() -> None:
    import asyncio

    import sqlalchemy as sa
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import create_async_engine

    from zistudy_api.config.settings import get_settings

    settings = get_settings()

    async def _process() -> None:
        engine = create_async_engine(settings.database_url, echo=False)
        try:
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text("SELECT version_num FROM alembic_version LIMIT 1")
                    )
                    has_version = result.first() is not None
            except SQLAlchemyError:
                has_version = False

            if has_version:
                return

            print("[migrations] Alembic version table missing; creating schema via metadata.")
            from zistudy_api.db import Base

            alembic_table = sa.Table(
                "alembic_version",
                sa.MetaData(),
                sa.Column("version_num", sa.String(32), primary_key=True),
            )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(alembic_table.create, checkfirst=True)
                await conn.execute(sa.delete(alembic_table))
                await conn.execute(
                    sa.insert(alembic_table).values(version_num="0001_initial_schema")
                )
        finally:
            await engine.dispose()

    asyncio.run(_process())


if __name__ == "__main__":  # pragma: no cover
    run_migrations()
