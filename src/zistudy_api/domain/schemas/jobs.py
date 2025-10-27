from __future__ import annotations

from datetime import datetime
from enum import Enum

from zistudy_api.domain.schemas.base import BaseSchema


class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class JobSummary(BaseSchema):
    id: int
    job_type: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: dict | None = None


class JobCreateResponse(BaseSchema):
    job: JobSummary


__all__ = ["JobStatus", "JobSummary", "JobCreateResponse"]
