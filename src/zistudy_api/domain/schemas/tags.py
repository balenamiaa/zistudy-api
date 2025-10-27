from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from zistudy_api.domain.schemas.base import BaseSchema, TimestampedSchema

TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class TagCreate(BaseSchema):
    name: TagName = Field(..., description="Human-friendly tag name.")


class TagRead(TimestampedSchema):
    id: int = Field(..., description="Tag identifier.")
    name: str = Field(..., description="Human-friendly tag name.")


class TagUsage(BaseSchema):
    tag: TagRead
    usage_count: int = Field(..., ge=0)


class TagSearchResponse(BaseSchema):
    items: list[TagRead]
    total: int


__all__ = ["TagCreate", "TagRead", "TagUsage", "TagSearchResponse"]
