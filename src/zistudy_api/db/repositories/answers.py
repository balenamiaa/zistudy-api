from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import Answer, StudySetCard
from zistudy_api.domain.schemas.answers import AnswerCreate, serialize_answer_data


class AnswerRepository:
    """Data access helper for answer persistence and analytics."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, *, user_id: str, payload: AnswerCreate) -> Answer:
        data_payload = serialize_answer_data(payload.data)
        entity = Answer(
            user_id=user_id,
            study_card_id=payload.study_card_id,
            data=data_payload,
            answer_type=payload.answer_type,
            is_correct=int(payload.is_correct) if payload.is_correct is not None else 2,
        )
        if payload.expected_answer is not None:
            entity.data.setdefault("expected", payload.expected_answer)
        if payload.evaluation_notes is not None:
            entity.data.setdefault("evaluation_notes", payload.evaluation_notes)
        if payload.latency_ms is not None:
            entity.data.setdefault("latency_ms", payload.latency_ms)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_id(self, answer_id: int) -> Answer | None:
        stmt: Select[tuple[Answer]] = select(Answer).where(Answer.id == answer_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
    ) -> tuple[int, list[Answer]]:
        stmt: Select[tuple[Answer]] = (
            select(Answer).where(Answer.user_id == user_id).order_by(Answer.created_at.desc())
        )

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self._session.scalar(total_stmt) or 0

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        return total, items

    async def stats_for_card(
        self, *, study_card_id: int, user_id: str | None = None
    ) -> tuple[int, int]:
        stmt = select(
            func.count(),
            func.sum(case((Answer.is_correct == 1, 1), else_=0)),
        ).where(Answer.study_card_id == study_card_id)
        if user_id is not None:
            stmt = stmt.where(Answer.user_id == user_id)
        result = await self._session.execute(stmt)
        total, correct = result.one()
        return int(total or 0), int(correct or 0)

    async def per_set_progress(
        self, *, user_id: str, study_set_ids: Sequence[int]
    ) -> list[tuple[int, int, int, int, datetime | None]]:
        if not study_set_ids:
            return []

        answers_subq = (
            select(
                Answer.study_card_id.label("card_id"),
                func.max(Answer.created_at).label("last_answered"),
                func.max(Answer.is_correct == 1).label("was_correct"),
                func.count(Answer.id).label("attempts"),
            )
            .where(Answer.user_id == user_id)
            .group_by(Answer.study_card_id)
            .subquery()
        )

        stmt = (
            select(
                StudySetCard.study_set_id,
                func.count(StudySetCard.card_id).label("total_cards"),
                func.count(answers_subq.c.card_id).label("attempted"),
                func.sum(case((answers_subq.c.was_correct.is_(True), 1), else_=0)).label("correct"),
                func.max(answers_subq.c.last_answered).label("last_answered"),
            )
            .outerjoin(answers_subq, answers_subq.c.card_id == StudySetCard.card_id)
            .where(StudySetCard.study_set_id.in_(study_set_ids))
            .group_by(StudySetCard.study_set_id)
        )

        result = await self._session.execute(stmt)
        rows = result.all()
        progress: list[tuple[int, int, int, int, datetime | None]] = []
        for row in rows:
            study_set_id, total_cards, attempted, correct, last_answered = row
            progress.append(
                (
                    int(study_set_id),
                    int(total_cards or 0),
                    int(attempted or 0),
                    int(correct or 0),
                    last_answered,
                )
            )
        return progress


__all__ = ["AnswerRepository"]
