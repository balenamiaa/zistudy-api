from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from zistudy_api.api.dependencies import AsyncSessionDependency, get_current_session_user
from zistudy_api.config.settings import get_settings
from zistudy_api.domain.schemas.answers import (
    AnswerCreate,
    AnswerHistory,
    AnswerRead,
    AnswerStats,
    StudySetProgress,
)
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.services.answers import AnswerService

router = APIRouter(prefix="/answers", tags=["Answers"])


def get_answer_service(session: AsyncSessionDependency) -> AnswerService:
    return AnswerService(session)


AnswerServiceDependency = Annotated[AnswerService, Depends(get_answer_service)]
CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]

MAX_PAGE_SIZE = get_settings().max_page_size


@router.get("/history", response_model=AnswerHistory)
async def answer_history(
    current_user: CurrentUserDependency,
    service: AnswerServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> AnswerHistory:
    """Return a paginated timeline of answers submitted by the current user."""
    return await service.list_history(user_id=current_user.id, page=page, page_size=page_size)


@router.get("/cards/{study_card_id}/stats", response_model=AnswerStats)
async def card_stats(
    study_card_id: int,
    current_user: CurrentUserDependency,
    service: AnswerServiceDependency,
) -> AnswerStats:
    """Summarise accuracy metrics for a single study card."""
    try:
        return await service.stats_for_card(study_card_id=study_card_id, user_id=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/study-sets/progress", response_model=list[StudySetProgress])
async def study_set_progress(
    study_set_ids: Annotated[list[int], Query()],
    current_user: CurrentUserDependency,
    service: AnswerServiceDependency,
) -> list[StudySetProgress]:
    """Report aggregated progress metrics across the requested study sets."""
    return await service.study_set_progress(user_id=current_user.id, study_set_ids=study_set_ids)


@router.post("", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
async def submit_answer(
    payload: AnswerCreate,
    current_user: CurrentUserDependency,
    service: AnswerServiceDependency,
) -> AnswerRead:
    """Persist a learner's answer and return the typed read model."""
    try:
        return await service.submit_answer(user_id=current_user.id, payload=payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/{answer_id}", response_model=AnswerRead)
async def get_answer(
    answer_id: int,
    current_user: CurrentUserDependency,
    service: AnswerServiceDependency,
) -> AnswerRead:
    """Retrieve a single answer owned by the current user."""
    try:
        return await service.get_answer(answer_id, user_id=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


__all__ = ["router"]
