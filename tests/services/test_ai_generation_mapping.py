from __future__ import annotations

from typing import Any, Sequence
from unittest.mock import AsyncMock, create_autospec

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.ai import (
    AiGeneratedCard,
    AiGeneratedCardOption,
    AiGeneratedPayload,
    AiGeneratedRationale,
    AiGeneratedStudyCardSet,
    AiRetentionAid,
    StudyCardGenerationRequest,
)
from zistudy_api.domain.schemas.study_cards import (
    CardGeneratorMetadata,
    ClozeCardData,
    EmqCardData,
    EmqMatch,
    GenericCardData,
    McqMultiCardData,
    McqSingleCardData,
    NoteCardData,
    StudyCardRead,
    TrueFalseCardData,
    WrittenCardData,
)
from zistudy_api.services.ai.agents import AgentConfiguration, AgentResult, StudyCardGenerationAgent
from zistudy_api.services.ai.clients import GenerativeClient
from zistudy_api.services.ai.generation_service import AiStudyCardService
from zistudy_api.services.ai.pdf import PDFIngestionResult, UploadedPDF
from zistudy_api.services.ai.pdf_strategies import PDFContextStrategy


class DummyStrategy(PDFContextStrategy):
    async def build_context(  # pragma: no cover - interface stub
        self,
        files: Sequence[UploadedPDF],
        *,
        client: Any,
    ):
        raise NotImplementedError


class DummyAgent(StudyCardGenerationAgent):
    def __init__(self) -> None:
        dummy_client = create_autospec(GenerativeClient, instance=True)
        dummy_config = AgentConfiguration(
            default_model="model",
            default_temperature=0.2,
            default_card_count=1,
            max_card_count=1,
        )
        super().__init__(client=dummy_client, config=dummy_config)


def _service() -> AiStudyCardService:
    session = create_autospec(AsyncSession, instance=True)
    agent = DummyAgent()
    strategy = DummyStrategy()
    return AiStudyCardService(session=session, agent=agent, pdf_strategy=strategy)


GENERATOR_META = CardGeneratorMetadata(
    model="model",
    temperature=0.2,
    requested_card_count=1,
    topics=["Cardiology"],
    clinical_focus=[],
    learning_objectives=[],
    preferred_card_types=[],
    existing_card_ids=[],
    sources=["uploaded.pdf"],
)


CARD_CASES = [
    (
        CardType.MCQ_SINGLE,
        AiGeneratedPayload(
            question="Select first-line therapy.",
            options=[
                AiGeneratedCardOption(id="A", text="Acetaminophen"),
                AiGeneratedCardOption(id="B", text="Ibuprofen"),
            ],
            correct_answers=["A"],
            rationale=AiGeneratedRationale(primary="Use acetaminophen.", alternatives={}),
            connections=[],
            glossary={},
            numerical_ranges=[],
            references=[],
        ),
        McqSingleCardData,
    ),
    (
        CardType.MCQ_MULTI,
        AiGeneratedPayload(
            question="Which findings support nephritic syndrome?",
            options=[
                AiGeneratedCardOption(id="A", text="RBC casts"),
                AiGeneratedCardOption(id="B", text="Lipid casts"),
                AiGeneratedCardOption(id="C", text="Hematuria"),
            ],
            correct_answers=["A", "C"],
            rationale=AiGeneratedRationale(primary="Glomerular injury clues.", alternatives={}),
            connections=[],
            glossary={},
            numerical_ranges=[],
            references=[],
        ),
        McqMultiCardData,
    ),
    (
        CardType.WRITTEN,
        AiGeneratedPayload(
            question="Name the antidote for organophosphate toxicity.",
            options=[],
            correct_answers=["Pralidoxime"],
            rationale=AiGeneratedRationale(primary="Reactivates acetylcholinesterase.", alternatives={}),
            connections=[],
            glossary={},
            numerical_ranges=[],
            references=[],
        ),
        WrittenCardData,
    ),
    (
        CardType.TRUE_FALSE,
        AiGeneratedPayload(
            question="Beta-blockers cause bradycardia.",
            options=[],
            correct_answers=["true"],
            rationale=AiGeneratedRationale(primary="Negative chronotrope.", alternatives={}),
            connections=[],
            glossary={},
            numerical_ranges=[],
            references=[],
        ),
        TrueFalseCardData,
    ),
    (
        CardType.CLOZE,
        AiGeneratedPayload(
            question="Fill in the blanks for the management of __ and __.",
            options=[],
            correct_answers=["hypoglycemia", "beta-blocker toxicity"],
            rationale=AiGeneratedRationale(primary="Two priorities.", alternatives={}),
            connections=[],
            glossary={},
            numerical_ranges=[],
            references=[],
        ),
        ClozeCardData,
    ),
    (
        CardType.EMQ,
        AiGeneratedPayload(
            question="Match the agent to the arrhythmia.",
            options=[
                AiGeneratedCardOption(id="0", text="Amiodarone"),
                AiGeneratedCardOption(id="1", text="Procainamide"),
            ],
            correct_answers=["1"],
            rationale=AiGeneratedRationale(primary="Procainamide for WPW.", alternatives={}),
            connections=["Wide-complex tachycardia"],
            glossary={},
            numerical_ranges=[],
            references=["Match instructions"],
        ),
        EmqCardData,
    ),
    (
        CardType.NOTE,
        AiGeneratedPayload(
            question="Summarise renal pearls.",
            options=[],
            correct_answers=[],
            rationale=AiGeneratedRationale(primary="## Renal Pearls\n- RBC casts imply GN", alternatives={}),
            connections=[],
            glossary={"title": "Renal Pearls"},
            numerical_ranges=[],
            references=[],
        ),
        NoteCardData,
    ),
]


