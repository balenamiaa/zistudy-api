from __future__ import annotations

from celery import Celery

from zistudy_api.config.settings import get_settings


def _create_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "zistudy",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    app.conf.update(
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=settings.celery_task_always_eager,
        timezone="UTC",
        enable_utc=True,
        include=["zistudy_api.services.job_processors"],
    )
    app.autodiscover_tasks(["zistudy_api.services"], force=True, related_name="tasks")
    app.autodiscover_tasks(["zistudy_api.services.job_processors"])
    return app


celery_app = _create_celery()

# Ensure task modules are imported so Celery registers them when the worker starts.

__all__ = ["celery_app"]
