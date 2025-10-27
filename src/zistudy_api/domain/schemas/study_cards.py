from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import Field, ValidationError, model_validator

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.base import ALLOW_EXTRA_SCHEMA_CONFIG, BaseSchema, TimestampedSchema
from zistudy_api.domain.schemas.common import PaginatedResponse

CARD_GENERATOR_SCHEMA_VERSION = "1.0.0"
"""Semantic version identifier for the typed study card payload contract.

Increment this value whenever any card payload structure or metadata changes in a
backward-incompatible way so downstream consumers can react to schema upgrades.
"""

T = TypeVar("T", bound=BaseSchema)

Difficulty = Annotated[int, Field(ge=1, le=5)]


class CardGeneratorMetadata(BaseSchema):
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
    id: str
    text: str

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class CardRationale(BaseSchema):
    primary: str
    alternatives: dict[str, str] = Field(default_factory=dict)

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class BaseCardData(BaseSchema):
    generator: CardGeneratorMetadata | None = Field(
        default=None, description="Metadata describing how the card was produced."
    )

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class NoteCardData(BaseCardData):
    title: str
    markdown: str


class QuestionCardData(BaseCardData):
    prompt: str
    rationale: CardRationale | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    connections: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    numerical_ranges: list[str] = Field(default_factory=list)


class MultipleChoiceCardData(QuestionCardData):
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
    @model_validator(mode="after")
    def _validate_single(self) -> McqSingleCardData:
        if len(self.correct_option_ids) != 1:
            raise ValueError("MCQ single cards must have exactly one correct option identifier.")
        return self


class McqMultiCardData(MultipleChoiceCardData):
    @model_validator(mode="after")
    def _validate_multi(self) -> McqMultiCardData:
        if len(self.correct_option_ids) < 2:
            raise ValueError("MCQ multi cards must have at least two correct option identifiers.")
        return self


class WrittenCardData(QuestionCardData):
    expected_answer: str | None = Field(default=None)


class TrueFalseCardData(QuestionCardData):
    correct_answer: bool


class ClozeCardData(QuestionCardData):
    cloze_answers: list[str] = Field(default_factory=list)


class EmqMatch(BaseSchema):
    premise_index: int
    option_index: int

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class EmqCardData(QuestionCardData):
    instructions: str | None = Field(default=None)
    premises: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    matches: list[EmqMatch] = Field(default_factory=list)


class GenericCardData(BaseCardData):
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