@pytest.mark.parametrize("card_type,payload,expected_type", CARD_CASES)
def test_map_card_to_data_handles_all_types(card_type, payload, expected_type) -> None:
    service = _service()
    card = AiGeneratedCard(card_type=card_type, difficulty=2, payload=payload)

    mapped = service._map_card_to_data(card, GENERATOR_META)

    assert isinstance(mapped, expected_type)
    assert mapped.generator == GENERATOR_META
    if isinstance(mapped, NoteCardData):
        assert mapped.title == "Renal Pearls"
    if isinstance(mapped, EmqCardData):
        assert mapped.matches == [EmqMatch(premise_index=0, option_index=1)]


def test_map_card_to_data_falls_back_to_generic(monkeypatch) -> None:
    service = _service()
    payload = AiGeneratedPayload(
        question="Fallback?",
        options=[],
        correct_answers=[],
        rationale=AiGeneratedRationale(primary="reason", alternatives={}),
        connections=[],
        glossary={},
        numerical_ranges=[],
        references=[],
    )
    card = AiGeneratedCard(card_type=CardType.WRITTEN, difficulty=1, payload=payload)

    error = ValidationError.from_exception_data("CardRationale", [])
    monkeypatch.setattr(
        "zistudy_api.services.ai.generation_service.CardRationale.model_validate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    mapped = service._map_card_to_data(card, GENERATOR_META)

    assert isinstance(mapped, GenericCardData)
    assert mapped.generator == GENERATOR_META


@pytest.mark.asyncio
async def test_persist_generated_cards_respects_retention_preferences(monkeypatch) -> None:
    service = _service()
    mock_card_service = AsyncMock()
    mock_card_service.import_card_batch.return_value = []
    service._card_service = mock_card_service

    cards = [
        AiGeneratedCard(
            card_type=CardType.MCQ_SINGLE,
            difficulty=1,
            payload=CARD_CASES[0][1],
        )
    ]
    request = StudyCardGenerationRequest(
        target_card_count=1,
        include_retention_aid=True,
        preferred_card_types=[CardType.MCQ_SINGLE],
    )
    documents: list[PDFIngestionResult] = []
    meta = AgentResult(
        cards=cards,
        retention_aid=AiRetentionAid(markdown="## Note\n- Content"),
        model_used="model",
        temperature_applied=0.2,
        requested_card_count=1,
    )

    await service._persist_generated_cards(cards, request=request, documents=documents, meta=meta)

    payload = mock_card_service.import_card_batch.call_args.args[0]
    assert len(payload.cards) == 1, "Retention aid should not be appended when note not allowed"


@pytest.mark.asyncio
async def test_persist_generated_cards_appends_retention_note(monkeypatch) -> None:
    service = _service()
    mock_card_service = AsyncMock()
    mock_card_service.import_card_batch.return_value = []
    service._card_service = mock_card_service

    cards = [
        AiGeneratedCard(
            card_type=CardType.MCQ_SINGLE,
            difficulty=1,
            payload=CARD_CASES[0][1],
        )
    ]
    request = StudyCardGenerationRequest(
        target_card_count=1,
        include_retention_aid=True,
    )
    documents: list[PDFIngestionResult] = []
    meta = AgentResult(
        cards=cards,
        retention_aid=AiRetentionAid(markdown="# Retention Aid\n- Remember this"),
        model_used="model",
        temperature_applied=0.2,
        requested_card_count=1,
    )

    await service._persist_generated_cards(cards, request=request, documents=documents, meta=meta)

    payload = mock_card_service.import_card_batch.call_args.args[0]
    assert len(payload.cards) == 2
    retention_card = payload.cards[-1]
    assert retention_card.card_type is CardType.NOTE
    assert isinstance(retention_card.data, NoteCardData)
    assert retention_card.data.title == "Retention Aid"


@pytest.mark.asyncio
async def test_generate_from_pdfs_passes_context(monkeypatch) -> None:
    class StubStrategy(PDFContextStrategy):
        async def build_context(self, files, *, client):
            return type("ctx", (), {"documents": (), "extra_parts": ()})()

    class StubAgent(StudyCardGenerationAgent):
        def __init__(self):
            client = create_autospec(GenerativeClient, instance=True)
            config = AgentConfiguration(
                default_model="model",
                default_temperature=0.2,
                default_card_count=1,
                max_card_count=1,
            )
            super().__init__(client=client, config=config)

        async def generate(self, request, *, documents, existing_questions, extra_parts):
            assert not documents
            assert not existing_questions
            assert not extra_parts
            return AgentResult(
                cards=[
                    AiGeneratedCard(
                        card_type=CardType.MCQ_SINGLE,
                        difficulty=1,
                        payload=CARD_CASES[0][1],
                    )
                ],
                retention_aid=None,
                model_used="model",
                temperature_applied=0.2,
                requested_card_count=1,
            )

    session = create_autospec(AsyncSession, instance=True)
    service = AiStudyCardService(session=session, agent=StubAgent(), pdf_strategy=StubStrategy())
    mock_card_service = AsyncMock()
    sample_read = StudyCardRead.model_validate(
        {
            "id": 1,
            "card_type": CardType.MCQ_SINGLE,
            "difficulty": 1,
            "data": {
                "prompt": "Select first-line therapy.",
                "options": [{"id": "A", "text": "Acetaminophen"}],
                "correct_option_ids": ["A"],
            },
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    )
    mock_card_service.import_card_batch.return_value = [sample_read]
    service._card_service = mock_card_service

    result = await service.generate_from_pdfs(
        StudyCardGenerationRequest(target_card_count=1),
        files=[],
    )

    assert result.cards == [sample_read]
    assert result.retention_aid is None
    assert isinstance(result.raw_generation, AiGeneratedStudyCardSet)


def test_map_card_to_data_note_derives_title_from_markdown_heading() -> None:
    service = _service()
    payload = AiGeneratedPayload(
        question="Summarise renal pearls.",
        options=[],
        correct_answers=[],
        rationale=AiGeneratedRationale(primary="# Derived Title\n- Point", alternatives={}),
        connections=[],
        glossary={},
        numerical_ranges=[],
        references=[],
    )
    card = AiGeneratedCard(card_type=CardType.NOTE, difficulty=1, payload=payload)

    mapped = service._map_card_to_data(card, GENERATOR_META)

    assert isinstance(mapped, NoteCardData)
    assert mapped.title == "Derived Title"
    assert mapped.markdown.startswith("# Derived Title")


def test_map_card_to_data_note_defaults_title_when_heading_empty() -> None:
    service = _service()
    payload = AiGeneratedPayload(
        question="Summarise renal pearls.",
        options=[],
        correct_answers=[],
        rationale=AiGeneratedRationale(primary="#    \n- Point", alternatives={}),
        connections=[],
        glossary={},
        numerical_ranges=[],
        references=[],
    )
    card = AiGeneratedCard(card_type=CardType.NOTE, difficulty=1, payload=payload)

    mapped = service._map_card_to_data(card, GENERATOR_META)

    assert isinstance(mapped, NoteCardData)
    assert mapped.title == "Note"


def test_map_card_to_data_note_rejects_empty_markdown() -> None:
    service = _service()
    payload = AiGeneratedPayload(
        question="Summarise renal pearls.",
        options=[],
        correct_answers=[],
        rationale=AiGeneratedRationale(primary="   ", alternatives={}),
        connections=[],
        glossary={},
        numerical_ranges=[],
        references=[],
    )
    card = AiGeneratedCard(card_type=CardType.NOTE, difficulty=1, payload=payload)

    with pytest.raises(ValueError):
        service._map_card_to_data(card, GENERATOR_META)


def test_card_generator_metadata_sets_schema_version() -> None:
    service = _service()
    request = StudyCardGenerationRequest(
        target_card_count=2,
        topics=["Cardiology"],
        preferred_card_types=[CardType.MCQ_SINGLE],
        existing_card_ids=[1],
    )
    documents = [
        PDFIngestionResult(
            filename="source.pdf",
            text_segments=(),
            images=(),
            page_count=1,
        )
    ]
    agent_result = AgentResult(
        cards=[],
        retention_aid=None,
        model_used="model",
        temperature_applied=0.2,
        requested_card_count=2,
    )

    meta = service._card_generator_metadata(request, documents, agent_result)

    assert meta.schema_version == GENERATOR_META.schema_version
    assert meta.sources == ["source.pdf"]


def test_parse_boolean_answer_interprets_values() -> None:
    service = _service()

    assert service._parse_boolean_answer(["TRUE"]) is True
    assert service._parse_boolean_answer(["0"]) is False
    assert service._parse_boolean_answer(["maybe"]) is None
