from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from zistudy_api.api.dependencies import (
    get_current_session_user,
    get_optional_session_user,
    get_study_card_service,
)
from zistudy_api.config.settings import get_settings
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.study_cards import (
    CardSearchRequest,
    PaginatedStudyCardResults,
    StudyCardCollection,
    StudyCardCreate,
    StudyCardImportPayload,
    StudyCardRead,
    StudyCardUpdate,
)
from zistudy_api.services.study_cards import StudyCardService

router = APIRouter(prefix="/study-cards", tags=["Study Cards"])


MAX_PAGE_SIZE = get_settings().max_page_size


StudyCardServiceDependency = Annotated[StudyCardService, Depends(get_study_card_service)]
CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]
OptionalUserDependency = Annotated[SessionUser | None, Depends(get_optional_session_user)]


@router.post("", response_model=StudyCardRead, status_code=status.HTTP_201_CREATED)
async def create_study_card(
    payload: StudyCardCreate,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> StudyCardRead:
    """Create a study card and return the stored representation."""
    return await service.create_card(payload, owner=user)


@router.get("/{card_id}", response_model=StudyCardRead)
async def get_study_card(
    card_id: int,
    service: StudyCardServiceDependency,
    session_user: OptionalUserDependency,
) -> StudyCardRead:
    """Fetch a study card by identifier."""
    try:
        return await service.get_card(card_id, requester=session_user)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.put("/{card_id}", response_model=StudyCardRead)
async def update_study_card(
    card_id: int,
    payload: StudyCardUpdate,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> StudyCardRead:
    """Apply updates to a study card and return the refreshed payload."""
    try:
        return await service.update_card(card_id, payload, requester=user)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_study_card(
    card_id: int,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> None:
    """Remove a study card from the catalog."""
    try:
        await service.delete_card(card_id, requester=user)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("", response_model=StudyCardCollection)
async def list_study_cards(
    service: StudyCardServiceDependency,
    session_user: OptionalUserDependency,
    card_type: CardType | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> StudyCardCollection:
    """List study cards with optional filtering by type."""
    return await service.list_cards(
        card_type=card_type,
        page=page,
        page_size=page_size,
        requester=session_user,
    )


@router.post("/search", response_model=PaginatedStudyCardResults)
async def search_study_cards(
    payload: CardSearchRequest,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> PaginatedStudyCardResults:
    """Search study cards using the provided query filters."""
    return await service.search_cards(payload, requester=user)


@router.get("/not-in-set/{study_set_id}", response_model=StudyCardCollection)
async def cards_not_in_set(
    study_set_id: int,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
    card_type: CardType | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> StudyCardCollection:
    """Return cards not yet associated with the specified study set."""
    return await service.list_cards_not_in_set(
        study_set_id=study_set_id,
        card_type=card_type,
        page=page,
        page_size=page_size,
        requester=user,
    )


@router.post("/import", response_model=list[StudyCardRead], status_code=status.HTTP_201_CREATED)
async def import_study_cards(
    payload: StudyCardImportPayload,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> list[StudyCardRead]:
    """Bulk import typed study cards."""
    return await service.import_card_batch(payload, owner=user)


@router.post(
    "/import/json", response_model=list[StudyCardRead], status_code=status.HTTP_201_CREATED
)
async def import_study_cards_json(
    request: Request,
    service: StudyCardServiceDependency,
    user: CurrentUserDependency,
) -> list[StudyCardRead]:
    """Bulk import cards from a raw JSON payload."""
    raw_body = await request.body()
    try:
        return await service.import_cards_from_json(raw_body.decode("utf-8"), owner=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
