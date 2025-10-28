"""High level orchestration for Gemini driven study card generation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from pydantic import ValidationError

from zistudy_api.domain.schemas.ai import (
    AiGeneratedCard,
    AiGeneratedStudyCardSet,
    AiRetentionAid,
    StudyCardGenerationRequest,
)
from zistudy_api.services.ai.clients import (
    GeminiClientError,
    GeminiFilePart,
    GeminiInlineDataPart,
    GeminiMessage,
    GeminiTextPart,
    GenerationConfig,
    GenerativeClient,
)
from zistudy_api.services.ai.pdf import PDFIngestionResult, PDFTextSegment
from zistudy_api.services.ai.prompts import STUDY_CARD_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentConfiguration:
    """Static defaults and safety bounds applied to each agent invocation."""

    default_model: str
    default_temperature: float
    default_card_count: int
    max_card_count: int
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Outcome of a generation run, including any retention content."""

    cards: list[AiGeneratedCard]
    retention_aid: AiRetentionAid | None
    model_used: str
    temperature_applied: float
    requested_card_count: int


class StudyCardGenerationAgent:
    """Coordinates context preparation and Gemini invocation to build study cards."""

    def __init__(
        self,
        *,
        client: GenerativeClient,
        config: AgentConfiguration,
    ) -> None:
        self._client = client
        self._config = config

    @property
    def client(self) -> GenerativeClient:
        return self._client

    async def generate(
        self,
        request: StudyCardGenerationRequest,
        *,
        documents: Sequence[PDFIngestionResult],
        existing_questions: Sequence[str] | None = None,
        extra_parts: Sequence[GeminiTextPart | GeminiInlineDataPart | GeminiFilePart] = (),
    ) -> AgentResult:
        """Invoke Gemini with structured prompts and return the parsed result set.

        The agent preserves incremental feedback between attempts, enriches the prompt
        with PDF context, and now accepts both question and note cards emitted by the
        model while still tracking question stems to minimise duplication.
        """
        target_card_count = request.target_card_count or self._config.default_card_count
        target_card_count = min(target_card_count, self._config.max_card_count)
        temperature = request.temperature or self._config.default_temperature
        model = request.model or self._config.default_model

        schema_json = json.dumps(AiGeneratedStudyCardSet.model_json_schema(), indent=2, sort_keys=True)
        context_summaries = [
            f"- Existing question: {question.strip()}"
            for question in (existing_questions or [])
            if isinstance(question, str) and question.strip()
        ]

        generated_cards: list[AiGeneratedCard] = []
        retention_aid: AiRetentionAid | None = None
        feedback: str | None = None
        last_error: Exception | None = None

        logger.info(
            "Dispatching Gemini generation",
            extra={
                "requested_cards": target_card_count,
                "documents": len(documents),
                "existing_context": len(existing_questions or []),
                "model": model,
                "temperature": temperature,
            },
        )

        for attempt in range(1, self._config.max_attempts + 1):
            remaining = target_card_count - len(generated_cards)
            if remaining <= 0:
                break

            instructions = self._render_instruction_block(
                request,
                remaining,
                feedback,
            )
            schema_instruction = (
                f"{instructions}\n\nReturn a JSON document that matches the following schema:\n```json\n{schema_json}\n```"
            )
            parts: list[GeminiTextPart | GeminiInlineDataPart | GeminiFilePart] = [GeminiTextPart(schema_instruction)]
            parts.extend(self._render_document_parts(documents))
            if context_summaries:
                parts.append(GeminiTextPart(self._render_existing_cards_section(context_summaries)))
            parts.extend(extra_parts)

            logger.debug(
                "Invoking Gemini generate_json",
                extra={
                    "attempt": attempt,
                    "remaining": remaining,
                    "feedback_supplied": feedback is not None,
                    "extra_parts": len(extra_parts),
                },
            )

            try:
                generation_config = GenerationConfig(
                    temperature=temperature,
                    top_p=0.9,
                    top_k=32,
                    candidate_count=1,
                    max_output_tokens=6000,
                )
                payload = await self._client.generate_json(
                    system_instruction=STUDY_CARD_SYSTEM_PROMPT,
                    messages=[GeminiMessage(role="user", parts=parts)],
                    generation_config=generation_config,
                    model=model,
                )
                parsed = AiGeneratedStudyCardSet.model_validate(payload)
            except (GeminiClientError, ValidationError) as exc:
                last_error = exc
                feedback = (
                    "The previous response could not be processed. "
                    f"Error: {exc}. Please return valid JSON that matches the schema and contains new questions."
                )
                logger.warning(
                    "Gemini response invalid",
                    extra={
                        "attempt": attempt,
                        "reason": str(exc),
                        "remaining": remaining,
                    },
                )
                continue

            batch_new_cards: list[AiGeneratedCard] = []
            for card in parsed.cards:
                batch_new_cards.append(card)
                if card.card_type.is_question:
                    question = self._extract_question(card)
                    if question:
                        context_summaries.append(self._format_card_summary(card, question))

            if batch_new_cards:
                generated_cards.extend(batch_new_cards)
                logger.debug(
                    "Accepted new cards",
                    extra={
                        "attempt": attempt,
                        "batch_size": len(batch_new_cards),
                        "total_generated": len(generated_cards),
                    },
                )
                if request.include_retention_aid and parsed.retention_aid:
                    retention_aid = parsed.retention_aid
                remaining = target_card_count - len(generated_cards)
                if remaining <= 0:
                    break
                feedback = (
                    f"Received {len(batch_new_cards)} new card(s). "
                    f"{remaining} additional distinct card(s) are still required."
                )
            else:
                logger.debug(
                    "No distinct cards returned",
                    extra={
                        "attempt": attempt,
                        "feedback": True,
                    },
                )
                feedback = "No new distinct cards were produced. Provide entirely new questions that are not duplicates of the context."

        if len(generated_cards) < target_card_count:
            if last_error:
                logger.error(
                    "Gemini did not produce required cards",
                    extra={
                        "received": len(generated_cards),
                        "requested": target_card_count,
                        "error": str(last_error),
                    },
                )
                raise last_error
            raise GeminiClientError(
                "Failed to generate the requested number of distinct study cards."
            )

        cards = self._enforce_count(generated_cards, target_card_count)
        result_set = AiGeneratedStudyCardSet(cards=cards, retention_aid=retention_aid)
        logger.info(
            "Gemini generation completed",
            extra={
                "produced": len(cards),
                "retention_aid": retention_aid is not None,
                "model": model,
            },
        )
        return AgentResult(
            cards=list(result_set.cards),
            retention_aid=result_set.retention_aid,
            model_used=model,
            temperature_applied=temperature,
            requested_card_count=target_card_count,
        )

    def _render_instruction_block(
        self,
        request: StudyCardGenerationRequest,
        remaining_count: int,
        feedback: str | None,
    ) -> str:
        """Assemble the instruction header for the next Gemini attempt."""
        lines: list[str] = []
        lines.append(f"Generate {remaining_count} additional exam-ready study cards.")
        lines.append(f"Difficulty profile: {request.difficulty_profile}.")
        if request.preferred_card_types:
            joined_types = ", ".join(card_type.value for card_type in request.preferred_card_types)
            lines.append(f"Allowed card types: {joined_types}.")
        if request.topics:
            lines.append("Topics of emphasis:")
            lines.extend(f"- {topic}" for topic in request.topics)
        if request.clinical_focus:
            lines.append("Clinical focus areas:")
            lines.extend(f"- {focus}" for focus in request.clinical_focus)
        if request.learning_objectives:
            lines.append("Learning objectives:")
            lines.extend(f"- {objective}" for objective in request.learning_objectives)
        if request.learner_level:
            lines.append(f"Learner level: {request.learner_level}. Adapt nuance accordingly.")
        if request.context_hints:
            lines.append("Additional priorities:")
            lines.append(request.context_hints.strip())
        lines.append(
            "Ensure retention aids use expressive markdown with headings and emphasised cues."
        )
        lines.append("Return only JSON matching the enforced schema.")
        lines.append("Avoid duplicating any questions already shared in the context.")
        if feedback:
            lines.append(f"Previous feedback: {feedback}")
        return "\n".join(lines)

    def _render_document_parts(
        self,
        documents: Sequence[PDFIngestionResult],
    ) -> Iterable[GeminiTextPart | GeminiInlineDataPart]:
        """Render PDF segments and images into Gemini message parts."""
        for document in documents:
            if document.text_segments:
                text_buffer = [
                    f"# Source document: {document.filename or 'uploaded.pdf'} "
                    f"(pages={document.page_count})"
                ]
                text_buffer.extend(self._render_text_segments(document.text_segments))
                yield GeminiTextPart("\n".join(text_buffer))

            for image in document.images:
                yield GeminiInlineDataPart(
                    mime_type=image.mime_type,
                    data=image.data_base64,
                )

    @staticmethod
    def _render_text_segments(segments: Sequence[PDFTextSegment]) -> Iterable[str]:
        for segment in segments:
            yield f"[page {segment.page_index}] {segment.content}"

    @staticmethod
    def _enforce_count(cards: Sequence[AiGeneratedCard], target: int) -> list[AiGeneratedCard]:
        if len(cards) <= target:
            return list(cards)
        return list(cards[:target])

    @staticmethod
    def _render_existing_cards_section(context: Sequence[str]) -> str:
        buffer = ["Existing cards to avoid repeating:"]
        buffer.extend(context)
        return "\n".join(buffer)

    @staticmethod
    def _format_card_summary(card: AiGeneratedCard, question: str) -> str:
        """Return a summary used to avoid duplicates in later attempts."""
        return f"- {card.card_type.value} | difficulty {card.difficulty} | {question.strip()}"

    @staticmethod
    def _extract_question(card: AiGeneratedCard) -> str | None:
        """Extract the canonical question stem when available."""
        question = card.payload.question
        if isinstance(question, str) and question.strip():
            return question.strip()
        return None


__all__ = ["AgentConfiguration", "AgentResult", "StudyCardGenerationAgent"]
