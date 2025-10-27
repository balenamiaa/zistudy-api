from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zistudy_api.domain.schemas.answers import (
    AnswerPayload,
    AnswerRead,
    ClozeAnswerData,
    EmqAnswerData,
    McqMultiAnswerData,
    McqSingleAnswerData,
    TrueFalseAnswerData,
    WrittenAnswerData,
    canonical_answer_type,
    parse_answer_data,
)
from zistudy_api.services.answers import AnswerService


def _assert_mcq_single(data: object) -> None:
    typed = cast(McqSingleAnswerData, data)
    assert typed.selected_option_id == "B"


def _assert_mcq_multi(data: object) -> None:
    typed = cast(McqMultiAnswerData, data)
    assert set(typed.selected_option_ids) == {"A", "D"}


def _assert_written(data: object) -> None:
    typed = cast(WrittenAnswerData, data)
    assert typed.text == "Anserine bursa"


def _assert_true_false(data: object) -> None:
    typed = cast(TrueFalseAnswerData, data)
    assert typed.selected is False


def _assert_cloze(data: object) -> None:
    typed = cast(ClozeAnswerData, data)
    assert typed.answers == ["first gap", "second gap"]


def _assert_emq(data: object) -> None:
    typed = cast(EmqAnswerData, data)
    assert typed.matches[0].option_index == 2


ANSWER_CASES: list[tuple[str, object, type, str, Callable[[object], None]]] = [
    ("mcq", {"selected": "B"}, McqSingleAnswerData, "mcq_single", _assert_mcq_single),
    (
        "mcq-multi",
        {"selected": ["A", "D"]},
        McqMultiAnswerData,
        "mcq_multi",
        _assert_mcq_multi,
    ),
    (
        "written",
        {"text": "Anserine bursa"},
        WrittenAnswerData,
        "written",
        _assert_written,
    ),
    ("true_false", {"selected": "false"}, TrueFalseAnswerData, "true_false", _assert_true_false),
    (
        "cloze",
        ["first gap", "second gap"],
        ClozeAnswerData,
        "cloze",
        _assert_cloze,
    ),
    (
        "emq",
        {"matches": [{"premise_index": 0, "option_index": 2}]},
        EmqAnswerData,
        "emq",
        _assert_emq,
    ),
]


@pytest.mark.parametrize("answer_type, raw, model_type, canonical, verifier", ANSWER_CASES)
def test_parse_answer_data_recognises_aliases(
    answer_type: str,
    raw: object,
    model_type: type,
    canonical: str,
    verifier: Callable[[object], None],
) -> None:
    parsed = parse_answer_data(answer_type, raw)
    assert isinstance(parsed, model_type)
    verifier(parsed)
    assert canonical_answer_type(answer_type, parsed) == canonical


@pytest.mark.parametrize("answer_type, raw, model_type, canonical, verifier", ANSWER_CASES)
def test_answer_payload_normalises_types(
    answer_type: str,
    raw: object,
    model_type: type,
    canonical: str,
    verifier: Callable[[object], None],
) -> None:
    payload = AnswerPayload.model_validate(
        {"study_card_id": 1, "answer_type": answer_type, "data": raw}
    )
    assert isinstance(payload.data, model_type)
    verifier(payload.data)
    assert payload.answer_type == canonical


def test_answer_service_to_read_model_returns_canonical_type() -> None:
    service = AnswerService(session=cast(AsyncSession, SimpleNamespace()))
    entity = SimpleNamespace(
        id=42,
        user_id="user-1",
        study_card_id=7,
        answer_type="mcq",
        data={"selected": "B"},
        is_correct=1,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )

    read = service._to_read_model(entity)  # type: ignore[arg-type]

    assert isinstance(read, AnswerRead)
    assert isinstance(read.data, McqSingleAnswerData)
    assert read.answer_type == "mcq_single"
    assert read.is_correct is True
