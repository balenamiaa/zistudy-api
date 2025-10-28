from __future__ import annotations

from typing import Mapping, Sequence, cast

import pytest
from tests.utils import create_pdf_with_text_and_image

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.ai import (
    AiGeneratedCard,
    AiGeneratedCardOption,
    AiGeneratedPayload,
    AiGeneratedRationale,
    AiRetentionAid,
    StudyCardGenerationRequest,
)
from zistudy_api.domain.schemas.study_cards import (
    CardOption,
    McqSingleCardData,
    NoteCardData,
    StudyCardCreate,
)
from zistudy_api.services.ai.agents import AgentResult, StudyCardGenerationAgent
from zistudy_api.services.ai.clients import (
    GeminiClientError,
    GeminiMessage,
    GenerationConfig,
    JSONValue,
)
from zistudy_api.services.ai.generation_service import AiStudyCardService, UploadedPDF
from zistudy_api.services.ai.pdf import DocumentIngestionService, PDFIngestionResult
from zistudy_api.services.ai.pdf_strategies import (
    IngestedPDFContextStrategy,
    NativePDFContextStrategy,
)
from zistudy_api.services.study_cards import StudyCardService


class StubClient:
    def __init__(self, should_upload: bool = False) -> None:
        self.should_upload = should_upload
        self.upload_calls: list[tuple[bytes, str, str | None]] = []
        self._default_model = "models/gemini-stub"

    async def upload_file(
        self, *, data: bytes, mime_type: str, display_name: str | None = None
    ) -> str:
        self.upload_calls.append((data, mime_type, display_name))
        if not self.should_upload:
            raise AssertionError("upload_file should not have been called for inline payloads")
        return "uploaded://file"

    async def generate_json(
        self,
        *,
        system_instruction: str,
        messages: Sequence[GeminiMessage],
        response_schema: Mapping[str, JSONValue] | None = None,
        generation_config: GenerationConfig | None = None,
        model: str | None = None,
    ) -> Mapping[str, JSONValue]:
        raise AssertionError("generate_json should not be invoked in StubClient")

    async def aclose(self) -> None:  # pragma: no cover - simple stub
        return None

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def supports_file_uploads(self) -> bool:
        return True


class FailingUploadClient(StubClient):
    async def upload_file(
        self, *, data: bytes, mime_type: str, display_name: str | None = None
    ) -> str:
        raise GeminiClientError("upload failed")


class StubAgent:
    def __init__(self, result: AgentResult) -> None:
        self._result = result
        self.seen_requests: list[StudyCardGenerationRequest] = []
        self.seen_documents: list[list[PDFIngestionResult]] = []
        self.seen_existing_questions: list[list[str]] = []
        self.seen_extra_parts: list[list] = []
        self._client = StubClient()

    async def generate(
        self,
        request: StudyCardGenerationRequest,
        *,
        documents: list[PDFIngestionResult],
        existing_questions: list[str] | None = None,
        extra_parts=(),
    ) -> AgentResult:
        self.seen_requests.append(request)
        self.seen_documents.append(documents)
        self.seen_existing_questions.append(list(existing_questions or []))
        self.seen_extra_parts.append(list(extra_parts))
        return self._result

    @property
    def client(self) -> StubClient:
        return self._client


pytestmark = pytest.mark.asyncio


