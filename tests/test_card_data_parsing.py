from __future__ import annotations

import pytest

import zistudy_api.domain.schemas.study_cards as card_schemas
from zistudy_api.domain.enums import CardType

GENERATOR = card_schemas.CardGeneratorMetadata(model="gemini-2.5-pro", temperature=0.2)


CARD_CASES = [
    (
        CardType.MCQ_SINGLE,
        card_schemas.McqSingleCardData(
            generator=GENERATOR,
            prompt="Select the first-line analgesic in pregnancy.",
            rationale=card_schemas.CardRationale(primary="Acetaminophen is preferred.", alternatives={}),
            options=[
                card_schemas.CardOption(id="A", text="Acetaminophen"),
                card_schemas.CardOption(id="B", text="Ibuprofen"),
            ],
            correct_option_ids=["A"],
            glossary={},
            connections=[],
            references=[],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.MCQ_MULTI,
        card_schemas.McqMultiCardData(
            generator=GENERATOR,
            prompt="Which findings support nephritic syndrome?",
            rationale=card_schemas.CardRationale(primary="Cast findings support the diagnosis.", alternatives={}),
            options=[
                card_schemas.CardOption(id="A", text="Red blood cell casts"),
                card_schemas.CardOption(id="B", text="Fatty casts"),
                card_schemas.CardOption(id="C", text="Hematuria"),
                card_schemas.CardOption(id="D", text="Polyuria"),
            ],
            correct_option_ids=["A", "C"],
            glossary={},
            connections=[],
            references=[],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.WRITTEN,
        card_schemas.WrittenCardData(
            generator=GENERATOR,
            prompt="What is the antidote for organophosphate poisoning?",
            rationale=card_schemas.CardRationale(primary="Pralidoxime reactivates acetylcholinesterase.", alternatives={}),
            expected_answer="Acetylcholinesterase inhibitor",
            glossary={},
            connections=[],
            references=[],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.TRUE_FALSE,
        card_schemas.TrueFalseCardData(
            generator=GENERATOR,
            prompt="True or False: Intravenous glucagon reverses beta-blocker toxicity.",
            rationale=card_schemas.CardRationale(primary="Glucagon bypasses beta receptors.", alternatives={}),
            correct_answer=True,
            glossary={},
            connections=[],
            references=[],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.CLOZE,
        card_schemas.ClozeCardData(
            generator=GENERATOR,
            prompt="Fill in the blanks for the management of __ and __.",
            rationale=card_schemas.CardRationale(primary="Key steps in management.", alternatives={}),
            cloze_answers=["hypoglycemia", "beta-blocker toxicity"],
            glossary={},
            connections=[],
            references=[],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.EMQ,
        card_schemas.EmqCardData(
            generator=GENERATOR,
            prompt="Match the stabilising agent to the arrhythmia.",
            instructions="Match the stabilising agent to the arrhythmia.",
            rationale=card_schemas.CardRationale(primary="Procainamide stabilises wide-complex tachycardia.", alternatives={}),
            options=["Amiodarone", "Dofetilide", "Procainamide"],
            premises=["Wide-complex tachycardia"],
            matches=[card_schemas.EmqMatch(premise_index=0, option_index=2)],
            glossary={},
            connections=[],
            references=["Use once per option."],
            numerical_ranges=[],
        ),
    ),
    (
        CardType.NOTE,
        card_schemas.NoteCardData(
            generator=GENERATOR,
            title="Renal pearls",
            markdown="## Renal pearls\n- RBC casts imply nephritic syndrome",
        ),
    ),
]


@pytest.mark.parametrize("card_type, model", CARD_CASES)
def test_parse_card_data_round_trips_json(card_type: CardType, model) -> None:
    raw = model.model_dump(mode="json")
    parsed = card_schemas.parse_card_data(card_type, raw)
    assert isinstance(parsed, type(model))
    assert parsed.model_dump(mode="json") == raw


def test_parse_card_data_returns_generic_when_invalid() -> None:
    raw = {"unexpected": "payload"}
    parsed = card_schemas.parse_card_data(None, raw)
    assert isinstance(parsed, card_schemas.GenericCardData)
    assert parsed.payload == raw


def test_parse_card_data_note_without_heading_uses_default_title() -> None:
    raw = card_schemas.NoteCardData(
        generator=None, title="Note", markdown="Clinical pearls\n- Keep hydrated"
    ).model_dump(
        mode="json"
    )

    parsed = card_schemas.parse_card_data(CardType.NOTE, raw)

    assert isinstance(parsed, card_schemas.NoteCardData)
    assert parsed.title == "Note"


def test_parse_card_data_raises_for_invalid_payload() -> None:
    with pytest.raises(ValueError):
        card_schemas.parse_card_data(CardType.MCQ_SINGLE, {"prompt": "Missing options"})
