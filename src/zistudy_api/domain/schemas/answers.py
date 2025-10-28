"""Typed answer payloads plus helpers for normalising historic data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import Field, ValidationError, model_validator

from zistudy_api.domain.schemas.base import ALLOW_EXTRA_SCHEMA_CONFIG, BaseSchema
from zistudy_api.domain.schemas.study_cards import EmqMatch

T = TypeVar("T", bound=BaseSchema)


def _maybe_model(model: type[T], value: Any) -> T | None:
    """Best-effort validator used by the normalisation helpers."""

    if value is None or isinstance(value, model):
        return value if isinstance(value, model) else None
    if isinstance(value, dict):
        try:
            return model.model_validate(value)
        except ValidationError:
            return None
    return None


class AnswerData(BaseSchema):
    """Base class for structured answer payloads."""

    model_config = ALLOW_EXTRA_SCHEMA_CONFIG


class GenericAnswerData(AnswerData):
    """Fallback payload for legacy or untyped answer submissions."""

    payload: dict[str, Any] | None = Field(default=None)


class McqSingleAnswerData(AnswerData):
    """Learner answer for single-choice MCQ cards."""

    selected_option_id: str


class McqMultiAnswerData(AnswerData):
    """Learner answer for multi-select MCQ cards."""

    selected_option_ids: list[str] = Field(default_factory=list)


class WrittenAnswerData(AnswerData):
    """Learner answer containing free text."""

    text: str


class TrueFalseAnswerData(AnswerData):
    """Learner answer for true/false cards."""

    selected: bool


class ClozeAnswerData(AnswerData):
    """Learner responses for cloze deletions."""

    answers: list[str] = Field(default_factory=list)


class EmqAnswerData(AnswerData):
    """Learner selections for extended matching questions."""

    matches: list[EmqMatch] = Field(default_factory=list)


AnswerDataUnion = (
    McqSingleAnswerData
    | McqMultiAnswerData
    | WrittenAnswerData
    | TrueFalseAnswerData
    | ClozeAnswerData
    | EmqAnswerData
    | GenericAnswerData
)


ANSWER_TYPE_TO_MODEL: dict[str, type[AnswerData]] = {
    "mcq_single": McqSingleAnswerData,
    "mcq_multi": McqMultiAnswerData,
    "written": WrittenAnswerData,
    "true_false": TrueFalseAnswerData,
    "cloze": ClozeAnswerData,
    "emq": EmqAnswerData,
}


MODEL_TO_ANSWER_TYPE: dict[type[AnswerData], str] = {
    model: answer_type for answer_type, model in ANSWER_TYPE_TO_MODEL.items()
}


def _normalise_answer_type(answer_type: str | None) -> str:
    """Collapse aliases and missing answer types into a canonical discriminator."""

    if not answer_type:
        return "generic"
    return answer_type.strip().lower()


def parse_answer_data(answer_type: str | None, raw_data: Any) -> AnswerData:
    """Normalise persisted answer payloads into typed models."""

    if isinstance(raw_data, AnswerData):
        inferred = MODEL_TO_ANSWER_TYPE.get(type(raw_data))
        if inferred and answer_type is None:
            answer_type = inferred
        return raw_data

    if not isinstance(raw_data, dict):
        raise TypeError("Answer payload must be a JSON object.")

    normalised_type = _normalise_answer_type(answer_type)
    model = ANSWER_TYPE_TO_MODEL.get(normalised_type)
    if model is None:
        return GenericAnswerData(payload=raw_data)

    try:
        return model.model_validate(raw_data)
    except ValidationError as exc:  # pragma: no cover - surfaced to caller
        raise ValueError(f"Invalid answer payload for type {normalised_type}.") from exc


def canonical_answer_type(answer_type: str | None, data: AnswerData) -> str:
    """Return the canonical answer type string for a parsed answer payload."""
    inferred = MODEL_TO_ANSWER_TYPE.get(type(data))
    if inferred:
        return inferred
    return _normalise_answer_type(answer_type)


def serialize_answer_data(data: AnswerData | dict[str, Any]) -> dict[str, Any]:
    """Render payloads back to primitives for persistence."""

    if isinstance(data, BaseSchema):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return data
    return {}


class AnswerPayload(BaseSchema):
    """Envelope for storing learner answers."""

    study_card_id: int
    answer_type: str = Field(default="generic", description="Answer type discriminator.")
    data: AnswerData | dict[str, Any] = Field(default_factory=dict)
    expected_answer: dict[str, Any] | None = Field(default=None)
    evaluation_notes: str | None = None
    is_correct: bool | None = Field(default=None)
    latency_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        raw_data = values.get("data")
        answer_type = values.get("answer_type")
        parsed = parse_answer_data(answer_type, raw_data)
        values["data"] = parsed
        values["answer_type"] = canonical_answer_type(answer_type, parsed)
        return values


class AnswerCreate(AnswerPayload):
    pass


class AnswerRead(AnswerPayload):
    """Answer payload returned by the API."""

    id: int
    user_id: str
    is_correct: bool | None = Field(default=None)
    created_at: datetime
    updated_at: datetime


class AnswerHistory(BaseSchema):
    """Paginated answer history for a learner."""

    items: list[AnswerRead]
    total: int
    page: int
    page_size: int


class AnswerStats(BaseSchema):
    """Aggregate answer statistics for a card."""

    study_card_id: int
    attempts: int
    correct: int
    accuracy: float


class StudySetProgress(BaseSchema):
    """Progress indicators for a learner within a study set."""

    study_set_id: int
    total_cards: int
    attempted_cards: int
    correct_cards: int
    accuracy: float
    last_answered_at: datetime | None


__all__ = [
    "AnswerCreate",
    "AnswerData",
    "AnswerDataUnion",
    "AnswerHistory",
    "AnswerPayload",
    "AnswerRead",
    "AnswerStats",
    "canonical_answer_type",
    "ClozeAnswerData",
    "EmqAnswerData",
    "GenericAnswerData",
    "McqMultiAnswerData",
    "McqSingleAnswerData",
    "parse_answer_data",
    "serialize_answer_data",
    "StudySetProgress",
    "TrueFalseAnswerData",
    "WrittenAnswerData",
]
