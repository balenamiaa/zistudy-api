from __future__ import annotations

from typing import Literal

from pydantic import Field

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.base import BaseSchema
from zistudy_api.domain.schemas.study_cards import Difficulty, StudyCardRead


class StudyCardGenerationRequest(BaseSchema):
    topics: list[str] = Field(default_factory=list, description="Core subjects to emphasise.")
    clinical_focus: list[str] = Field(
        default_factory=list,
        description="Specific diseases, systems, or patient populations to prioritise.",
    )
    learning_objectives: list[str] = Field(
        default_factory=list,
        description="Granular competencies the learner wants to master.",
    )
    target_card_count: int | None = Field(
        default=None,
        ge=1,
        le=60,
        description="Desired number of cards; falls back to configuration defaults when omitted.",
    )
    preferred_card_types: list[CardType] = Field(
        default_factory=list, description="Optional restriction on generated card types."
    )
    difficulty_profile: Literal["balanced", "advanced", "foundational"] = Field(
        default="balanced",
        description="Controls the overall distribution of difficulty values.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional creativity override for the LLM call.",
    )
    model: str | None = Field(
        default=None,
        description="Override model identifier for the generation request.",
    )
    include_retention_aid: bool = Field(
        default=True,
        description="Include a markdown retention aid in the response.",
    )
    learner_level: str | None = Field(
        default=None,
        description="Short descriptor of the learner's current training stage.",
    )
    context_hints: str | None = Field(
        default=None,
        description="Additional free-form hints or priorities for the generator.",
    )
    existing_card_ids: list[int] = Field(
        default_factory=list,
        description="Identifiers of previously generated cards to reference and avoid duplicating.",
    )


class StudyCardGenerationSummary(BaseSchema):
    card_count: int
    sources: list[str] = Field(
        default_factory=list,
        description="Names of ingested files or other context sources.",
    )
    model_used: str
    temperature_applied: float


class AiGeneratedCardOption(BaseSchema):
    id: str = Field(..., description="Stable identifier for the option (e.g. letter).")
    text: str = Field(..., description="Option text rendered to the learner.")


class AiGeneratedRationale(BaseSchema):
    primary: str = Field(..., description="Primary explanation for the correct answer.")
    alternatives: dict[str, str] = Field(
        default_factory=dict,
        description="Explanation keyed by option id for why alternatives are incorrect.",
    )


class AiGeneratedPayload(BaseSchema):
    question: str = Field(..., description="Full exam-style stem or prompt.")
    options: list[AiGeneratedCardOption] | None = Field(
        default=None, description="Options for MCQ/EMQ cards when relevant."
    )
    correct_answers: list[str] = Field(
        default_factory=list,
        description="Identifiers or textual answers considered correct.",
    )
    rationale: AiGeneratedRationale = Field(..., description="Detailed explanation bundle.")
    connections: list[str] = Field(
        default_factory=list,
        description="Cross-links to related concepts or clinical pearls.",
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Definitions for uncommon terminology mentioned in the card.",
    )
    numerical_ranges: list[str] = Field(
        default_factory=list,
        description="Reference ranges or quantitative anchors mentioned in the stem.",
    )
    references: list[str] = Field(
        default_factory=list,
        description="Optional citations or guideline references.",
    )


class AiGeneratedCard(BaseSchema):
    card_type: CardType
    difficulty: Difficulty
    payload: AiGeneratedPayload


class AiRetentionAid(BaseSchema):
    markdown: str = Field(..., description="Markdown-formatted retention summary.")


class AiGeneratedStudyCardSet(BaseSchema):
    cards: list[AiGeneratedCard]
    retention_aid: AiRetentionAid | None = Field(
        default=None,
        description="Optional markdown retention aid for the generated set.",
    )


class StudyCardGenerationResponse(BaseSchema):
    cards: list[AiGeneratedCard]
    retention_aid: AiRetentionAid | None = None
    summary: StudyCardGenerationSummary


class StudyCardGenerationResult(BaseSchema):
    cards: list[StudyCardRead]
    retention_aid: AiRetentionAid | None = None
    summary: StudyCardGenerationSummary
    raw_generation: AiGeneratedStudyCardSet


__all__ = [
    "AiGeneratedCard",
    "AiGeneratedCardOption",
    "AiGeneratedPayload",
    "AiGeneratedRationale",
    "AiGeneratedStudyCardSet",
    "AiRetentionAid",
    "StudyCardGenerationRequest",
    "StudyCardGenerationResponse",
    "StudyCardGenerationSummary",
    "StudyCardGenerationResult",
]
