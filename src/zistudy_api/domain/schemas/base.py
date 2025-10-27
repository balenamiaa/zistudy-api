from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.generics import GenericModel

SCHEMA_CONFIG = ConfigDict(
    frozen=True,
    from_attributes=True,
    populate_by_name=True,
    extra="ignore",
)

ALLOW_EXTRA_SCHEMA_CONFIG = ConfigDict(
    frozen=True,
    from_attributes=True,
    populate_by_name=True,
    extra="allow",
)


class BaseSchema(BaseModel):
    """Base schema with shared configuration."""

    model_config = SCHEMA_CONFIG


class GenericSchema(GenericModel):
    """Generic-compatible schema base."""

    model_config = SCHEMA_CONFIG


class TimestampedSchema(BaseSchema):
    """Mixin schema providing timestamp fields."""

    created_at: datetime = Field(..., description="Creation timestamp in UTC.")
    updated_at: datetime = Field(..., description="Last update timestamp in UTC.")


__all__ = ["ALLOW_EXTRA_SCHEMA_CONFIG", "BaseSchema", "GenericSchema", "TimestampedSchema"]
