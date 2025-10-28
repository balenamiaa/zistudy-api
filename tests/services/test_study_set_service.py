from __future__ import annotations

import pytest

from zistudy_api.db.repositories.users import UserRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.study_cards import CardOption, McqSingleCardData, StudyCardCreate
from zistudy_api.domain.schemas.study_sets import (
    AddCardsToSet,
    BulkAddToSets,
    StudySetCreate,
    StudySetUpdate,
)
from zistudy_api.services.study_cards import StudyCardService
from zistudy_api.services.study_sets import StudySetService, StudySetWithMeta

pytestmark = pytest.mark.asyncio


async def _create_user(session, email: str = "owner@example.com") -> str:
    repo = UserRepository(session)
    user = await repo.create(email=email, password_hash="hash", full_name="Owner")
    await session.commit()
    return user.id


async def _create_card(session, prompt: str) -> int:
    service = StudyCardService(session)
    card = await service.create_card(
        StudyCardCreate(
            card_type=CardType.MCQ_SINGLE,
            difficulty=2,
            data=McqSingleCardData(
                prompt=prompt,
                options=[
                    CardOption(id="A", text="Option 1"),
                    CardOption(id="B", text="Option 2"),
                ],
                correct_option_ids=["A"],
            ),
        )
    )
    return card.id


async def test_study_set_service_lifecycle(session_maker) -> None:
    async with session_maker() as session:
        user_id = await _create_user(session)
        card_id = await _create_card(session, "Initial question?")

        service = StudySetService(session)
        created = await service.create_study_set(
            StudySetCreate(title="ICU Essentials", description="Basics", is_private=False, tag_names=["icu", "critical"]),
            user_id,
        )
        assert isinstance(created, StudySetWithMeta)
        assert created.study_set.title == "ICU Essentials"
        assert {tag.name for tag in created.tags} == {"icu", "critical"}

        updated = await service.update_study_set(
            created.study_set.id,
            StudySetUpdate(title="Updated", tag_names=["critical", "care"]),
        )
        assert updated.study_set.title == "Updated"
        assert {tag.name for tag in updated.tags} == {"critical", "care"}

        added = await service.add_cards(
            AddCardsToSet(
                study_set_id=created.study_set.id,
                card_ids=[card_id],
                card_type=CardType.MCQ_SINGLE,
            )
        )
        assert added == 1

        cards_page = await service.list_cards_in_set(
            study_set_id=created.study_set.id,
            card_type=None,
            page=1,
            page_size=10,
        )
        assert cards_page.total == 1

        removed = await service.remove_cards(
            study_set_id=created.study_set.id,
            card_ids=[card_id],
            card_type=CardType.MCQ_SINGLE,
        )
        assert removed == 1

        result = await service.bulk_add_cards(
            BulkAddToSets(
                study_set_ids=[created.study_set.id, 999],
                card_ids=[card_id],
                card_type=CardType.MCQ_SINGLE,
            )
        )
        assert result.success_count == 1
        assert result.error_count == 1
        assert any("not found" in error for error in result.errors)

        with pytest.raises(KeyError):
            await service.can_modify(9999, user_id)


async def test_study_set_service_permission_and_bulk_delete(session_maker) -> None:
    async with session_maker() as session:
        owner_id = await _create_user(session, email="owner@example.com")
        other_id = await _create_user(session, email="other@example.com")

        service = StudySetService(session)
        first = await service.create_study_set(StudySetCreate(title="First", description=None, is_private=True), owner_id)
        second = await service.create_study_set(StudySetCreate(title="Second", description=None, is_private=True), other_id)

        result = await service.bulk_delete_study_sets(
            study_set_ids=[first.study_set.id, second.study_set.id],
            user_id=owner_id,
        )
        assert result.success_count == 1
        assert result.error_count == 1
        assert first.study_set.id in result.affected_ids
        assert any("Forbidden" in msg for msg in result.errors)
