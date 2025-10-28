from __future__ import annotations

import json

import pytest

from zistudy_api.domain.enums import CardType
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
        created = await service.create_card(payload)
        fetched = await service.get_card(created.id)
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
        )
        assert updated.difficulty == 3
        assert isinstance(updated.data, McqSingleCardData)
        assert updated.data.prompt == "Updated?"

        collection = await service.list_cards(card_type=None, page=1, page_size=10)
        assert collection.total == 1

        search = await service.search_cards(
            CardSearchRequest(
                query="Updated",
                filters=CardSearchFilters(card_types=[CardType.MCQ_SINGLE]),
                page=1,
                page_size=10,
            )
        )
        assert search.total == 1

        await service.delete_card(created.id)
        with pytest.raises(KeyError):
            await service.get_card(created.id)


async def test_study_card_service_import_cards_from_json(session_maker) -> None:
        async with session_maker() as session:
            service = StudyCardService(session)
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
            created = await service.import_cards_from_json(json.dumps(cards))
            assert len(created) == 2
            assert {card.card_type for card in created} == {CardType.NOTE, CardType.MCQ_SINGLE}
