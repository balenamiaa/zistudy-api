from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from zistudy_api.config.settings import Settings, get_settings


def _celery_worker_main(loglevel: str) -> None:
    from zistudy_api.celery_app import celery_app

    celery_app.worker_main(
        [
            "worker",
            f"--loglevel={loglevel}",
        ]
    )


def _run_migrations(max_attempts: int = 8, base_delay: float = 1.0) -> None:
    from asyncpg import PostgresError
    from sqlalchemy.exc import OperationalError

    from zistudy_api.db.migrations import run_migrations

    attempt = 1
    while True:
        try:
            run_migrations()
            return
        except (OperationalError, PostgresError) as exc:
            if attempt >= max_attempts:
                raise
            wait = base_delay * attempt
            print(
                f"[main] Database not ready (attempt {attempt}/{max_attempts}): {exc}. "
                f"Retrying in {wait:.1f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
            attempt += 1


def _run_api(settings: Settings) -> None:
    from fastapi import FastAPI

    from zistudy_api.app import app
    reload_enabled = settings.environment == "local"
    host = settings.api_host
    port = settings.api_port
    app_target: FastAPI | str = "zistudy_api.app:app" if reload_enabled else app
    uvicorn.run(
        app_target,
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
        reload=reload_enabled,
    )


def _run_worker(settings: Settings) -> None:
    if settings.environment == "local":
        from watchfiles import run_process

        run_process(
            Path.cwd(),
            target=_celery_worker_main,
            args=(settings.celery_loglevel,),
            target_type="function",
        )
        return

    _celery_worker_main(settings.celery_loglevel)


def _start_worker_subprocess(settings: Settings) -> subprocess.Popen[bytes]:
    try:
        env = os.environ.copy()
        if settings.environment == "local":
            command = (
                f"celery -A zistudy_api.celery_app:celery_app worker "
                f"--loglevel={settings.celery_loglevel}"
            )
            return subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "watchfiles",
                    "--filter",
                    "python",
                    "--target-type",
                    "command",
                    command,
                ],
                env=env,
            )

        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "zistudy_api.celery_app:celery_app",
                "worker",
                f"--loglevel={settings.celery_loglevel}",
            ],
            env=env,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(
            "Unable to locate Celery executable. Ensure Celery is installed or run the worker "
            "via `ZISTUDY_PROCESS_TYPE=worker uv run main.py`."
        ) from exc


def _bootstrap_settings():
    try:
        return get_settings()
    except ValidationError as exc:
        missing = sorted(
            {
                ".".join(str(part) for part in error["loc"])
                for error in exc.errors()
                if error.get("type") == "missing"
            }
        )
        if missing:
            print(
                "[main] Missing required configuration. "
                "Set environment variables (prefix ZISTUDY_) for: "
                f"{', '.join(missing)}",
                file=sys.stderr,
            )
        raise


def main() -> None:
    try:
        settings = _bootstrap_settings()
    except ValidationError:
        sys.exit(1)

    process_type = settings.process_type

    if process_type == "worker":
        _run_worker(settings)
        return

    _run_migrations()

    if process_type == "api-with-worker":
        worker_process: subprocess.Popen[bytes] | None = None
        try:
            worker_process = _start_worker_subprocess(settings)
        except RuntimeError as exc:
            print(f"[main] {exc}", file=sys.stderr)
        try:
            _run_api(settings)
        finally:
            if worker_process and worker_process.poll() is None:
                worker_process.send_signal(signal.SIGTERM)
                try:
                    worker_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker_process.kill()
        return

    _run_api(settings)


if __name__ == "__main__":
    main()
