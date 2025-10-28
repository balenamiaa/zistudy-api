from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.models import StudySet
from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.db.repositories.study_sets import StudySetRepository
from zistudy_api.db.repositories.tags import TagRepository
from zistudy_api.domain.enums import CardCategory, CardType
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.study_cards import StudyCardRead
from zistudy_api.domain.schemas.study_sets import (
    AddCardsToSet,
    BulkAddToSets,
    BulkOperationResult,
    StudySetCardEntry,
    StudySetCardsPage,
    StudySetCreate,
    StudySetForCard,
    StudySetRead,
    StudySetUpdate,
    StudySetWithMeta,
)
from zistudy_api.domain.schemas.tags import TagRead


class StudySetService:
    """Domain services orchestrating study set operations."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._study_sets = StudySetRepository(session)
        self._tags = TagRepository(session)
        self._cards = StudyCardRepository(session)

    async def create_study_set(
        self, payload: StudySetCreate, user_id: str | None
    ) -> StudySetWithMeta:
        """Create a study set with optional tags and return its metadata-rich view."""
        entity = await self._study_sets.create(payload, user_id)
        if payload.tag_names:
            tags = await self._tags.ensure_tags(payload.tag_names)
            await self._study_sets.attach_tags(entity, tags)
        await self._session.commit()
        return await self.get_study_set(entity.id)

    async def get_study_set(self, study_set_id: int) -> StudySetWithMeta:
        """Fetch a study set and expand associated metadata."""
        entity = await self._require_study_set(study_set_id)
        return await self._build_meta_response(entity)

    async def update_study_set(
        self, study_set_id: int, payload: StudySetUpdate
    ) -> StudySetWithMeta:
        """Update study set details and return the refreshed metadata wrapper."""
        entity = await self._require_study_set(study_set_id)
        await self._study_sets.update(entity, payload)
        if payload.tag_names is not None:
            tags = await self._tags.ensure_tags(payload.tag_names)
            await self._study_sets.attach_tags(entity, tags)
        await self._session.commit()
        await self._session.refresh(entity)
        return await self._build_meta_response(entity)

    async def delete_study_set(self, study_set_id: int) -> None:
        """Remove a study set from the repository."""
        entity = await self._require_study_set(study_set_id)
        await self._study_sets.delete(entity)
        await self._session.commit()

    async def list_accessible_study_sets(
        self,
        *,
        user_id: str | None,
        show_only_owned: bool,
        search_query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[int, list[StudySetWithMeta]]:
        """Return accessible study sets for the caller with pagination metadata."""
        total, entities = await self._study_sets.list_accessible(
            current_user=user_id,
            show_only_owned=show_only_owned,
            search_query=search_query,
            page=page,
            page_size=page_size,
        )
        meta = [await self._build_meta_response(entity) for entity in entities]
        return total, meta

    async def can_modify(self, study_set_id: int, user_id: str | None) -> bool:
        """Determine whether a user is permitted to modify a study set."""
        entity = await self._study_sets.get_by_id(study_set_id)
        if entity is None:
            raise KeyError(f"Study set {study_set_id} not found")
        read_model = StudySetRead.model_validate(entity)
        return read_model.can_modify(user_id)

    async def add_cards(self, payload: AddCardsToSet, *, requester: SessionUser) -> int:
        """Add cards to a study set, ensuring all IDs are valid."""
        entity = await self._require_study_set(payload.study_set_id)
        unique_ids = list(dict.fromkeys(payload.card_ids))
        cards = await self._cards.get_many(unique_ids)
        found_ids = {card.id for card in cards}
        if len(found_ids) != len(unique_ids):
            missing = set(unique_ids) - found_ids
            raise ValueError(f"Unknown card ids: {sorted(missing)}")
        inaccessible = [
            card.id
            for card in cards
            if not self._card_accessible(card.owner_id, requester)
        ]
        if inaccessible:
            raise PermissionError(f"Forbidden: cards {sorted(inaccessible)}")

        category = payload.card_type.category
        added = await self._study_sets.add_cards(
            study_set_id=entity.id,
            card_ids=unique_ids,
            card_category=category,
        )
        await self._session.commit()
        return added

    async def remove_cards(
        self,
        study_set_id: int,
        card_ids: Sequence[int],
        card_type: CardType,
    ) -> int:
        """Remove cards from a study set by identifier."""
        await self._require_study_set(study_set_id)
        unique_ids = list(dict.fromkeys(card_ids))
        removed = await self._study_sets.remove_cards(
            study_set_id=study_set_id,
            card_ids=unique_ids,
            card_category=card_type.category,
        )
        await self._session.commit()
        return removed

    async def list_cards_in_set(
        self,
        *,
        study_set_id: int,
        card_type: CardType | None,
        page: int,
        page_size: int,
    ) -> StudySetCardsPage:
        """List the cards inside a study set with pagination support."""
        await self._require_study_set(study_set_id)
        total, entries = await self._study_sets.list_cards(
            study_set_id=study_set_id,
            card_type=card_type,
            page=page,
            page_size=page_size,
        )
        card_entries = [
            StudySetCardEntry(
                card=StudyCardRead.model_validate(card),
                position=position,
            )
            for card, position in entries
        ]
        return StudySetCardsPage(items=card_entries, total=total, page=page, page_size=page_size)

    async def bulk_add_cards(
        self,
        payload: BulkAddToSets,
        *,
        requester: SessionUser,
    ) -> BulkOperationResult:
        """Add cards to multiple study sets and aggregate success/error counts."""
        errors: list[str] = []
        success = 0

        for study_set_id in payload.study_set_ids:
            try:
                await self._require_study_set(study_set_id)
                await self.add_cards(
                    AddCardsToSet(
                        study_set_id=study_set_id,
                        card_ids=payload.card_ids,
                        card_type=payload.card_type,
                    ),
                    requester=requester,
                )
                success += 1
            except (KeyError, ValueError) as exc:
                errors.append(f"Set {study_set_id}: {exc}")
            except PermissionError as exc:
                errors.append(f"Set {study_set_id}: {exc}")

        return BulkOperationResult(
            success_count=success,
            error_count=len(errors),
            errors=errors,
            affected_ids=payload.study_set_ids,
        )

    async def bulk_delete_study_sets(
        self,
        *,
        study_set_ids: Sequence[int],
        user_id: str | None,
    ) -> BulkOperationResult:
        """Delete multiple study sets, skipping sets the caller cannot modify."""
        errors: list[str] = []
        success = 0
        deleted: list[int] = []

        for study_set_id in study_set_ids:
            try:
                if not await self.can_modify(study_set_id, user_id):
                    raise PermissionError("Forbidden")
                await self.delete_study_set(study_set_id)
                deleted.append(study_set_id)
                success += 1
            except PermissionError as exc:
                errors.append(f"Set {study_set_id}: {exc}")
            except KeyError as exc:
                errors.append(f"Set {study_set_id}: {exc}")

        return BulkOperationResult(
            success_count=success,
            error_count=len(errors),
            errors=errors,
            affected_ids=deleted,
        )

    async def get_study_sets_for_card(
        self,
        *,
        card_id: int,
        user_id: str | None,
    ) -> list[StudySetForCard]:
        """Return study sets that contain the specified card and are accessible."""
        sets = await self._study_sets.list_for_card(card_id)
        responses: list[StudySetForCard] = []
        for entity in sets:
            meta = await self._build_meta_response(entity)
            read_model = meta.study_set
            if not read_model.can_access(user_id):
                continue
            contains_card = True
            responses.append(
                StudySetForCard(
                    study_set=read_model,
                    contains_card=contains_card,
                    card_count=meta.card_count,
                    owner_email=meta.owner_email,
                    tags=meta.tags,
                )
            )

        return responses

    async def _require_study_set(self, study_set_id: int) -> StudySet:
        entity = await self._study_sets.get_by_id(study_set_id)
        if entity is None:
            raise KeyError(f"Study set {study_set_id} not found")
        return entity

    async def _build_meta_response(self, entity: StudySet) -> StudySetWithMeta:
        await self._session.refresh(entity, attribute_names=["tags", "owner"])
        tags = [TagRead.model_validate(tag.tag) for tag in entity.tags if tag.tag]
        study_set = StudySetRead.model_validate(entity)
        counts = await self._study_sets.get_card_counts(entity.id)

        owner = entity.__dict__.get("owner")
        owner_email = owner.email if owner is not None else None

        return StudySetWithMeta(
            study_set=study_set,
            tags=tags,
            card_count=counts["total"],
            question_count=counts["questions"],
            owner_email=owner_email,
        )

    @staticmethod
    def _card_accessible(owner_id: str | None, requester: SessionUser) -> bool:
        if owner_id is None:
            return True
        if requester.is_superuser:
            return True
        return owner_id == requester.id

    async def clone_study_sets(
        self,
        *,
        study_set_ids: Sequence[int],
        owner_id: str,
        title_prefix: str | None = None,
    ) -> list[int]:
        new_ids: list[int] = []

        for study_set_id in study_set_ids:
            original = await self._study_sets.get_by_id(study_set_id)
            if original is None:
                raise KeyError(f"Study set {study_set_id} not found")
            if not StudySetRead.model_validate(original).can_access(owner_id):
                raise PermissionError("Forbidden")

            new_title = original.title
            if title_prefix:
                new_title = f"{title_prefix}{new_title}"

            create_payload = StudySetCreate(
                title=new_title,
                description=original.description,
                is_private=original.is_private,
                tag_names=[],
            )

            clone = await self._study_sets.create(create_payload, owner_id)

            tag_names = [tag.tag.name for tag in original.tags if tag.tag]
            if tag_names:
                tags = await self._tags.ensure_tags(tag_names)
                await self._study_sets.attach_tags(clone, tags)

            cards_by_category: dict[CardCategory, list[int]] = {}
            for relation in original.cards:
                category = relation.card_category
                if not isinstance(category, CardCategory):
                    category = CardCategory(category)
                cards_by_category.setdefault(category, []).append(relation.card_id)

            for category, card_ids in cards_by_category.items():
                await self._study_sets.add_cards(
                    study_set_id=clone.id,
                    card_ids=card_ids,
                    card_category=category,
                )

            new_ids.append(clone.id)

        await self._session.commit()
        return new_ids

    async def export_study_sets(
        self,
        *,
        study_set_ids: Sequence[int],
        user_id: str,
    ) -> list[dict[str, Any]]:
        exports: list[dict[str, Any]] = []
        for study_set_id in study_set_ids:
            entity = await self._study_sets.get_by_id(study_set_id)
            if entity is None:
                raise KeyError(f"Study set {study_set_id} not found")
            read_model = StudySetRead.model_validate(entity)
            if not read_model.can_access(user_id):
                raise PermissionError("Forbidden")

            cards_with_meta = await self._study_sets.get_cards_with_details(study_set_id)
            meta = await self._build_meta_response(entity)
            exports.append(
                {
                    "study_set": meta.model_dump(mode="json"),
                    "cards": [
                        {
                            "card": StudyCardRead.model_validate(card).model_dump(mode="json"),
                            "position": relation.position,
                            "card_category": relation.card_category,
                        }
                        for relation, card in cards_with_meta
                    ],
                }
            )
        return exports


__all__ = ["StudySetService"]
