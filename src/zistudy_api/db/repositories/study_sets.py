from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from zistudy_api.db.models import StudyCard, StudySet, StudySetCard, StudySetTag, Tag
from zistudy_api.domain.enums import CardCategory, CardType
from zistudy_api.domain.schemas.study_sets import StudySetCreate, StudySetUpdate


class StudySetRepository:
    """Data access operations for study sets."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, payload: StudySetCreate, owner_id: str | None) -> StudySet:
        entity = StudySet(
            title=payload.title,
            description=payload.description,
            is_private=payload.is_private,
            owner_id=owner_id,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_id(self, study_set_id: int) -> StudySet | None:
        stmt: Select[tuple[StudySet]] = (
            select(StudySet)
            .options(
                selectinload(StudySet.tags).joinedload(StudySetTag.tag),
                selectinload(StudySet.cards),
                selectinload(StudySet.owner),
            )
            .where(StudySet.id == study_set_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def attach_tags(self, entity: StudySet, tags: Sequence[Tag]) -> None:
        await self._session.execute(
            select(StudySetTag).where(StudySetTag.study_set_id == entity.id)
        )
        await self._session.refresh(entity, attribute_names=["tags"])
        entity.tags.clear()
        for tag in tags:
            entity.tags.append(StudySetTag(tag=tag))
        await self._session.flush()

    async def update(self, entity: StudySet, payload: StudySetUpdate) -> StudySet:
        if payload.title is not None:
            entity.title = payload.title
        if payload.description is not None:
            entity.description = payload.description
        if payload.is_private is not None:
            entity.is_private = payload.is_private
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity: StudySet) -> None:
        await self._session.delete(entity)

    async def list_accessible(
        self,
        *,
        current_user: str | None,
        show_only_owned: bool,
        search_query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[StudySet]]:
        stmt: Select[tuple[StudySet]] = (
            select(StudySet)
            .options(
                selectinload(StudySet.tags).joinedload(StudySetTag.tag),
                selectinload(StudySet.owner),
            )
            .order_by(StudySet.created_at.desc())
        )

        if show_only_owned and current_user:
            stmt = stmt.where(StudySet.owner_id == current_user)
        elif current_user:
            stmt = stmt.where(
                (StudySet.is_private.is_(False))
                | (StudySet.owner_id == current_user)
                | (StudySet.owner_id.is_(None))
            )
        else:
            stmt = stmt.where(StudySet.is_private.is_(False))

        if search_query:
            like_term = f"%{search_query.strip()}%"
            stmt = stmt.where(
                (StudySet.title.ilike(like_term)) | (StudySet.description.ilike(like_term))
            )

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(total_stmt)
        total = total or 0

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        return total, items

    async def get_card_counts(self, study_set_id: int) -> dict[str, int]:
        stmt_total = (
            select(func.count())
            .select_from(StudySetCard)
            .where(StudySetCard.study_set_id == study_set_id)
        )
        total = await self._session.scalar(stmt_total) or 0

        stmt_questions = (
            select(func.count())
            .select_from(StudySetCard)
            .where(
                StudySetCard.study_set_id == study_set_id,
                StudySetCard.card_category == CardCategory.QUESTION,
            )
        )
        question_count = await self._session.scalar(stmt_questions) or 0

        return {"total": total, "questions": question_count}

    async def add_cards(
        self,
        *,
        study_set_id: int,
        card_ids: Sequence[int],
        card_category: CardCategory,
    ) -> int:
        if not card_ids:
            return 0

        existing_stmt: Select[tuple[int]] = select(StudySetCard.card_id).where(
            StudySetCard.study_set_id == study_set_id,
            StudySetCard.card_category == card_category,
            StudySetCard.card_id.in_(card_ids),
        )
        existing_result = await self._session.execute(existing_stmt)
        existing_ids = set(existing_result.scalars().all())

        filtered_ids = [card_id for card_id in card_ids if card_id not in existing_ids]
        if not filtered_ids:
            return 0

        max_position_stmt = select(func.coalesce(func.max(StudySetCard.position), 0)).where(
            StudySetCard.study_set_id == study_set_id,
            StudySetCard.card_category == card_category,
        )
        start_position = await self._session.scalar(max_position_stmt) or 0

        for index, card_id in enumerate(filtered_ids, start=1):
            self._session.add(
                StudySetCard(
                    study_set_id=study_set_id,
                    card_id=card_id,
                    card_category=card_category,
                    position=start_position + index,
                )
            )

        return len(filtered_ids)

    async def remove_cards(
        self,
        *,
        study_set_id: int,
        card_ids: Sequence[int],
        card_category: CardCategory,
    ) -> int:
        if not card_ids:
            return 0

        delete_stmt = (
            select(StudySetCard)
            .where(
                StudySetCard.study_set_id == study_set_id,
                StudySetCard.card_category == card_category,
                StudySetCard.card_id.in_(card_ids),
            )
            .with_for_update()
        )

        result = await self._session.execute(delete_stmt)
        records = list(result.scalars().all())
        for record in records:
            await self._session.delete(record)

        return len(records)

    async def list_cards(
        self,
        *,
        study_set_id: int,
        card_type: CardType | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[tuple[StudyCard, int]]]:
        count_stmt = (
            select(func.count())
            .select_from(StudySetCard)
            .join(StudyCard, StudySetCard.card_id == StudyCard.id)
            .where(StudySetCard.study_set_id == study_set_id)
        )

        data_stmt = (
            select(StudyCard, StudySetCard.position)
            .select_from(StudySetCard)
            .join(StudyCard, StudySetCard.card_id == StudyCard.id)
            .where(StudySetCard.study_set_id == study_set_id)
            .order_by(StudySetCard.position.asc(), StudyCard.id.asc())
        )

        if card_type is not None:
            count_stmt = count_stmt.where(StudyCard.card_type == card_type.value)
            data_stmt = data_stmt.where(StudyCard.card_type == card_type.value)

        total = await self._session.scalar(count_stmt)
        total = total or 0

        data_stmt = data_stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(data_stmt)
        rows = result.all()
        items = [(row[0], row[1]) for row in rows]
        return total, items

    async def list_for_card(self, card_id: int) -> list[StudySet]:
        stmt = (
            select(StudySet)
            .join(StudySetCard, StudySetCard.study_set_id == StudySet.id)
            .options(
                selectinload(StudySet.tags).joinedload(StudySetTag.tag),
                selectinload(StudySet.owner),
            )
            .where(StudySetCard.card_id == card_id)
            .order_by(StudySet.title.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_cards_with_details(
        self, study_set_id: int
    ) -> list[tuple[StudySetCard, StudyCard]]:
        stmt: Select[tuple[StudySetCard, StudyCard]] = (
            select(StudySetCard, StudyCard)
            .join(StudyCard, StudyCard.id == StudySetCard.card_id)
            .where(StudySetCard.study_set_id == study_set_id)
            .order_by(StudySetCard.position.asc())
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row[0], row[1]) for row in rows]


__all__ = ["StudySetRepository"]
