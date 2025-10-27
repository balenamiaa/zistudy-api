from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.study_cards import (
    CardSearchRequest,
    CardSearchResult,
    PaginatedStudyCardResults,
    StudyCardCollection,
    StudyCardCreate,
    StudyCardImportPayload,
    StudyCardRead,
    StudyCardUpdate,
)


class StudyCardService:
    """Business logic for study card operations."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repository = StudyCardRepository(session)

    async def create_card(self, payload: StudyCardCreate) -> StudyCardRead:
        """Create a study card and return the typed read model."""
        entity = await self._repository.create(payload)
        await self._session.commit()
        return StudyCardRead.model_validate(entity)

    async def get_card(self, card_id: int) -> StudyCardRead:
        """Retrieve a single study card by identifier."""
        entity = await self._repository.get_by_id(card_id)
        if entity is None:
            raise KeyError(f"Study card {card_id} not found")
        return StudyCardRead.model_validate(entity)

    async def update_card(self, card_id: int, payload: StudyCardUpdate) -> StudyCardRead:
        """Apply updates to a study card and return the refreshed read model."""
        entity = await self._repository.update(card_id, payload)
        if entity is None:
            raise KeyError(f"Study card {card_id} not found")
        await self._session.commit()
        return StudyCardRead.model_validate(entity)

    async def delete_card(self, card_id: int) -> None:
        """Delete a study card by identifier."""
        deleted = await self._repository.delete(card_id)
        if not deleted:
            raise KeyError(f"Study card {card_id} not found")
        await self._session.commit()

    async def list_cards(
        self,
        *,
        card_type: CardType | None,
        page: int,
        page_size: int,
    ) -> StudyCardCollection:
        """Return a paginated collection of study cards filtered by type."""
        total, entities = await self._repository.list_cards(
            card_type=card_type, page=page, page_size=page_size
        )
        cards = [StudyCardRead.model_validate(entity) for entity in entities]
        return StudyCardCollection(
            items=cards,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def search_cards(self, request: CardSearchRequest) -> PaginatedStudyCardResults:
        """Search study cards and include relevance metadata when available."""
        total, entities = await self._repository.search_cards(request)
        results = [
            CardSearchResult(
                card=StudyCardRead.model_validate(entity),
                score=None,
                snippet=None,
            )
            for entity in entities
        ]
        return PaginatedStudyCardResults(
            items=results,
            total=total,
            page=request.page,
            page_size=request.page_size,
        )

    async def list_cards_not_in_set(
        self,
        *,
        study_set_id: int,
        card_type: CardType | None,
        page: int,
        page_size: int,
    ) -> StudyCardCollection:
        """List cards not currently associated with the specified study set."""
        total, entities = await self._repository.list_not_in_set(
            study_set_id=study_set_id,
            card_type=card_type,
            page=page,
            page_size=page_size,
        )
        cards = [StudyCardRead.model_validate(entity) for entity in entities]
        return StudyCardCollection(items=cards, total=total, page=page, page_size=page_size)

    async def import_card_batch(self, payload: StudyCardImportPayload) -> list[StudyCardRead]:
        """Persist a batch of typed study cards."""
        entities = await self._repository.import_cards(payload.cards)
        await self._session.commit()
        return [StudyCardRead.model_validate(entity) for entity in entities]

    async def import_cards_from_json(self, json_data: str) -> list[StudyCardRead]:
        """Parse legacy JSON payloads into typed cards and persist them."""
        adapter = TypeAdapter(list[StudyCardCreate])
        try:
            cards = adapter.validate_json(json_data)
        except ValidationError as exc:
            raise ValueError("Invalid card payload") from exc
        payload = StudyCardImportPayload(cards=list(cards))
        return await self.import_card_batch(payload)


__all__ = ["StudyCardService"]
