from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import Field, ValidationError, model_validator

from zistudy_api.domain.schemas.base import ALLOW_EXTRA_SCHEMA_CONFIG, BaseSchema
from zistudy_api.domain.schemas.study_cards import EmqMatch

T = TypeVar("T", bound=BaseSchema)


def _maybe_model(model: type[T], value: Any) -> T | None:
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
    payload: dict[str, Any] | None = Field(default=None)


class McqSingleAnswerData(AnswerData):
    selected_option_id: str


class McqMultiAnswerData(AnswerData):
    selected_option_ids: list[str] = Field(default_factory=list)


class WrittenAnswerData(AnswerData):
    text: str


class TrueFalseAnswerData(AnswerData):
    selected: bool


class ClozeAnswerData(AnswerData):
    answers: list[str] = Field(default_factory=list)


class EmqAnswerData(AnswerData):
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


ANSWER_TYPE_ALIASES: dict[str, str] = {
    "mcq": "mcq_single",
    "mcq_single": "mcq_single",
    "mcq-single": "mcq_single",
    "mcqsingle": "mcq_single",
    "mcq_multi": "mcq_multi",
    "mcq-multi": "mcq_multi",
    "mcqmulti": "mcq_multi",
    "written": "written",
    "true_false": "true_false",
    "truefalse": "true_false",
    "tf": "true_false",
    "cloze": "cloze",
    "emq": "emq",
}


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
    if not answer_type:
        return "generic"
    lowered = answer_type.strip().lower()
    return ANSWER_TYPE_ALIASES.get(lowered, lowered)


def _coerce_bool(value: Any) -> bool | None:
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


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _parse_emq_matches(items: Any) -> list[EmqMatch]:
    matches: list[EmqMatch] = []
    if not isinstance(items, (list, tuple)):
        return matches
    for item in items:
        if isinstance(item, EmqMatch):
            matches.append(item)
            continue
        if isinstance(item, dict):
            parsed = _maybe_model(EmqMatch, item)
            if parsed is not None:
                matches.append(parsed)
            continue
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                matches.append(EmqMatch(premise_index=int(item[0]), option_index=int(item[1])))
            except Exception:  # noqa: BLE001
                continue
    return matches


def parse_answer_data(answer_type: str | None, raw_data: Any) -> AnswerData:
    if isinstance(raw_data, AnswerData):
        inferred = MODEL_TO_ANSWER_TYPE.get(type(raw_data))
        if inferred and answer_type is None:
            answer_type = inferred
        return raw_data

    normalised_type = _normalise_answer_type(answer_type)
    if isinstance(raw_data, dict):
        if normalised_type == "mcq_single":
            selected = (
                raw_data.get("selected_option_id")
                or raw_data.get("selected")
                or raw_data.get("answer")
                or raw_data.get("index")
            )
            if selected is not None:
                return McqSingleAnswerData(selected_option_id=str(selected))

        if normalised_type == "mcq_multi":
            selected = (
                raw_data.get("selected_option_ids")
                or raw_data.get("selected")
                or raw_data.get("answers")
                or raw_data.get("indices")
            )
            values = _coerce_str_list(selected)
            if values:
                return McqMultiAnswerData(selected_option_ids=values)

        if normalised_type == "written":
            text = raw_data.get("text") or raw_data.get("answer")
            if isinstance(text, str):
                return WrittenAnswerData(text=text)

        if normalised_type == "true_false":
            selected = raw_data.get("selected")
            if selected is None:
                selected = raw_data.get("answer")
            coerced = _coerce_bool(selected)
            if coerced is not None:
                return TrueFalseAnswerData(selected=coerced)

        if normalised_type == "cloze":
            answers = raw_data.get("answers") or raw_data.get("responses")
            values = _coerce_str_list(answers)
            if values:
                return ClozeAnswerData(answers=values)

        if normalised_type == "emq":
            matches = _parse_emq_matches(raw_data.get("matches") or raw_data.get("selections"))
            if matches:
                return EmqAnswerData(matches=matches)

        return GenericAnswerData(payload=raw_data)

    if isinstance(raw_data, list):
        if normalised_type == "mcq_multi":
            return McqMultiAnswerData(selected_option_ids=[str(item) for item in raw_data])
        if normalised_type == "cloze":
            return ClozeAnswerData(answers=[str(item) for item in raw_data])
        if normalised_type == "emq":
            return EmqAnswerData(matches=_parse_emq_matches(raw_data))

    if isinstance(raw_data, (str, int, float)) and normalised_type == "mcq_single":
        return McqSingleAnswerData(selected_option_id=str(raw_data))

    return GenericAnswerData(payload=raw_data if isinstance(raw_data, dict) else None)


def canonical_answer_type(answer_type: str | None, data: AnswerData) -> str:
    """Return the canonical answer type string for a parsed answer payload."""
    inferred = MODEL_TO_ANSWER_TYPE.get(type(data))
    if inferred:
        return inferred
    return _normalise_answer_type(answer_type)


def serialize_answer_data(data: AnswerData | dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, BaseSchema):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return data
    return {}


class AnswerPayload(BaseSchema):
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
    id: int
    user_id: str
    is_correct: bool | None = Field(default=None)
    created_at: datetime
    updated_at: datetime


class AnswerHistory(BaseSchema):
    items: list[AnswerRead]
    total: int
    page: int
    page_size: int


class AnswerStats(BaseSchema):
    study_card_id: int
    attempts: int
    correct: int
    accuracy: float


class StudySetProgress(BaseSchema):
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
