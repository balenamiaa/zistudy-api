from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.typing import FilteringBoundLogger

from zistudy_api.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        final_processor: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            final_processor,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a structlog logger instance."""

    logger = structlog.get_logger(name)
    return cast(FilteringBoundLogger, logger)


__all__ = ["configure_logging", "get_logger"]
