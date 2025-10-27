from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import StudySetTag, Tag


class TagRepository:
    """Repository providing CRUD operations for tags."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_names(self, names: Iterable[str]) -> list[Tag]:
        normalized = {name.strip() for name in names if name.strip()}
        if not normalized:
            return []

        stmt: Select[tuple[Tag]] = select(Tag).where(Tag.name.in_(normalized))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Tag]:
        stmt: Select[tuple[Tag]] = select(Tag).order_by(Tag.name.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def ensure_tags(self, names: Iterable[str]) -> list[Tag]:
        normalized = [name.strip() for name in names if name.strip()]
        if not normalized:
            return []

        existing = await self.list_by_names(normalized)
        existing_map = {tag.name: tag for tag in existing}

        ordered: list[Tag] = []
        created: dict[str, Tag] = {}

        for name in normalized:
            if name in existing_map:
                ordered.append(existing_map[name])
                continue

            tag = Tag(name=name)
            self._session.add(tag)
            created[name] = tag
            ordered.append(tag)

        if created:
            await self._session.flush()
            for tag in created.values():
                await self._session.refresh(tag)

        return ordered

    async def search(self, query: str, limit: int = 20) -> tuple[int, list[Tag]]:
        pattern = f"%{query.strip()}%"
        stmt = select(Tag).where(Tag.name.ilike(pattern)).order_by(Tag.name.asc())
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(count_stmt) or 0
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return total, list(result.scalars().all())

    async def popular(self, limit: int = 10) -> list[tuple[Tag, int]]:
        stmt = (
            select(Tag, func.count(StudySetTag.study_set_id).label("usage"))
            .join(StudySetTag, StudySetTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(func.count(StudySetTag.study_set_id).desc(), Tag.name.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row[0], int(row[1])) for row in rows]


__all__ = ["TagRepository"]
