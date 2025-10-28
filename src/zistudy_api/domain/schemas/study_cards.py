"""Typed study card payloads and normalisation helpers."""

from __future__ import annotations

from typing import Annotated, Any, cast

from pydantic import Field, ValidationError, model_validator

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.base import ALLOW_EXTRA_SCHEMA_CONFIG, BaseSchema, TimestampedSchema
from zistudy_api.domain.schemas.common import PaginatedResponse

CARD_GENERATOR_SCHEMA_VERSION = "1.0.0"
"""Semantic version identifier for the typed study card payload contract.

Increment this value whenever any card payload structure or metadata changes in a
backward-incompatible way so downstream consumers can react to schema upgrades.
"""

Difficulty = Annotated[int, Field(ge=1, le=5)]


class CardGeneratorMetadata(BaseSchema):
    """Describe the AI run responsible for generating a card payload."""

    model: str = Field(..., description="Identifier of the model that produced the card.")
    temperature: float | None = Field(default=None)
    requested_card_count: int | None = Field(default=None)
    topics: list[str] | None = Field(default=None)
    clinical_focus: list[str] | None = Field(default=None)
    learning_objectives: list[str] | None = Field(default=None)
    preferred_card_types: list[str] | None = Field(default=None)
    existing_card_ids: list[int] | None = Field(default=None)
    sources: list[str] | None = Field(default=None)
    schema_version: str = Field(
        default=CARD_GENERATOR_SCHEMA_VERSION,
        description="Semantic version of the structured study card payload schema.",
    )

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class CardOption(BaseSchema):
    """Single multiple-choice option."""

    id: str
    text: str

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class CardRationale(BaseSchema):
    """Structured explanation describing the correct and alternative answers."""

    primary: str
    alternatives: dict[str, str] = Field(default_factory=dict)

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class BaseCardData(BaseSchema):
    """Common fields shared by all card payloads."""

    generator: CardGeneratorMetadata | None = Field(
        default=None, description="Metadata describing how the card was produced."
    )

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class NoteCardData(BaseCardData):
    """Markdown note that complements active recall questions."""

    title: str
    markdown: str


class QuestionCardData(BaseCardData):
    """Base payload for questions that expect an answer from the learner."""

    prompt: str
    rationale: CardRationale | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    connections: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    numerical_ranges: list[str] = Field(default_factory=list)


class MultipleChoiceCardData(QuestionCardData):
    """Shared structure for MCQ style cards."""

    options: list[CardOption] = Field(default_factory=list)
    correct_option_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_option_ids(self) -> MultipleChoiceCardData:
        if not self.correct_option_ids:
            raise ValueError("At least one correct option identifier is required.")
        option_ids = {option.id for option in self.options}
        missing = [identifier for identifier in self.correct_option_ids if identifier not in option_ids]
        if missing:
            raise ValueError(f"Unknown option identifiers referenced: {missing}")
        return self


class McqSingleCardData(MultipleChoiceCardData):
    """Single-answer multiple choice question."""

    @model_validator(mode="after")
    def _validate_single(self) -> McqSingleCardData:
        if len(self.correct_option_ids) != 1:
            raise ValueError("MCQ single cards must have exactly one correct option identifier.")
        return self


class McqMultiCardData(MultipleChoiceCardData):
    """Multiple-answer multiple choice question."""

    @model_validator(mode="after")
    def _validate_multi(self) -> McqMultiCardData:
        if len(self.correct_option_ids) < 2:
            raise ValueError("MCQ multi cards must have at least two correct option identifiers.")
        return self


class WrittenCardData(QuestionCardData):
    """Written response question expecting a free-text answer."""

    expected_answer: str | None = Field(default=None)


class TrueFalseCardData(QuestionCardData):
    """True/false card."""

    correct_answer: bool


class ClozeCardData(QuestionCardData):
    """Cloze deletion card capturing the hidden tokens."""

    cloze_answers: list[str] = Field(default_factory=list)


class EmqMatch(BaseSchema):
    """Mapping between EMQ premise and option."""

    premise_index: int
    option_index: int

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class EmqCardData(QuestionCardData):
    """Extended matching question payload."""

    instructions: str | None = Field(default=None)
    premises: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    matches: list[EmqMatch] = Field(default_factory=list)


class GenericCardData(BaseCardData):
    """Fallback container for payloads that we cannot normalise."""

    payload: dict[str, Any] | None = Field(default=None)


CardData = (
    NoteCardData
    | McqSingleCardData
    | McqMultiCardData
    | WrittenCardData
    | TrueFalseCardData
    | ClozeCardData
    | EmqCardData
    | GenericCardData
)


