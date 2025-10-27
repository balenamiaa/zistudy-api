from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.repositories.jobs import JobRepository
from zistudy_api.domain.schemas.jobs import JobStatus, JobSummary


class ProcessorTask(Protocol):
    def delay(self, job_id: int) -> object: ...


class JobService:
    """Coordinate background job creation and retrieval."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repository = JobRepository(session)

    async def enqueue(
        self,
        *,
        job_type: str,
        owner_id: str,
        payload: dict,
        processor_task: ProcessorTask,
    ) -> JobSummary:
        """Persist a job request and dispatch the configured processor task."""
        job = await self._repository.create(job_type=job_type, owner_id=owner_id, payload=payload)
        await self._repository.set_status(job.id, status=JobStatus.PENDING.value)
        await self._session.commit()

        processor_task.delay(job.id)

        return JobSummary(
            id=job.id,
            job_type=job.job_type,
            status=JobStatus.PENDING,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error=job.error,
            result=None,
        )

    async def get_job(self, job_id: int, *, owner_id: str) -> JobSummary:
        """Fetch a job if it belongs to the supplied owner."""
        job = await self._repository.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise KeyError(f"Job {job_id} not found")
        return JobSummary(
            id=job.id,
            job_type=job.job_type,
            status=JobStatus(job.status),
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error=job.error,
            result=job.result,
        )


__all__ = ["JobService"]
