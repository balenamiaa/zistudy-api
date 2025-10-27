from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from zistudy_api.api.dependencies import AsyncSessionDependency, get_current_session_user
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.jobs import JobSummary
from zistudy_api.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])

CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]


@router.get("/{job_id}", response_model=JobSummary)
async def get_job(
    job_id: int,
    current_user: CurrentUserDependency,
    session: AsyncSessionDependency,
) -> JobSummary:
    """Fetch a job owned by the current user, raising 404 when missing."""
    service = JobService(session)
    try:
        return await service.get_job(job_id, owner_id=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


__all__ = ["router"]
