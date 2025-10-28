from __future__ import annotations

import json

import pytest

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.auth import SessionUser
from zistudy_api.domain.schemas.study_cards import (
    CardOption,
    CardSearchFilters,
    CardSearchRequest,
    McqSingleCardData,
    NoteCardData,
    StudyCardCreate,
    StudyCardUpdate,
)
from zistudy_api.services.study_cards import StudyCardService

pytestmark = pytest.mark.asyncio


async def test_study_card_service_crud(session_maker) -> None:
    async with session_maker() as session:
        service = StudyCardService(session)
        owner = SessionUser(
            id="user-123",
            email="user@example.com",
            is_superuser=False,
        )
        payload = StudyCardCreate(
            card_type=CardType.MCQ_SINGLE,
            difficulty=2,
            data=McqSingleCardData(
                prompt="What is the powerhouse of the cell?",
                options=[
                    CardOption(id="A", text="Nucleus"),
                    CardOption(id="B", text="Mitochondria"),
                    CardOption(id="C", text="Golgi apparatus"),
                ],
                correct_option_ids=["B"],
            ),
        )
        created = await service.create_card(payload, owner=owner)
        assert created.owner_id == owner.id

        fetched = await service.get_card(created.id, requester=owner)
        assert isinstance(fetched.data, McqSingleCardData)
        assert fetched.data.correct_option_ids == ["B"]

        updated = await service.update_card(
            created.id,
            StudyCardUpdate(
                difficulty=3,
                data=McqSingleCardData(
                    generator=None,
                    prompt="Updated?",
                    options=[CardOption(id="A", text="ATP synthesis"), CardOption(id="B", text="Protein folding")],
                    correct_option_ids=["A"],
                ),
            ),
            requester=owner,
        )
        assert updated.difficulty == 3
        assert isinstance(updated.data, McqSingleCardData)
        assert updated.data.prompt == "Updated?"

        collection = await service.list_cards(
            card_type=None,
            page=1,
            page_size=10,
            requester=owner,
        )
        assert collection.total == 1

        search = await service.search_cards(
            CardSearchRequest(
                query="Updated",
                filters=CardSearchFilters(card_types=[CardType.MCQ_SINGLE]),
                page=1,
                page_size=10,
            ),
            requester=owner,
        )
        assert search.total == 1

        await service.delete_card(created.id, requester=owner)
        with pytest.raises(KeyError):
            await service.get_card(created.id, requester=owner)


async def test_study_card_service_import_cards_from_json(session_maker) -> None:
        async with session_maker() as session:
            service = StudyCardService(session)
            owner = SessionUser(
                id="import-owner",
                email="owner@example.com",
                is_superuser=False,
            )
            cards = [
                StudyCardCreate(
                    card_type=CardType.NOTE,
                    difficulty=1,
                    data=NoteCardData(generator=None, title="Hydration", markdown="Remember to hydrate."),
                ).model_dump(mode="json"),
                StudyCardCreate(
                    card_type=CardType.MCQ_SINGLE,
                    difficulty=3,
                    data=McqSingleCardData(
                        generator=None,
                        prompt="Normal sodium?",
                        options=[CardOption(id="A", text="135-145 mEq/L"), CardOption(id="B", text="120-130 mEq/L")],
                        correct_option_ids=["A"],
                    ),
                ).model_dump(mode="json"),
            ]
            created = await service.import_cards_from_json(json.dumps(cards), owner=owner)
            assert len(created) == 2
            assert {card.card_type for card in created} == {CardType.NOTE, CardType.MCQ_SINGLE}
            assert all(card.owner_id == owner.id for card in created)


async def test_system_owned_deletion_requires_admin(session_maker) -> None:
    async with session_maker() as session:
        service = StudyCardService(session)
        system_card = await service.create_card(
            StudyCardCreate(
                card_type=CardType.NOTE,
                difficulty=1,
                data=NoteCardData(generator=None, title="Shared", markdown="System provided."),
            ),
            owner=None,
        )

        regular_user = SessionUser(id="regular", email="regular@example.com", is_superuser=False)
        admin_user = SessionUser(id="admin", email="admin@example.com", is_superuser=True)

        with pytest.raises(PermissionError):
            await service.delete_card(system_card.id, requester=regular_user)

        await service.delete_card(system_card.id, requester=admin_user)


async def test_list_cards_respects_visibility(session_maker) -> None:
    async with session_maker() as session:
        service = StudyCardService(session)
        owner = SessionUser(id="owner", email="owner@example.com", is_superuser=False)
        other = SessionUser(id="other", email="other@example.com", is_superuser=False)

        owned_card = await service.create_card(
            StudyCardCreate(
                card_type=CardType.MCQ_SINGLE,
                difficulty=2,
                data=McqSingleCardData(
                    prompt="Owner question?",
                    options=[CardOption(id="A", text="Answer")],
                    correct_option_ids=["A"],
                ),
            ),
            owner=owner,
        )
        system_card = await service.create_card(
            StudyCardCreate(
                card_type=CardType.NOTE,
                difficulty=1,
                data=NoteCardData(generator=None, title="System", markdown="Shared note"),
            ),
            owner=None,
        )

        owner_list = await service.list_cards(card_type=None, page=1, page_size=10, requester=owner)
        assert {card.id for card in owner_list.items} == {owned_card.id, system_card.id}

        other_list = await service.list_cards(card_type=None, page=1, page_size=10, requester=other)
        assert {card.id for card in other_list.items} == {system_card.id}

        anonymous_list = await service.list_cards(card_type=None, page=1, page_size=10, requester=None)
        assert {card.id for card in anonymous_list.items} == {system_card.id}

        owner_not_in_set = await service.list_cards_not_in_set(
            study_set_id=123,
            card_type=None,
            page=1,
            page_size=10,
            requester=owner,
        )
        assert owner_not_in_set.total == 2

        other_not_in_set = await service.list_cards_not_in_set(
            study_set_id=123,
            card_type=None,
            page=1,
            page_size=10,
            requester=other,
        )
        assert {card.id for card in other_not_in_set.items} == {system_card.id}


async def test_superuser_listing_and_updates(session_maker, monkeypatch) -> None:
    async with session_maker() as session:
        service = StudyCardService(session)
        owner = SessionUser(id="owner-1", email="owner1@example.com", is_superuser=False)
        superuser = SessionUser(id="super", email="super@example.com", is_superuser=True)

        card = await service.create_card(
            StudyCardCreate(
                card_type=CardType.MCQ_SINGLE,
                difficulty=2,
                data=McqSingleCardData(
                    prompt="Superuser question?",
                    options=[CardOption(id="A", text="Answer")],
                    correct_option_ids=["A"],
                ),
            ),
            owner=owner,
        )

        super_listing = await service.list_cards(card_type=None, page=1, page_size=10, requester=superuser)
        assert {item.id for item in super_listing.items} == {card.id}

        updated = await service.update_card(
            card.id,
            StudyCardUpdate(difficulty=4),
            requester=superuser,
        )
        assert updated.difficulty == 4

        fetched = await service.get_card(card.id, requester=superuser)
        assert fetched.id == card.id

        async def fake_update(card_id: int, payload: StudyCardUpdate):
            return None

        monkeypatch.setattr(service._repository, "update", fake_update)
        with pytest.raises(KeyError):
            await service.update_card(card.id, StudyCardUpdate(difficulty=5), requester=superuser)
