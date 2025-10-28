from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.auth import SessionUser
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

    async def create_card(
        self,
        payload: StudyCardCreate,
        *,
        owner: SessionUser | None,
    ) -> StudyCardRead:
        """Create a study card and return the typed read model."""
        owner_id = owner.id if owner is not None else None
        entity = await self._repository.create(payload, owner_id=owner_id)
        await self._session.commit()
        return StudyCardRead.model_validate(entity)

    async def get_card(
        self,
        card_id: int,
        *,
        requester: SessionUser | None,
    ) -> StudyCardRead:
        """Retrieve a single study card by identifier."""
        entity = await self._repository.get_by_id(card_id)
        if entity is None:
            raise KeyError(f"Study card {card_id} not found")
        if not self._can_view(entity.owner_id, requester):
            raise PermissionError("Forbidden")
        return StudyCardRead.model_validate(entity)

    async def update_card(
        self,
        card_id: int,
        payload: StudyCardUpdate,
        *,
        requester: SessionUser | None,
    ) -> StudyCardRead:
        """Apply updates to a study card and return the refreshed read model."""
        current = await self._repository.get_by_id(card_id)
        if current is None:
            raise KeyError(f"Study card {card_id} not found")
        if not self._can_modify(current.owner_id, requester):
            raise PermissionError("Forbidden")
        entity = await self._repository.update(card_id, payload)
        if entity is None:
            raise KeyError(f"Study card {card_id} not found")
        await self._session.commit()
        return StudyCardRead.model_validate(entity)

    async def delete_card(
        self,
        card_id: int,
        *,
        requester: SessionUser,
    ) -> None:
        """Delete a study card by identifier."""
        entity = await self._repository.get_by_id(card_id)
        if entity is None:
            raise KeyError(f"Study card {card_id} not found")
        if not self._can_delete(entity.owner_id, requester):
            raise PermissionError("Forbidden")
        deleted = await self._repository.delete(card_id)
        if not deleted:  # pragma: no cover - defensive since existence already checked
            raise KeyError(f"Study card {card_id} not found")
        await self._session.commit()

    async def list_cards(
        self,
        *,
        card_type: CardType | None,
        page: int,
        page_size: int,
        requester: SessionUser | None,
    ) -> StudyCardCollection:
        """Return a paginated collection of study cards filtered by type."""
        visible_owner_ids = self._visible_owner_ids(requester)
        total, entities = await self._repository.list_cards(
            card_type=card_type,
            page=page,
            page_size=page_size,
            visible_owner_ids=visible_owner_ids,
        )
        cards = [StudyCardRead.model_validate(entity) for entity in entities]
        return StudyCardCollection(
            items=cards,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def search_cards(
        self,
        request: CardSearchRequest,
        *,
        requester: SessionUser,
    ) -> PaginatedStudyCardResults:
        """Search study cards and include relevance metadata when available."""
        visible_owner_ids = self._visible_owner_ids(requester)
        total, entities = await self._repository.search_cards(
            request,
            visible_owner_ids=visible_owner_ids,
        )
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
        requester: SessionUser | None,
    ) -> StudyCardCollection:
        """List cards not currently associated with the specified study set."""
        visible_owner_ids = self._visible_owner_ids(requester)
        total, entities = await self._repository.list_not_in_set(
            study_set_id=study_set_id,
            card_type=card_type,
            page=page,
            page_size=page_size,
            visible_owner_ids=visible_owner_ids,
        )
        cards = [StudyCardRead.model_validate(entity) for entity in entities]
        return StudyCardCollection(items=cards, total=total, page=page, page_size=page_size)

    async def import_card_batch(
        self,
        payload: StudyCardImportPayload,
        *,
        owner: SessionUser | None = None,
    ) -> list[StudyCardRead]:
        """Persist a batch of typed study cards."""
        owner_id = owner.id if owner is not None else None
        entities = await self._repository.import_cards(payload.cards, owner_id=owner_id)
        await self._session.commit()
        return [StudyCardRead.model_validate(entity) for entity in entities]

    async def import_cards_from_json(
        self,
        json_data: str,
        *,
        owner: SessionUser | None = None,
    ) -> list[StudyCardRead]:
        """Deserialize ``StudyCardCreate`` records from JSON and persist them."""
        adapter = TypeAdapter(list[StudyCardCreate])
        try:
            cards = adapter.validate_json(json_data)
        except ValidationError as exc:
            raise ValueError("Invalid card payload") from exc
        payload = StudyCardImportPayload(cards=list(cards))
        return await self.import_card_batch(payload, owner=owner)

    @staticmethod
    def _visible_owner_ids(user: SessionUser | None) -> tuple[str | None, ...] | None:
        if user is None:
            return (None,)
        if user.is_superuser:
            return None
        return (user.id, None)

    @staticmethod
    def _can_view(owner_id: str | None, user: SessionUser | None) -> bool:
        if owner_id is None:
            return True
        if user is None:
            return False
        if user.is_superuser:
            return True
        return owner_id == user.id

    @classmethod
    def _can_modify(cls, owner_id: str | None, user: SessionUser | None) -> bool:
        if owner_id is None:
            return bool(user and user.is_superuser)
        if user is None:
            return False
        if user.is_superuser:
            return True
        return owner_id == user.id

    @classmethod
    def _can_delete(cls, owner_id: str | None, user: SessionUser) -> bool:
        if owner_id is None:
            return user.is_superuser
        if user.is_superuser:
            return True
        return owner_id == user.id


__all__ = ["StudyCardService"]