async def test_ai_service_persists_cards(session_maker) -> None:
    payload = create_pdf_with_text_and_image("Early recognition of sepsis improves survival.")
    document_ingestor = DocumentIngestionService(text_chunk_size=120)
    agent_result = AgentResult(
        cards=[
            AiGeneratedCard(
                card_type=CardType.MCQ_SINGLE,
                difficulty=3,
                payload=AiGeneratedPayload(
                    question="Which intervention most improves mortality in septic shock?",
                    options=[
                        AiGeneratedCardOption(id="A", text="Early broad-spectrum antibiotics"),
                        AiGeneratedCardOption(id="B", text="Low-dose dopamine"),
                    ],
                    correct_answers=["A"],
                    rationale=AiGeneratedRationale(
                        primary="Timely antibiotics within the first hour reduce mortality based on Surviving Sepsis Campaign data.",
                        alternatives={
                            "B": "Dopamine is no longer recommended due to arrhythmia risk."
                        },
                    ),
                    connections=["Initiate source control", "Assess lactate trends"],
                    glossary={"Source control": "Procedures that eliminate the infectious focus."},
                    numerical_ranges=["Mean arterial pressure target: 65–70 mmHg"],
                    references=["Surviving Sepsis Campaign 2021"],
                ),
            )
        ],
        retention_aid=AiRetentionAid(
            markdown="## Sepsis Pearls\n- Administer antibiotics within 1 hour\n- Resuscitate to MAP ≥ 65 mmHg"
        ),
        model_used="models/gemini-2.5-pro",
        temperature_applied=0.35,
        requested_card_count=1,
    )
    stub_agent = StubAgent(agent_result)

    async with session_maker() as session:
        # Seed an existing card to ensure its question is forwarded as context.
        repository = StudyCardService(session)
        seed = await repository.create_card(
            StudyCardCreate(
                card_type=CardType.MCQ_SINGLE,
                difficulty=2,
                data=McqSingleCardData(
                    generator=None,
                    prompt="What is the first-line therapy for septic shock?",
                    options=[CardOption(id="A", text="Early broad-spectrum antibiotics")],
                    correct_option_ids=["A"],
                ),
            ),
            owner=None,
        )

    async with session_maker() as session:
        service = AiStudyCardService(
            session=session,
            agent=cast(StudyCardGenerationAgent, stub_agent),
            pdf_strategy=IngestedPDFContextStrategy(document_ingestor),
        )
        request = StudyCardGenerationRequest(
            topics=["Sepsis"],
            clinical_focus=["ICU"],
            learner_level="PGY-2 resident",
            existing_card_ids=[seed.id],
        )
        result = await service.generate_from_pdfs(
            request,
            files=[UploadedPDF(filename="sepsis.pdf", payload=payload)],
        )

    assert len(result.cards) == 2  # MCQ + retention note
    assert result.retention_aid is not None
    assert result.summary.model_used == "models/gemini-2.5-pro"
    assert result.summary.sources == ["sepsis.pdf"]

    mcq, note = result.cards
    assert mcq.card_type == CardType.MCQ_SINGLE
    assert note.card_type == CardType.NOTE
    assert isinstance(mcq.data, McqSingleCardData)
    assert mcq.data.generator is not None
    assert mcq.data.generator.schema_version == "1.0.0"
    assert mcq.data.generator.topics == ["Sepsis"]
    assert isinstance(note.data, NoteCardData)
    assert note.data.generator is not None
    assert note.data.generator.schema_version == "1.0.0"
    assert note.data.markdown

    assert stub_agent.seen_documents, "Expected ingestion to provide documents"
    assert stub_agent.seen_documents[0][0].filename == "sepsis.pdf"
    assert stub_agent.seen_existing_questions[0]
    assert "first-line therapy" in stub_agent.seen_existing_questions[0][0]


async def test_ai_service_respects_retention_preference(session_maker) -> None:
    document_ingestor = DocumentIngestionService(text_chunk_size=120)
    agent_result = AgentResult(
        cards=[
            AiGeneratedCard(
                card_type=CardType.MCQ_SINGLE,
                difficulty=2,
                payload=AiGeneratedPayload(
                    question="What is the antidote for beta-blocker overdose?",
                    options=[
                        AiGeneratedCardOption(id="A", text="Glucagon"),
                        AiGeneratedCardOption(id="B", text="Naloxone"),
                    ],
                    correct_answers=["A"],
                    rationale=AiGeneratedRationale(
                        primary="Glucagon activates adenylate cyclase independent of beta receptors to restore inotropy.",
                        alternatives={"B": "Naloxone is used for opioid toxicity."},
                    ),
                    connections=[],
                    glossary={},
                    numerical_ranges=[],
                    references=[],
                ),
            )
        ],
        retention_aid=AiRetentionAid(
            markdown="## Antidotes\n- Glucagon reverses beta-blocker effects"
        ),
        model_used="models/gemini-2.5-pro",
        temperature_applied=0.2,
        requested_card_count=1,
    )
    stub_agent = StubAgent(agent_result)

    async with session_maker() as session:
        service = AiStudyCardService(
            session=session,
            agent=cast(StudyCardGenerationAgent, stub_agent),
            pdf_strategy=IngestedPDFContextStrategy(document_ingestor),
        )
        request = StudyCardGenerationRequest(
            topics=["Toxicology"],
            include_retention_aid=False,
        )
        result = await service.generate_from_pdfs(request, files=[])

    assert len(result.cards) == 1
    assert result.retention_aid is None
    card = result.cards[0]
    assert card.card_type == CardType.MCQ_SINGLE