def _maybe_model(model: type[T], value: Any) -> T | None:
    if value is None or isinstance(value, model):
        return value if isinstance(value, model) else None
    if isinstance(value, dict):
        try:
            return model.model_validate(value)
        except ValidationError:
            return None
    return None


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "1", "yes", "y"}:
            return True
        if lowered in {"false", "f", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


_CARD_TYPE_TO_MODEL: dict[CardType, type[BaseCardData]] = {
    CardType.NOTE: NoteCardData,
    CardType.MCQ_SINGLE: McqSingleCardData,
    CardType.MCQ_MULTI: McqMultiCardData,
    CardType.WRITTEN: WrittenCardData,
    CardType.TRUE_FALSE: TrueFalseCardData,
    CardType.CLOZE: ClozeCardData,
    CardType.EMQ: EmqCardData,
}


def _convert_card_data(card_type: CardType | None, raw_data: Any) -> CardData | None:
    if not isinstance(raw_data, dict):
        return None

    generator = _maybe_model(CardGeneratorMetadata, raw_data.get("generator"))
    payload = raw_data.get("payload")
    payload_dict = payload if isinstance(payload, dict) else raw_data

    if card_type == CardType.NOTE:
        markdown = payload_dict.get("markdown")
        if isinstance(markdown, str):
            title_value = payload_dict.get("title")
            title_str = title_value.strip() if isinstance(title_value, str) and title_value.strip() else None
            if not title_str:
                heading = payload_dict.get("heading")
                if isinstance(heading, str) and heading.strip():
                    title_str = heading.strip()
            if not title_str:
                title_str = "Note"
            return NoteCardData(generator=generator, title=title_str, markdown=markdown)
        return None

    if card_type in _CARD_TYPE_TO_MODEL and card_type is not None:
        prompt = payload_dict.get("prompt") or payload_dict.get("question")
        if not isinstance(prompt, str):
            return None
        rationale = _maybe_model(CardRationale, payload_dict.get("rationale"))
        base_kwargs = {
            "generator": generator,
            "prompt": prompt,
            "rationale": rationale,
            "glossary": _coerce_dict(payload_dict.get("glossary")),
            "connections": _coerce_str_list(payload_dict.get("connections")),
            "references": _coerce_str_list(payload_dict.get("references")),
            "numerical_ranges": _coerce_str_list(
                payload_dict.get("numerical_ranges") or payload_dict.get("numericalRanges")
            ),
        }

        if card_type in {CardType.MCQ_SINGLE, CardType.MCQ_MULTI}:
            options: list[CardOption] = []
            for option in payload_dict.get("options") or []:
                try:
                    options.append(CardOption.model_validate(option))
                except ValidationError:
                    continue
            if not options:
                return None
            correct_ids = _coerce_str_list(
                payload_dict.get("correct_option_ids") or payload_dict.get("correct_answers")
            )
            if card_type == CardType.MCQ_SINGLE:
                if len(correct_ids) != 1:
                    return None
                return McqSingleCardData(
                    **base_kwargs,
                    options=options,
                    correct_option_ids=[correct_ids[0]],
                )
            if len(correct_ids) < 2:
                return None
            return McqMultiCardData(
                **base_kwargs,
                options=options,
                correct_option_ids=correct_ids,
            )

        if card_type == CardType.WRITTEN:
            correct_answers = _coerce_str_list(payload_dict.get("correct_answers"))
            expected = correct_answers[0] if correct_answers else None
            return WrittenCardData(**base_kwargs, expected_answer=expected)

        if card_type == CardType.TRUE_FALSE:
            correct_answers = _coerce_str_list(payload_dict.get("correct_answers"))
            answer = _parse_bool(correct_answers[0]) if correct_answers else None
            if answer is None:
                return None
            return TrueFalseCardData(**base_kwargs, correct_answer=answer)

        if card_type == CardType.CLOZE:
            return ClozeCardData(
                **base_kwargs,
                cloze_answers=_coerce_str_list(
                    payload_dict.get("cloze_answers") or payload_dict.get("correct_answers")
                ),
            )

        if card_type == CardType.EMQ:
            premises = _coerce_str_list(payload_dict.get("premises"))
            emq_options = _coerce_str_list(payload_dict.get("options"))
            matches_raw = payload_dict.get("matches") or payload_dict.get("correct_matches") or []
            matches: list[EmqMatch] = []
            for match in matches_raw:
                try:
                    matches.append(EmqMatch.model_validate(match))
                except ValidationError:
                    continue
            return EmqCardData(
                **base_kwargs,
                instructions=payload_dict.get("instructions"),
                premises=premises,
                options=emq_options,
                matches=matches,
            )

    return None


def parse_card_data(card_type: CardType | None, raw_data: Any) -> CardData:
    if isinstance(
        raw_data,
        (
            NoteCardData,
            McqSingleCardData,
            McqMultiCardData,
            WrittenCardData,
            TrueFalseCardData,
            ClozeCardData,
            EmqCardData,
            GenericCardData,
        ),
    ):
        return raw_data

    converted = _convert_card_data(card_type, raw_data)
    if converted is not None:
        return converted

    generator = _maybe_model(
        CardGeneratorMetadata,
        raw_data.get("generator") if isinstance(raw_data, dict) else None,
    )
    payload_dict: dict[str, Any] | None = None
    if isinstance(raw_data, dict):
        payload_field = raw_data.get("payload")
        payload_dict = payload_field if isinstance(payload_field, dict) else raw_data
    return GenericCardData(generator=generator, payload=payload_dict)


class StudyCardBase(BaseSchema):
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
    data: CardData | dict[str, Any] | None = None
    difficulty: Difficulty | None = None


class StudyCardRead(StudyCardBase, TimestampedSchema):
    id: int = Field(..., description="Primary identifier for the study card.")


class CardSearchFilters(BaseSchema):
    card_types: list[CardType] | None = Field(default=None)
    min_difficulty: Difficulty | None = Field(default=None)
    max_difficulty: Difficulty | None = Field(default=None)
    study_set_ids: list[int] | None = Field(default=None)


class CardSearchRequest(BaseSchema):
    query: str | None = Field(default=None, description="Free text to match against card data.")
    filters: CardSearchFilters = Field(default_factory=CardSearchFilters)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class CardSearchResult(BaseSchema):
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
