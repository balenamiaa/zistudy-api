from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Iterable

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from zistudy_api.db.models import StudyCard, StudySetCard
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.base import BaseSchema
from zistudy_api.domain.schemas.study_cards import (
    CardData,
    CardSearchRequest,
    StudyCardCreate,
    StudyCardUpdate,
)

HIDDEN_SEARCH_FIELDS = frozenset({"generator"})


def _serialize_card_data(data: CardData | dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, BaseSchema):
        return data.model_dump(mode="json")
    return data


def _strip_hidden_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_hidden_fields(item)
            for key, item in value.items()
            if key not in HIDDEN_SEARCH_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_hidden_fields(item) for item in value]
    return value


def _build_search_document(
    *, card_type: CardType | str | None, data: CardData | dict[str, Any]
) -> str:
    serialized = _serialize_card_data(data)
    sanitized = _strip_hidden_fields(serialized)
    type_value = (
        card_type.value
        if isinstance(card_type, CardType)
        else str(card_type)
        if card_type is not None
        else None
    )
    payload: dict[str, Any] = {"data": sanitized}
    if type_value:
        payload["card_type"] = type_value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _build_owner_filter(
    visible_owner_ids: Sequence[str | None] | None,
):
    if visible_owner_ids is None:
        return None
    include_null = any(owner_id is None for owner_id in visible_owner_ids)
    concrete_ids = [owner_id for owner_id in visible_owner_ids if owner_id is not None]
    owner_clauses = []
    if concrete_ids:
        owner_clauses.append(StudyCard.owner_id.in_(concrete_ids))
    if include_null:
        owner_clauses.append(StudyCard.owner_id.is_(None))
    if not owner_clauses:
        return false()
    return or_(*owner_clauses)


class StudyCardRepository:
    """Data access layer for study cards."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, payload: StudyCardCreate, *, owner_id: str | None) -> StudyCard:
        serialized_data = _serialize_card_data(payload.data)
        entity = StudyCard(
            card_type=payload.card_type,
            data=serialized_data,
            difficulty=payload.difficulty,
            owner_id=owner_id,
            search_document=_build_search_document(card_type=payload.card_type, data=payload.data),
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_id(self, card_id: int) -> StudyCard | None:
        stmt: Select[tuple[StudyCard]] = select(StudyCard).where(StudyCard.id == card_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, card_id: int, payload: StudyCardUpdate) -> StudyCard | None:
        entity = await self.get_by_id(card_id)
        if entity is None:
            return None

        if payload.data is not None:
            entity.data = _serialize_card_data(payload.data)
            entity.search_document = _build_search_document(
                card_type=entity.card_type,
                data=payload.data,
            )
        if payload.difficulty is not None:
            entity.difficulty = payload.difficulty
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, card_id: int) -> bool:
        entity = await self.get_by_id(card_id)
        if entity is None:
            return False
        await self._session.delete(entity)
        return True

    async def list_cards(
        self,
        card_type: CardType | None,
        page: int,
        page_size: int,
        *,
        visible_owner_ids: Sequence[str | None] | None,
    ) -> tuple[int, list[StudyCard]]:
        stmt: Select[tuple[StudyCard]] = select(StudyCard).order_by(StudyCard.created_at.desc())
        if card_type is not None:
            stmt = stmt.where(StudyCard.card_type == card_type.value)

        owner_filter = _build_owner_filter(visible_owner_ids)
        if owner_filter is not None:
            stmt = stmt.where(owner_filter)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(total_stmt) or 0

        stmt = stmt.options(selectinload(StudyCard.answers))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        return total, items

    async def get_many(self, card_ids: Sequence[int]) -> list[StudyCard]:
        if not card_ids:
            return []

        stmt: Select[tuple[StudyCard]] = select(StudyCard).where(StudyCard.id.in_(card_ids))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search_cards(
        self,
        request: CardSearchRequest,
        *,
        visible_owner_ids: Sequence[str | None] | None,
    ) -> tuple[int, list[StudyCard]]:
        stmt: Select[tuple[StudyCard]] = select(StudyCard)

        if request.query:
            like_term = f"%{request.query.strip()}%"
            stmt = stmt.where(StudyCard.search_document.ilike(like_term))

        filters = request.filters
        if filters.card_types:
            stmt = stmt.where(
                StudyCard.card_type.in_([card_type.value for card_type in filters.card_types])
            )

        if filters.min_difficulty is not None:
            stmt = stmt.where(StudyCard.difficulty >= filters.min_difficulty)
        if filters.max_difficulty is not None:
            stmt = stmt.where(StudyCard.difficulty <= filters.max_difficulty)

        if filters.study_set_ids:
            stmt = stmt.join(StudySetCard, StudySetCard.card_id == StudyCard.id).where(
                StudySetCard.study_set_id.in_(filters.study_set_ids)
            )

        owner_filter = _build_owner_filter(visible_owner_ids)
        if owner_filter is not None:
            stmt = stmt.where(owner_filter)

        stmt = stmt.order_by(StudyCard.created_at.desc()).distinct()

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(total_stmt) or 0

        stmt = stmt.options(selectinload(StudyCard.answers))
        stmt = stmt.offset((request.page - 1) * request.page_size).limit(request.page_size)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        return total, items

    async def list_not_in_set(
        self,
        *,
        study_set_id: int,
        card_type: CardType | None,
        page: int,
        page_size: int,
        visible_owner_ids: Sequence[str | None] | None,
    ) -> tuple[int, list[StudyCard]]:
        excluded_cards = select(StudySetCard.card_id).where(
            StudySetCard.study_set_id == study_set_id
        )

        stmt: Select[tuple[StudyCard]] = (
            select(StudyCard)
            .where(~StudyCard.id.in_(excluded_cards))
            .order_by(StudyCard.created_at.desc())
        )

        if card_type is not None:
            stmt = stmt.where(StudyCard.card_type == card_type.value)

        owner_filter = _build_owner_filter(visible_owner_ids)
        if owner_filter is not None:
            stmt = stmt.where(owner_filter)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(total_stmt) or 0

        stmt = stmt.options(selectinload(StudyCard.answers))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        return total, items

    async def import_cards(
        self,
        cards: Iterable[StudyCardCreate],
        *,
        owner_id: str | None,
    ) -> list[StudyCard]:
        payload = list(cards)
        if not payload:
            return []

        entities = [
            StudyCard(
                card_type=item.card_type,
                data=_serialize_card_data(item.data),
                difficulty=item.difficulty,
                owner_id=owner_id,
                search_document=_build_search_document(card_type=item.card_type, data=item.data),
            )
            for item in payload
        ]
        self._session.add_all(entities)
        await self._session.flush()
        for entity in entities:
            await self._session.refresh(entity)
        return entities


__all__ = ["StudyCardRepository"]