async def test_ai_service_native_strategy_includes_pdf_parts(session_maker) -> None:
    document_ingestor = DocumentIngestionService(text_chunk_size=120)
    agent_result = AgentResult(
        cards=[
            AiGeneratedCard(
                card_type=CardType.MCQ_SINGLE,
                difficulty=1,
                payload=AiGeneratedPayload(
                    question="Stub question",
                    options=[
                        AiGeneratedCardOption(id="A", text="1"),
                        AiGeneratedCardOption(id="B", text="2"),
                    ],
                    correct_answers=["A"],
                    rationale=AiGeneratedRationale(primary="", alternatives={}),
                    connections=[],
                    glossary={},
                    numerical_ranges=[],
                    references=[],
                ),
            )
        ],
        retention_aid=None,
        model_used="models/gemini-2.5-pro",
        temperature_applied=0.2,
        requested_card_count=1,
    )
    stub_agent = StubAgent(agent_result)

    stub_agent._client.should_upload = True

    async with session_maker() as session:
        service = AiStudyCardService(
            session=session,
            agent=cast(StudyCardGenerationAgent, stub_agent),
            pdf_strategy=NativePDFContextStrategy(document_ingestor, inline_threshold=1),
        )
        request = StudyCardGenerationRequest(topics=["Test"], include_retention_aid=False)
        await service.generate_from_pdfs(
            request,
            files=[
                UploadedPDF(filename="native.pdf", payload=create_pdf_with_text_and_image("native"))
            ],
        )

    assert stub_agent.seen_extra_parts[0], "Expected PDF parts to be forwarded"
    assert stub_agent._client.upload_calls, "Expected large PDFs to be uploaded via File API"


async def test_ai_service_rejects_blank_note_markdown(session_maker) -> None:
    document_ingestor = DocumentIngestionService(text_chunk_size=120)
    agent_result = AgentResult(
        cards=[
            AiGeneratedCard(
                card_type=CardType.NOTE,
                difficulty=1,
                payload=AiGeneratedPayload(
                    question="Summarise nephritic syndrome findings.",
                    options=[],
                    correct_answers=[],
                    rationale=AiGeneratedRationale(primary="   ", alternatives={}),
                    connections=[],
                    glossary={},
                    numerical_ranges=[],
                    references=[],
                ),
            )
        ],
        retention_aid=None,
        model_used="models/gemini-2.5-pro",
        temperature_applied=0.2,
        requested_card_count=1,
    )
    stub_agent = StubAgent(agent_result)

    async with session_maker() as session:
        service = AiStudyCardService(
            session=session,
            agent=cast(StudyCardGenerationAgent, stub_agent),
            pdf_strategy=IngestedPDFContextStrategy(document_ingestor),
        )
        request = StudyCardGenerationRequest(target_card_count=1)
        with pytest.raises(ValueError):
            await service.generate_from_pdfs(request, files=[])


async def test_ai_service_rejects_blank_retention_markdown(session_maker) -> None:
    document_ingestor = DocumentIngestionService(text_chunk_size=120)
    agent_result = AgentResult(
        cards=[],
        retention_aid=AiRetentionAid(markdown=" \t "),
        model_used="models/gemini-2.5-pro",
        temperature_applied=0.2,
        requested_card_count=1,
    )
    stub_agent = StubAgent(agent_result)

    async with session_maker() as session:
        service = AiStudyCardService(
            session=session,
            agent=cast(StudyCardGenerationAgent, stub_agent),
            pdf_strategy=IngestedPDFContextStrategy(document_ingestor),
        )
        request = StudyCardGenerationRequest(target_card_count=1)
        with pytest.raises(ValueError):
            await service.generate_from_pdfs(request, files=[])


@pytest.mark.asyncio
async def test_native_strategy_falls_back_when_upload_fails() -> None:
    document_ingestor = DocumentIngestionService(text_chunk_size=64)
    strategy = NativePDFContextStrategy(document_ingestor, inline_threshold=1)
    failing_client = FailingUploadClient()
    pdf_payload = create_pdf_with_text_and_image("fallback")

    context = await strategy.build_context(
        [UploadedPDF(filename="fallback.pdf", payload=pdf_payload)],
        client=failing_client,
    )

    assert len(context.documents) == 1
    assert not context.extra_parts
