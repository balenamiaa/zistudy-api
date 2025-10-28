from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import zistudy_api.domain.schemas.answers as answer_schemas
from zistudy_api.services.answers import AnswerService

ANSWER_CASES = [
    (
        "mcq_single",
        answer_schemas.McqSingleAnswerData(selected_option_id="B"),
        answer_schemas.McqSingleAnswerData,
    ),
    (
        "mcq_multi",
        answer_schemas.McqMultiAnswerData(selected_option_ids=["A", "D"]),
        answer_schemas.McqMultiAnswerData,
    ),
    (
        "written",
        answer_schemas.WrittenAnswerData(text="Anserine bursa"),
        answer_schemas.WrittenAnswerData,
    ),
    (
        "true_false",
        answer_schemas.TrueFalseAnswerData(selected=False),
        answer_schemas.TrueFalseAnswerData,
    ),
    (
        "cloze",
        answer_schemas.ClozeAnswerData(answers=["first gap", "second gap"]),
        answer_schemas.ClozeAnswerData,
    ),
    (
        "emq",
        answer_schemas.EmqAnswerData(
            matches=[answer_schemas.EmqMatch(premise_index=0, option_index=2)]
        ),
        answer_schemas.EmqAnswerData,
    ),
]


@pytest.mark.parametrize("answer_type, answer_model, expected_type", ANSWER_CASES)
def test_parse_answer_data_round_trips(
    answer_type: str,
    answer_model: answer_schemas.AnswerData,
    expected_type: type,
) -> None:
    raw = answer_model.model_dump(mode="json")
    parsed = answer_schemas.parse_answer_data(answer_type, raw)
    assert isinstance(parsed, expected_type)
    assert parsed.model_dump(mode="json") == raw
    assert answer_schemas.canonical_answer_type(answer_type, parsed) == answer_type


@pytest.mark.parametrize("answer_type, answer_model, expected_type", ANSWER_CASES)
def test_answer_payload_normalises_types(
    answer_type: str,
    answer_model: answer_schemas.AnswerData,
    expected_type: type,
) -> None:
    payload = answer_schemas.AnswerPayload.model_validate(
        {
            "study_card_id": 1,
            "answer_type": answer_type,
            "data": answer_model.model_dump(mode="json"),
        }
    )
    assert isinstance(payload.data, expected_type)
    assert payload.answer_type == answer_type


def test_parse_answer_data_generic_when_type_unknown() -> None:
    raw = {"arbitrary": "payload"}
    parsed = answer_schemas.parse_answer_data("custom", raw)
    assert isinstance(parsed, answer_schemas.GenericAnswerData)
    assert parsed.payload == raw


def test_parse_answer_data_raises_for_non_object() -> None:
    with pytest.raises(TypeError):
        answer_schemas.parse_answer_data("mcq_single", "invalid")


def test_answer_service_to_read_model_returns_canonical_type() -> None:
    service = AnswerService(session=cast(AsyncSession, SimpleNamespace()))
    entity = SimpleNamespace(
        id=42,
        user_id="user-1",
        study_card_id=7,
        answer_type="mcq_single",
        data={"selected_option_id": "B"},
        is_correct=1,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )

    read = service._to_read_model(entity)  # type: ignore[arg-type]
    assert isinstance(read, answer_schemas.AnswerRead)
    assert isinstance(read.data, answer_schemas.McqSingleAnswerData)
    assert read.answer_type == "mcq_single"
    assert read.is_correct is True
