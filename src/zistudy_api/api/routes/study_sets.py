from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from zistudy_api.api.dependencies import (
    JobServiceDependency,
    get_current_session_user,
    get_optional_session_user,
    get_study_set_service,
)
from zistudy_api.config.settings import get_settings
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.jobs import JobSummary
from zistudy_api.domain.schemas.study_sets import (
    AddCardsToSet,
    BulkAddToSets,
    BulkDeleteStudySets,
    BulkOperationResult,
    CloneStudySetsRequest,
    ExportStudySetsRequest,
    PaginatedStudySets,
    RemoveCardsFromSet,
    StudySetCardsPage,
    StudySetCreate,
    StudySetForCard,
    StudySetUpdate,
    StudySetWithMeta,
)
from zistudy_api.services.job_processors import process_clone_job, process_export_job
from zistudy_api.services.study_sets import StudySetService

router = APIRouter(prefix="/study-sets", tags=["Study Sets"])


StudySetServiceDependency = Annotated[StudySetService, Depends(get_study_set_service)]
CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]
OptionalUserDependency = Annotated[SessionUser | None, Depends(get_optional_session_user)]


@router.post(
    "",
    response_model=StudySetWithMeta,
    status_code=status.HTTP_201_CREATED,
)
async def create_study_set(
    payload: StudySetCreate,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> StudySetWithMeta:
    """Create a study set owned by the authenticated user."""
    return await service.create_study_set(payload, user.id)


@router.get(
    "/{study_set_id}",
    response_model=StudySetWithMeta,
)
async def get_study_set(
    study_set_id: int,
    service: StudySetServiceDependency,
) -> StudySetWithMeta:
    """Retrieve a study set including metadata such as tags and ownership."""
    try:
        return await service.get_study_set(study_set_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/{study_set_id}",
    response_model=StudySetWithMeta,
)
async def update_study_set(
    study_set_id: int,
    payload: StudySetUpdate,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> StudySetWithMeta:
    """Update study set metadata after confirming the caller has modify rights."""
    try:
        if not await service.can_modify(study_set_id, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return await service.update_study_set(study_set_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{study_set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_study_set(
    study_set_id: int,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> None:
    """Delete a study set owned or managed by the current user."""
    try:
        if not await service.can_modify(study_set_id, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        await service.delete_study_set(study_set_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=PaginatedStudySets)
async def list_study_sets(
    service: StudySetServiceDependency,
    session_user: OptionalUserDependency,
    show_only_owned: bool = False,
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PaginatedStudySets:
    """List study sets visible to the caller with optional filters."""
    user_id = session_user.id if session_user else None
    total, items = await service.list_accessible_study_sets(
        user_id=user_id,
        show_only_owned=show_only_owned,
        search_query=search,
        page=page,
        page_size=page_size,
    )
    return PaginatedStudySets(items=items, total=total, page=page, page_size=page_size)


@router.post(
    "/add-cards",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_cards_to_set(
    payload: AddCardsToSet,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> None:
    """Append cards to a study set after verifying modify permissions."""
    try:
        if not await service.can_modify(payload.study_set_id, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        await service.add_cards(payload, requester=user)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post(
    "/remove-cards",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_cards_from_set(
    payload: RemoveCardsFromSet,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> None:
    """Remove cards from a study set when the caller has modify rights."""
    try:
        if not await service.can_modify(payload.study_set_id, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        await service.remove_cards(
            study_set_id=payload.study_set_id,
            card_ids=payload.card_ids,
            card_type=payload.card_type,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{study_set_id}/can-access", response_model=dict[str, bool])
async def can_access_study_set(
    study_set_id: int,
    service: StudySetServiceDependency,
    session_user: OptionalUserDependency,
) -> dict[str, bool]:
    """Return booleans indicating whether the caller can access or modify the set."""
    user_id = session_user.id if session_user else None
    try:
        entity = await service.get_study_set(study_set_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    can_access = entity.study_set.can_access(user_id)
    can_modify = await service.can_modify(study_set_id, user_id)
    return {"can_access": can_access, "can_modify": can_modify}


@router.get(
    "/{study_set_id}/cards",
    response_model=StudySetCardsPage,
)
async def list_cards_in_study_set(
    study_set_id: int,
    service: StudySetServiceDependency,
    card_type: CardType | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> StudySetCardsPage:
    """List cards that belong to a study set with optional filtering."""
    try:
        page_data = await service.list_cards_in_set(
            study_set_id=study_set_id,
            card_type=card_type,
            page=page,
            page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return page_data


@router.post("/clone", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
async def clone_study_sets_endpoint(
    payload: CloneStudySetsRequest,
    service: StudySetServiceDependency,
    job_service: JobServiceDependency,
    user: CurrentUserDependency,
) -> JobSummary:
    """Enqueue an asynchronous clone job for the selected study sets."""
    for study_set_id in payload.study_set_ids:
        meta = await service.get_study_set(study_set_id)
        if not meta.study_set.can_access(user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    summary = await job_service.enqueue(
        job_type="study_set_clone",
        owner_id=user.id,
        payload={
            "study_set_ids": payload.study_set_ids,
            "title_prefix": payload.title_prefix,
            "owner_id": user.id,
        },
        processor_task=process_clone_job,
    )
    return summary


@router.post("/export", response_model=JobSummary, status_code=status.HTTP_202_ACCEPTED)
async def export_study_sets_endpoint(
    payload: ExportStudySetsRequest,
    service: StudySetServiceDependency,
    job_service: JobServiceDependency,
    user: CurrentUserDependency,
) -> JobSummary:
    """Enqueue an asynchronous export job for the selected study sets."""
    for study_set_id in payload.study_set_ids:
        meta = await service.get_study_set(study_set_id)
        if not meta.study_set.can_access(user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    summary = await job_service.enqueue(
        job_type="study_set_export",
        owner_id=user.id,
        payload={
            "study_set_ids": payload.study_set_ids,
            "owner_id": user.id,
        },
        processor_task=process_export_job,
    )
    return summary


@router.post(
    "/bulk-add",
    response_model=BulkOperationResult,
)
async def bulk_add_cards_to_study_sets(
    payload: BulkAddToSets,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> BulkOperationResult:
    """Add cards to multiple study sets in one request, reporting failures."""
    # Ensure user can modify each set before attempting bulk operation
    forbidden: list[int] = []
    permitted_ids: list[int] = []
    for set_id in payload.study_set_ids:
        try:
            if not await service.can_modify(set_id, user.id):
                forbidden.append(set_id)
            else:
                permitted_ids.append(set_id)
        except KeyError:
            forbidden.append(set_id)

    if not permitted_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    filtered_payload = BulkAddToSets(
        study_set_ids=permitted_ids,
        card_ids=payload.card_ids,
        card_type=payload.card_type,
    )
    result = await service.bulk_add_cards(filtered_payload, requester=user)
    if forbidden:
        augmented_errors = [
            *result.errors,
            *[f"Set {set_id}: Forbidden" for set_id in forbidden],
        ]
        result = result.model_copy(
            update={
                "errors": augmented_errors,
                "error_count": result.error_count + len(forbidden),
            }
        )
    return result


@router.post(
    "/bulk-delete",
    response_model=BulkOperationResult,
)
async def bulk_delete_study_sets(
    payload: BulkDeleteStudySets,
    service: StudySetServiceDependency,
    user: CurrentUserDependency,
) -> BulkOperationResult:
    """Delete multiple study sets owned by the caller, aggregating errors."""
    result = await service.bulk_delete_study_sets(
        study_set_ids=payload.study_set_ids,
        user_id=user.id,
    )
    if result.success_count == 0 and result.error_count > 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.errors)
    return result


@router.get(
    "/for-card/{card_id}",
    response_model=list[StudySetForCard],
)
async def study_sets_for_card(
    card_id: int,
    service: StudySetServiceDependency,
    session_user: OptionalUserDependency,
) -> list[StudySetForCard]:
    """List study sets containing a specific card, filtered by caller access."""
    user_id = session_user.id if session_user else None
    sets = await service.get_study_sets_for_card(card_id=card_id, user_id=user_id)
    return sets


MAX_PAGE_SIZE = get_settings().max_page_size
