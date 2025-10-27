from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import AsyncJob


class JobRepository:
    """Persistence layer for tracking async jobs."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        job_type: str,
        owner_id: str,
        payload: dict,
        status: str = "pending",
    ) -> AsyncJob:
        entity = AsyncJob(
            job_type=job_type,
            owner_id=owner_id,
            payload=payload,
            status=status,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get(self, job_id: int) -> AsyncJob | None:
        stmt: Select[tuple[AsyncJob]] = select(AsyncJob).where(AsyncJob.id == job_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_owner(self, owner_id: str) -> list[AsyncJob]:
        stmt: Select[tuple[AsyncJob]] = (
            select(AsyncJob)
            .where(AsyncJob.owner_id == owner_id)
            .order_by(AsyncJob.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_status(
        self,
        job_id: int,
        *,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, datetime | str | None] = {
            "status": status,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if error is not None:
            values["error"] = error
        await self._session.execute(update(AsyncJob).where(AsyncJob.id == job_id).values(**values))

    async def set_result(self, job_id: int, result: dict) -> None:
        await self._session.execute(
            update(AsyncJob)
            .where(AsyncJob.id == job_id)
            .values(result=result, updated_at=datetime.now(tz=timezone.utc))
        )


__all__ = ["JobRepository"]
