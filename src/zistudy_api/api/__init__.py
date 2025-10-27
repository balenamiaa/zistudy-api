from __future__ import annotations

from fastapi import APIRouter, FastAPI

from zistudy_api.api.routes import ai, answers, auth, jobs, study_cards, study_sets, tags


def include_api_routes(app: FastAPI) -> None:
    """Register all API routers with the FastAPI application."""

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(ai.router)
    api_router.include_router(answers.router)
    api_router.include_router(auth.router)
    api_router.include_router(jobs.router)
    api_router.include_router(study_sets.router)
    api_router.include_router(study_cards.router)
    api_router.include_router(tags.router)
    app.include_router(api_router)


__all__ = ["include_api_routes"]
