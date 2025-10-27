from __future__ import annotations

import logging
from typing import Sequence

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.db.repositories.study_cards import StudyCardRepository
from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.ai import (
    AiGeneratedCard,
    AiGeneratedStudyCardSet,
    AiRetentionAid,
    StudyCardGenerationRequest,
    StudyCardGenerationResult,
    StudyCardGenerationSummary,
)
from zistudy_api.domain.schemas.study_cards import (
    CARD_GENERATOR_SCHEMA_VERSION,
    CardData,
    CardGeneratorMetadata,
    CardOption,
    CardRationale,
    ClozeCardData,
    EmqCardData,
    EmqMatch,
    GenericCardData,
    McqMultiCardData,
    McqSingleCardData,
    NoteCardData,
    QuestionCardData,
    StudyCardCreate,
    StudyCardImportPayload,
    StudyCardRead,
    TrueFalseCardData,
    WrittenCardData,
    parse_card_data,
)
from zistudy_api.services.ai.agents import AgentResult, StudyCardGenerationAgent
from zistudy_api.services.ai.clients import GenerativeClient
from zistudy_api.services.ai.pdf import PDFIngestionResult, UploadedPDF
from zistudy_api.services.ai.pdf_strategies import PDFContextStrategy
from zistudy_api.services.study_cards import StudyCardService

logger = logging.getLogger(__name__)


