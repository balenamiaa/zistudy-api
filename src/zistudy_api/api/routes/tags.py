from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from zistudy_api.api.dependencies import get_current_session_user, get_tag_service
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.tags import TagCreate, TagRead, TagSearchResponse, TagUsage
from zistudy_api.services.tags import TagService

router = APIRouter(prefix="/tags", tags=["Tags"])


TagServiceDependency = Annotated[TagService, Depends(get_tag_service)]
CurrentUserDependency = Annotated[SessionUser, Depends(get_current_session_user)]
NamesQuery = Annotated[list[str] | None, Query()]
SearchQuery = Annotated[str, Query(min_length=1, max_length=64)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
PopularLimitQuery = Annotated[int, Query(ge=1, le=50)]


@router.get("", response_model=list[TagRead])
async def list_tags(
    service: TagServiceDependency,
    names: NamesQuery = None,
) -> list[TagRead]:
    """Return tags, optionally filtering to a provided name list."""
    return await service.list_tags(names)


@router.post("", response_model=list[TagRead], status_code=status.HTTP_201_CREATED)
async def create_tags(
    payload: list[TagCreate],
    service: TagServiceDependency,
    _: CurrentUserDependency,
) -> list[TagRead]:
    """Ensure the supplied tag names exist and return their canonical form."""
    tag_names = [tag.name for tag in payload]
    return await service.ensure_tags(tag_names, commit=True)


@router.get("/search", response_model=TagSearchResponse)
async def search_tags(
    service: TagServiceDependency,
    query: SearchQuery,
    limit: LimitQuery = 20,
) -> TagSearchResponse:
    """Search tags by prefix or substring and return a bounded result set."""
    total, tags = await service.search_tags(query, limit)
    return TagSearchResponse(items=tags, total=total)


@router.get("/popular", response_model=list[TagUsage])
async def popular_tags(
    service: TagServiceDependency,
    limit: PopularLimitQuery = 10,
) -> list[TagUsage]:
    """Return the most frequently used tags."""
    return await service.popular_tags(limit)
