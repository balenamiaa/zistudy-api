from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Mapping, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette import status as http_status

from zistudy_api.api import include_api_routes
from zistudy_api.config.settings import Settings, get_settings
from zistudy_api.core.logging import configure_logging
from zistudy_api.db.session import lifespan_context
from zistudy_api.domain.schemas.common import ErrorBody, ErrorEnvelope

HTTP_STATUS_MESSAGES: Mapping[int, str] = cast(
    Mapping[int, str],
    getattr(http_status, "HTTP_STATUS_CODES", {}),
)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    async with lifespan_context():
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory for the ZiStudy API."""

    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        lifespan=_lifespan,
    )

    if settings.environment == "production" and (
        not settings.cors_origins or settings.cors_origins == ["*"]
    ):
        raise RuntimeError("Production deployments must configure explicit CORS origins.")

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    include_api_routes(app)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = (
            exc.detail
            if isinstance(exc.detail, str)
            else HTTP_STATUS_MESSAGES.get(exc.status_code, "Error")
        )
        details = exc.detail if isinstance(exc.detail, dict) else None
        payload = ErrorEnvelope(
            error=ErrorBody(
                code=exc.status_code,
                message=message,
                details=details,
            )
        ).model_dump(mode="json")
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:  # pragma: no cover
        payload = ErrorEnvelope(
            error=ErrorBody(
                code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                details={"reason": str(exc)},
            )
        ).model_dump(mode="json")
        return JSONResponse(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload)

    return app


app = create_app()


__all__ = ["app", "create_app"]