class AiStudyCardService:
    """High-level façade orchestrating ingestion, generation, and persistence."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        agent: StudyCardGenerationAgent,
        pdf_strategy: PDFContextStrategy,
    ) -> None:
        self._session = session
        self._agent = agent
        self._pdf_strategy = pdf_strategy
        self._card_service = StudyCardService(session)
        self._client: GenerativeClient = agent.client

    async def generate_from_pdfs(
        self,
        request: StudyCardGenerationRequest,
        files: Sequence[UploadedPDF],
    ) -> StudyCardGenerationResult:
        """Ingest PDFs, invoke the generation agent, and persist the resulting cards."""
        logger.info(
            "Preparing AI study card generation",
            extra={
                "file_count": len(files),
                "strategy": type(self._pdf_strategy).__name__,
                "topics": request.topics,
                "target_cards": request.target_card_count,
            },
        )
        pdf_context = await self._pdf_strategy.build_context(files, client=self._client)
        documents = list(pdf_context.documents)
        logger.debug(
            "PDF context prepared",
            extra={
                "documents": len(documents),
                "extra_parts": len(pdf_context.extra_parts),
            },
        )
        existing_questions = await self._load_existing_questions(request.existing_card_ids)
        logger.debug(
            "Loaded existing questions",
            extra={"existing_questions": len(existing_questions)},
        )
        agent_result = await self._agent.generate(
            request,
            documents=documents,
            existing_questions=existing_questions,
            extra_parts=tuple(pdf_context.extra_parts),
        )
        logger.info(
            "AI agent returned result",
            extra={
                "generated_cards": len(agent_result.cards),
                "retention_aid": agent_result.retention_aid is not None,
            },
        )
        cards = await self._persist_generated_cards(
            agent_result.cards,
            request=request,
            documents=documents,
            meta=agent_result,
        )
        logger.info(
            "Persisted generated cards",
            extra={"created_cards": len(cards)},
        )

        summary = self._build_summary(documents, agent_result, cards_count=len(cards))
        retention_aid = agent_result.retention_aid if request.include_retention_aid else None
        raw = AiGeneratedStudyCardSet(
            cards=agent_result.cards,
            retention_aid=agent_result.retention_aid,
        )
        return StudyCardGenerationResult(
            cards=cards,
            retention_aid=retention_aid,
            summary=summary,
            raw_generation=raw,
        )

    async def _load_existing_questions(self, card_ids: Sequence[int]) -> list[str]:
        if not card_ids:
            return []
        repository = StudyCardRepository(self._session)
        records = await repository.get_many(card_ids)
        questions: list[str] = []
        for record in records:
            card_type = CardType(record.card_type) if isinstance(record.card_type, str) else record.card_type
            question = self._extract_question_from_data(card_type, record.data)
            if question:
                questions.append(question)
        return questions

    async def _persist_generated_cards(
        self,
        generated_cards: Sequence[AiGeneratedCard],
        *,
        request: StudyCardGenerationRequest,
        documents: Sequence[PDFIngestionResult],
        meta: AgentResult,
    ) -> list[StudyCardRead]:
        card_payloads = []
        generator_meta = self._card_generator_metadata(request, documents, meta)
        for card in generated_cards:
            data_model = self._map_card_to_data(card, generator_meta)
            card_payloads.append(
                StudyCardCreate(
                    card_type=card.card_type,
                    difficulty=card.difficulty,
                    data=data_model,
                )
            )
        include_retention_note = (
            meta.retention_aid is not None
            and request.include_retention_aid
            and (not request.preferred_card_types or CardType.NOTE in request.preferred_card_types)
        )
        if include_retention_note and meta.retention_aid:
            card_payloads.append(self._build_retention_note(meta.retention_aid, generator_meta))

        payload = StudyCardImportPayload(cards=card_payloads)
        created = await self._card_service.import_card_batch(payload)
        return created

    def _map_card_to_data(
        self,
        card: AiGeneratedCard,
        generator: CardGeneratorMetadata,
    ) -> CardData:
        """Transform a generated card into the typed domain payload.

        Raises:
            ValueError: If the model returns a note without markdown content or a
                resolvable title, ensuring invalid notes cannot be persisted silently.
        """
        payload = card.payload
        try:
            rationale = CardRationale.model_validate(payload.rationale.model_dump(mode="json"))
            base_kwargs = {
                "generator": generator,
                "prompt": payload.question,
                "rationale": rationale,
                "glossary": payload.glossary,
                "connections": payload.connections,
                "references": payload.references,
                "numerical_ranges": payload.numerical_ranges,
            }

            if card.card_type == CardType.MCQ_SINGLE:
                options = [CardOption(id=option.id, text=option.text) for option in payload.options or []]
                correct_ids = payload.correct_answers or ([options[0].id] if options else [])
                return McqSingleCardData(
                    **base_kwargs,
                    options=options,
                    correct_option_ids=correct_ids,
                )

            if card.card_type == CardType.MCQ_MULTI:
                options = [CardOption(id=option.id, text=option.text) for option in payload.options or []]
                correct_ids = payload.correct_answers or [option.id for option in options[:2]]
                return McqMultiCardData(
                    **base_kwargs,
                    options=options,
                    correct_option_ids=correct_ids,
                )

            if card.card_type == CardType.WRITTEN:
                expected = payload.correct_answers[0] if payload.correct_answers else None
                return WrittenCardData(**base_kwargs, expected_answer=expected)

            if card.card_type == CardType.TRUE_FALSE:
                answer = self._parse_boolean_answer(payload.correct_answers)
                if answer is None:
                    answer = True
                return TrueFalseCardData(**base_kwargs, correct_answer=answer)

            if card.card_type == CardType.CLOZE:
                return ClozeCardData(
                    **base_kwargs,
                    cloze_answers=payload.correct_answers or [],
                )

            if card.card_type == CardType.EMQ:
                matches = []
                for index, option_id in enumerate(payload.correct_answers or []):
                    try:
                        matches.append(
                            EmqMatch.model_validate(
                                {"premise_index": index, "option_index": int(option_id)}
                            )
                        )
                    except Exception:  # noqa: BLE001
                        continue
                return EmqCardData(
                    **base_kwargs,
                    instructions=payload.references[0] if payload.references else None,
                    premises=payload.connections,
                    options=[option.text for option in payload.options or []],
                    matches=matches,
                )

            if card.card_type == CardType.NOTE:
                markdown_raw = payload.rationale.primary or ""
                markdown = markdown_raw.strip()
                if not markdown:
                    raise ValueError("Generated note card contained empty markdown content.")
                title_value = payload.glossary.get("title") if payload.glossary else None
                if isinstance(title_value, str) and title_value.strip():
                    title = title_value.strip()
                else:
                    title = self._extract_heading(markdown) or "Note"
                title = title.strip()
                if not title:
                    raise ValueError("Generated note card resolved to a blank title.")
                return NoteCardData(generator=generator, title=title, markdown=markdown)
        except ValidationError as exc:  # pragma: no cover - defensive guard
            logger.debug(
                "Falling back to generic card data",
                extra={"card_type": card.card_type, "error": str(exc)},
            )

        return GenericCardData(
            generator=generator,
            payload=card.payload.model_dump(mode="json"),
        )

    @staticmethod
    def _parse_boolean_answer(correct_answers: Sequence[str]) -> bool | None:
        if not correct_answers:
            return None
        candidate = correct_answers[0].strip().lower()
        if candidate in {"true", "t", "1", "yes", "y"}:
            return True
        if candidate in {"false", "f", "0", "no", "n"}:
            return False
        return None

    def _build_retention_note(
        self,
        retention: AiRetentionAid,
        generator: CardGeneratorMetadata,
    ) -> StudyCardCreate:
        """Build a persistent note from the retention aid markdown."""
        markdown = (retention.markdown or "").strip()
        if not markdown:
            raise ValueError("Retention aids must include markdown content.")
        title = self._extract_heading(markdown) or "Retention Aid"
        data = NoteCardData(generator=generator, title=title.strip(), markdown=markdown)
        return StudyCardCreate(card_type=CardType.NOTE, difficulty=1, data=data)

    @staticmethod
    def _build_summary(
        documents: Sequence[PDFIngestionResult],
        meta: AgentResult,
        cards_count: int,
    ) -> StudyCardGenerationSummary:
        sources = [
            document.filename or f"uploaded-{index + 1}.pdf"
            for index, document in enumerate(documents)
        ]
        return StudyCardGenerationSummary(
            card_count=cards_count,
            sources=sources,
            model_used=meta.model_used,
            temperature_applied=meta.temperature_applied,
        )

    def _card_generator_metadata(
        self,
        request: StudyCardGenerationRequest,
        documents: Sequence[PDFIngestionResult],
        meta: AgentResult,
    ) -> CardGeneratorMetadata:
        return CardGeneratorMetadata(
            model=meta.model_used,
            temperature=meta.temperature_applied,
            requested_card_count=meta.requested_card_count,
            topics=request.topics,
            clinical_focus=request.clinical_focus,
            learning_objectives=request.learning_objectives,
            preferred_card_types=[card_type.value for card_type in request.preferred_card_types],
            existing_card_ids=request.existing_card_ids,
            sources=[
                document.filename or f"uploaded-{index + 1}.pdf"
                for index, document in enumerate(documents)
            ],
            schema_version=CARD_GENERATOR_SCHEMA_VERSION,
        )

    @staticmethod
    def _extract_question_from_data(card_type: CardType | None, data: dict | None) -> str | None:
        if not isinstance(data, dict):
            return None
        parsed = parse_card_data(card_type, data)
        if isinstance(parsed, QuestionCardData):
            return parsed.prompt.strip()
        return None

    @staticmethod
    def _extract_heading(markdown: str | None) -> str | None:
        if not markdown:
            return None
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
            if stripped:
                return stripped[:80].strip()
        return None


__all__ = ["AiStudyCardService", "UploadedPDF"]
