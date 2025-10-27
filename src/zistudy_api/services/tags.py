from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.repositories.tags import TagRepository
from zistudy_api.domain.schemas.tags import TagRead, TagUsage


class TagService:
    """Expose tag operations."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repository = TagRepository(session)

    async def ensure_tags(self, tag_names: list[str], *, commit: bool = False) -> list[TagRead]:
        """Create tags that do not yet exist and return the canonical set."""
        tags = await self._repository.ensure_tags(tag_names)
        if commit:
            await self._session.commit()
        return [TagRead.model_validate(tag) for tag in tags]

    async def list_tags(self, tag_names: list[str] | None = None) -> list[TagRead]:
        """List tags, optionally filtering by specific names."""
        tags = (
            await self._repository.list_all()
            if tag_names is None
            else await self._repository.list_by_names(tag_names)
        )
        return [TagRead.model_validate(tag) for tag in tags]

    async def search_tags(self, query: str, limit: int = 20) -> tuple[int, list[TagRead]]:
        """Search tags by query and return total hits plus the current page of tags."""
        total, tags = await self._repository.search(query=query, limit=limit)
        return total, [TagRead.model_validate(tag) for tag in tags]

    async def popular_tags(self, limit: int = 10) -> list[TagUsage]:
        """Return the most popular tags ranked by usage count."""
        rows = await self._repository.popular(limit=limit)
        return [TagUsage(tag=TagRead.model_validate(tag), usage_count=usage) for tag, usage in rows]


__all__ = ["TagService"]