_CARD_TYPE_TO_MODEL: dict[CardType, type[BaseCardData]] = {
    CardType.NOTE: NoteCardData,
    CardType.MCQ_SINGLE: McqSingleCardData,
    CardType.MCQ_MULTI: McqMultiCardData,
    CardType.WRITTEN: WrittenCardData,
    CardType.TRUE_FALSE: TrueFalseCardData,
    CardType.CLOZE: ClozeCardData,
    CardType.EMQ: EmqCardData,
}


def _coerce_generator(value: Any) -> CardGeneratorMetadata | None:
    if value is None or isinstance(value, CardGeneratorMetadata):
        return value if isinstance(value, CardGeneratorMetadata) else None
    if isinstance(value, dict):
        return CardGeneratorMetadata.model_validate(value)
    return None


def parse_card_data(card_type: CardType | None, raw_data: Any) -> CardData:
    """Normalise stored payloads into the strongly typed card data models."""

    if isinstance(raw_data, BaseCardData):
        return cast(CardData, raw_data)

    if not isinstance(raw_data, dict):
        raise TypeError("Study card payload must be a JSON object.")

    if card_type is None:
        return GenericCardData(generator=_coerce_generator(raw_data.get("generator")), payload=raw_data)

    model = _CARD_TYPE_TO_MODEL.get(card_type)
    if model is None:
        return GenericCardData(generator=_coerce_generator(raw_data.get("generator")), payload=raw_data)

    try:
        return cast(CardData, model.model_validate(raw_data))
    except ValidationError as exc:  # pragma: no cover - surfaced to caller
        raise ValueError(f"Invalid study card payload for type {card_type.value}.") from exc


class StudyCardBase(BaseSchema):
    """Common fields for writable and readable study card representations."""

    card_type: CardType = Field(..., description="Discriminator for the study card type.")
    data: CardData = Field(..., description="Structured card content.")
    difficulty: Difficulty = Field(1, description="Difficulty on a 1–5 scale.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_data_model(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        raw_data = values.get("data")
        card_type_value = values.get("card_type")
        try:
            card_type_enum = (
                card_type_value
                if isinstance(card_type_value, CardType)
                else CardType(card_type_value)
            )
        except Exception:  # noqa: BLE001
            card_type_enum = None
        values["data"] = parse_card_data(card_type_enum, raw_data)
        return values


class StudyCardCreate(StudyCardBase):
    pass


class StudyCardUpdate(BaseSchema):
    """Partial update payload for study cards."""

    data: CardData | dict[str, Any] | None = None
    difficulty: Difficulty | None = None


class StudyCardRead(StudyCardBase, TimestampedSchema):
    """Card payload returned by the API and persistence layer."""

    id: int = Field(..., description="Primary identifier for the study card.")
    owner_id: str | None = Field(
        default=None,
        description="User identifier for the card owner. ``None`` indicates a system-owned card.",
    )


class CardSearchFilters(BaseSchema):
    """Optional filters applied during study card search."""

    card_types: list[CardType] | None = Field(default=None)
    min_difficulty: Difficulty | None = Field(default=None)
    max_difficulty: Difficulty | None = Field(default=None)
    study_set_ids: list[int] | None = Field(default=None)


class CardSearchRequest(BaseSchema):
    """Request payload for full-text search across study cards."""

    query: str | None = Field(default=None, description="Free text to match against card data.")
    filters: CardSearchFilters = Field(default_factory=CardSearchFilters)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class CardSearchResult(BaseSchema):
    """Container bundling a card and its relevance metadata."""

    card: StudyCardRead
    score: float | None = Field(
        default=None, description="Relative relevance score when available."
    )
    snippet: str | None = Field(default=None, description="Optional highlighted snippet.")


class PaginatedStudyCardResults(PaginatedResponse[CardSearchResult]):
    pass


class StudyCardCollection(PaginatedResponse[StudyCardRead]):
    pass


class StudyCardImportPayload(BaseSchema):
    """Batch import payload used for AI generated cards."""

    cards: list[StudyCardCreate] = Field(..., min_length=1)


__all__ = [
    "CARD_GENERATOR_SCHEMA_VERSION",
    "CardSearchFilters",
    "CardSearchRequest",
    "CardSearchResult",
    "CardData",
    "CardGeneratorMetadata",
    "CardOption",
    "CardRationale",
    "QuestionCardData",
    "MultipleChoiceCardData",
    "McqSingleCardData",
    "McqMultiCardData",
    "WrittenCardData",
    "TrueFalseCardData",
    "ClozeCardData",
    "EmqCardData",
    "EmqMatch",
    "PaginatedStudyCardResults",
    "StudyCardCollection",
    "StudyCardCreate",
    "StudyCardImportPayload",
    "StudyCardRead",
    "StudyCardUpdate",
    "NoteCardData",
    "GenericCardData",
    "parse_card_data",
]
