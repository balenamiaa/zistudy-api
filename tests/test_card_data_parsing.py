from __future__ import annotations

from collections.abc import Callable

import pytest

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.study_cards import (
    ClozeCardData,
    EmqCardData,
    EmqMatch,
    GenericCardData,
    McqMultiCardData,
    McqSingleCardData,
    NoteCardData,
    TrueFalseCardData,
    WrittenCardData,
    parse_card_data,
)


def _assert_mcq_single(data: McqSingleCardData) -> None:
    assert data.prompt == "Select the first-line analgesic in pregnancy."
    assert data.correct_option_ids == ["A"]
    assert [option.id for option in data.options] == ["A", "B"]


def _assert_mcq_multi(data: McqMultiCardData) -> None:
    assert data.prompt == "Which findings support nephritic syndrome?"
    assert set(data.correct_option_ids) == {"A", "C"}
    assert len(data.options) == 4


def _assert_written(data: WrittenCardData) -> None:
    assert data.expected_answer == "Acetylcholinesterase inhibitor"
    assert data.prompt.startswith("What is the antidote")


def _assert_true_false(data: TrueFalseCardData) -> None:
    assert data.correct_answer is True
    assert "beta-blocker" in data.prompt.lower()


def _assert_cloze(data: ClozeCardData) -> None:
    assert data.cloze_answers == ["hypoglycemia", "beta-blocker toxicity"]
    assert "fill in the blanks" in data.prompt.lower()


def _assert_emq(data: EmqCardData) -> None:
    assert data.instructions == "Match the stabilising agent to the arrhythmia."
    assert data.options == ["Amiodarone", "Dofetilide", "Procainamide"]
    assert data.matches == [EmqMatch(premise_index=0, option_index=2)]


def _assert_note(data: NoteCardData) -> None:
    assert data.title == "Renal pearls"
    assert data.markdown.startswith("## Renal pearls")


CARD_CASES: list[tuple[CardType, dict, type, Callable]] = [
    (
        CardType.MCQ_SINGLE,
        {
            "payload": {
                "question": "Select the first-line analgesic in pregnancy.",
                "options": [
                    {"id": "A", "text": "Acetaminophen"},
                    {"id": "B", "text": "Ibuprofen"},
                ],
                "correct_answers": ["A"],
                "rationale": {"primary": "Acetaminophen is preferred.", "alternatives": {}},
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            }
        },
        McqSingleCardData,
        _assert_mcq_single,
    ),
    (
        CardType.MCQ_MULTI,
        {
            "payload": {
                "question": "Which findings support nephritic syndrome?",
                "options": [
                    {"id": "A", "text": "Red blood cell casts"},
                    {"id": "B", "text": "Fatty casts"},
                    {"id": "C", "text": "Hematuria"},
                    {"id": "D", "text": "Polyuria"},
                ],
                "correct_answers": ["A", "C"],
                "rationale": {"primary": "Cast findings support the diagnosis.", "alternatives": {}},
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            }
        },
        McqMultiCardData,
        _assert_mcq_multi,
    ),
    (
        CardType.WRITTEN,
        {
            "payload": {
                "question": "What is the antidote for organophosphate poisoning?",
                "correct_answers": ["Acetylcholinesterase inhibitor"],
                "rationale": {"primary": "Pralidoxime reactivates acetylcholinesterase.", "alternatives": {}},
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            }
        },
        WrittenCardData,
        _assert_written,
    ),
    (
        CardType.TRUE_FALSE,
        {
            "payload": {
                "question": "True or False: Intravenous glucagon reverses beta-blocker toxicity.",
                "correct_answers": ["true"],
                "rationale": {"primary": "Glucagon bypasses beta receptors.", "alternatives": {}},
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            }
        },
        TrueFalseCardData,
        _assert_true_false,
    ),
    (
        CardType.CLOZE,
        {
            "payload": {
                "question": "Fill in the blanks for the management of __ and __.",
                "correct_answers": ["hypoglycemia", "beta-blocker toxicity"],
                "rationale": {"primary": "Key steps in management.", "alternatives": {}},
                "glossary": {},
                "connections": [],
                "references": [],
                "numerical_ranges": [],
            }
        },
        ClozeCardData,
        _assert_cloze,
    ),
    (
        CardType.EMQ,
        {
            "payload": {
                "question": "Match the stabilising agent to the arrhythmia.",
                "instructions": "Match the stabilising agent to the arrhythmia.",
                "references": ["Use once per option."],
                "connections": [
                    "Wide-complex tachycardia",
                ],
                "options": ["Amiodarone", "Dofetilide", "Procainamide"],
                "matches": [{"premise_index": 0, "option_index": 2}],
                "rationale": {"primary": "Procainamide stabilises wide-complex tachycardia.", "alternatives": {}},
                "glossary": {},
                "numerical_ranges": [],
            }
        },
        EmqCardData,
        _assert_emq,
    ),
    (
        CardType.NOTE,
        {
            "payload": {
                "markdown": "## Renal pearls\n- RBC casts imply nephritic syndrome",
                "heading": "Renal pearls",
            }
        },
        NoteCardData,
        _assert_note,
    ),
]


@pytest.mark.parametrize("card_type, raw, model_type, verifier", CARD_CASES)
def test_parse_card_data_converts_legacy_payloads(
    card_type: CardType,
    raw: dict,
    model_type: type,
    verifier: Callable[[object], None],
) -> None:
    parsed = parse_card_data(card_type, raw)
    assert isinstance(parsed, model_type)
    verifier(parsed)


def test_parse_card_data_returns_generic_when_invalid() -> None:
    raw = {"payload": {"question": 123, "rationale": {"primary": "", "alternatives": {}}}}
    parsed = parse_card_data(CardType.MCQ_SINGLE, raw)
    assert isinstance(parsed, GenericCardData)
    assert parsed.payload is not None
