from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import Answer
from zistudy_api.db.repositories.answers import AnswerRepository
from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.domain.schemas.answers import (
    AnswerCreate,
    AnswerHistory,
    AnswerRead,
    AnswerStats,
    StudySetProgress,
    canonical_answer_type,
    parse_answer_data,
)


class AnswerService:
    """Business logic for recording and analysing answers."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._answers = AnswerRepository(session)
        self._cards = StudyCardRepository(session)

    async def submit_answer(self, *, user_id: str, payload: AnswerCreate) -> AnswerRead:
        """Persist an answer for a study card and return the typed read model."""
        card = await self._cards.get_by_id(payload.study_card_id)
        if card is None:
            raise KeyError(f"Study card {payload.study_card_id} not found")

        entity = await self._answers.create(user_id=user_id, payload=payload)
        await self._session.commit()
        return self._to_read_model(entity)

    async def get_answer(self, answer_id: int, *, user_id: str) -> AnswerRead:
        """Fetch a specific answer belonging to the requesting user."""
        entity = await self._answers.get_by_id(answer_id)
        if entity is None or entity.user_id != user_id:
            raise KeyError("Answer not found")
        return self._to_read_model(entity)

    async def list_history(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
    ) -> AnswerHistory:
        """Return a paginated history of answers for the requesting user."""
        total, items = await self._answers.list_for_user(
            user_id=user_id,
            page=page,
            page_size=page_size,
        )
        return AnswerHistory(
            items=[self._to_read_model(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def stats_for_card(
        self, *, study_card_id: int, user_id: str | None = None
    ) -> AnswerStats:
        """Compute aggregate accuracy metrics for a study card."""
        total, correct = await self._answers.stats_for_card(
            study_card_id=study_card_id, user_id=user_id
        )
        accuracy = (correct / total) if total else 0.0
        return AnswerStats(
            study_card_id=study_card_id,
            attempts=total,
            correct=correct,
            accuracy=accuracy,
        )

    async def study_set_progress(
        self,
        *,
        user_id: str,
        study_set_ids: list[int],
    ) -> list[StudySetProgress]:
        """Summarise answer progress for the requested study sets."""
        aggregates = await self._answers.per_set_progress(
            user_id=user_id, study_set_ids=study_set_ids
        )
        progress: list[StudySetProgress] = []
        for set_id, total_cards, attempted, correct, last_answered in aggregates:
            accuracy = (correct / attempted) if attempted else 0.0
            progress.append(
                StudySetProgress(
                    study_set_id=set_id,
                    total_cards=total_cards,
                    attempted_cards=attempted,
                    correct_cards=correct,
                    accuracy=accuracy,
                    last_answered_at=last_answered,
                )
            )
        return progress

    def _to_read_model(self, entity: Answer) -> AnswerRead:
        """Convert a persisted answer entity into its typed API representation."""
        payload = entity.data if isinstance(entity.data, dict) else {}
        expected = payload.get("expected") if isinstance(payload, dict) else None
        notes = payload.get("evaluation_notes") if isinstance(payload, dict) else None
        latency = payload.get("latency_ms") if isinstance(payload, dict) else None
        answer_data = parse_answer_data(entity.answer_type, payload)
        answer_type = canonical_answer_type(entity.answer_type, answer_data)
        return AnswerRead(
            id=entity.id,
            user_id=entity.user_id,
            study_card_id=entity.study_card_id,
            answer_type=answer_type,
            data=answer_data,
            expected_answer=expected if isinstance(expected, dict) else None,
            evaluation_notes=notes if isinstance(notes, str) else None,
            is_correct=self._is_correct(entity.is_correct),
            latency_ms=int(latency) if isinstance(latency, (int, float)) else None,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _is_correct(value: int | None) -> bool | None:
        if value is None:
            return None
        if value == 2:
            return None
        return value == 1


__all__ = ["AnswerService"]
