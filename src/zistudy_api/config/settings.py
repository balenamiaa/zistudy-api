from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables or .env files."""

    model_config = SettingsConfigDict(
        env_prefix="ZISTUDY_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    app_name: str = "ZiStudy API"
    api_version: str = "0.2.0"
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
        ]
    )
    ai_pdf_max_bytes: int = Field(
        default=150 * 1024 * 1024,
        ge=1,
        description="Maximum allowed PDF upload size (in bytes) for AI endpoints.",
    )
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    process_type: Literal["api", "worker", "api-with-worker"] = "api"
    database_url: str = Field(..., description="SQLAlchemy-compatible database URL.")
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    default_page_size: int = 20
    max_page_size: int = 100
    jwt_secret: str = Field(..., min_length=16, description="Secret key for signing JWTs.")
    jwt_algorithm: str = "HS256"
    access_token_exp_minutes: int = 15
    refresh_token_exp_minutes: int = 60 * 24 * 14
    refresh_token_length: int = 64
    api_key_length: int = 48
    ai_provider: Literal["gemini"] = "gemini"
    gemini_api_key: str | None = Field(
        default=None,
        description="API key for the Google Gemini platform.",
    )
    gemini_endpoint: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        description="Base URL for the Gemini API.",
    )
    gemini_model: str = Field(
        default="gemini-2.5-pro",
        description="Default Gemini model identifier used for generation requests.",
    )
    gemini_request_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Timeout for outbound requests to the Gemini API.",
    )
    ai_generation_default_temperature: float = Field(
        default=0.35,
        ge=0.0,
        le=2.0,
        description="Default creativity level for AI generated study cards.",
    )
    ai_generation_default_card_count: int = Field(
        default=8,
        ge=1,
        le=40,
        description="Fallback number of cards generated when a client omits the target count.",
    )
    ai_generation_max_card_count: int = Field(
        default=20,
        ge=1,
        le=60,
        description="Hard upper bound on the number of cards generated per request.",
    )
    ai_generation_max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of attempts when the AI output fails schema validation.",
    )
    gemini_pdf_mode: Literal["native", "ingest"] = Field(
        default="native",
        description="How PDF context should be supplied to Gemini (native inline PDFs or pre-extracted text/images).",
    )
    celery_broker_url: str = Field(
        default="redis://localhost:6379/0",
        description="Celery broker URL.",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1",
        description="Celery result backend URL.",
    )
    celery_task_always_eager: bool = Field(
        default=False,
        description="Run Celery tasks synchronously (useful for tests).",
    )
    celery_loglevel: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()  # pyright: ignore[reportCallIssue]


__all__ = ["Settings", "get_settings"]
