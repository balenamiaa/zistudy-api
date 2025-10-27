from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar

from pydantic import Field

from zistudy_api.domain.schemas.base import BaseSchema, GenericSchema

T = TypeVar("T")


class Pagination(BaseSchema):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginatedResponse(GenericSchema, Generic[T]):
    items: Sequence[T] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)


class ErrorBody(BaseSchema):
    code: int
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseSchema):
    error: ErrorBody


__all__ = ["ErrorBody", "ErrorEnvelope", "Pagination", "PaginatedResponse"]
