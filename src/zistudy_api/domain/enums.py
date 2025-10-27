from __future__ import annotations

from enum import Enum


class CardType(str, Enum):
    MCQ_SINGLE = "mcq_single"
    MCQ_MULTI = "mcq_multi"
    WRITTEN = "written"
    TRUE_FALSE = "true_false"
    CLOZE = "cloze"
    EMQ = "emq"
    NOTE = "note"
    FLASHCARD = "flashcard"

    @property
    def is_question(self) -> bool:
        return self in {
            CardType.MCQ_SINGLE,
            CardType.MCQ_MULTI,
            CardType.WRITTEN,
            CardType.TRUE_FALSE,
            CardType.CLOZE,
            CardType.EMQ,
        }

    @property
    def category(self) -> "CardCategory":
        return CardCategory.QUESTION if self.is_question else CardCategory.NOTE


class CardCategory(int, Enum):
    QUESTION = 1
    NOTE = 2


__all__ = ["CardCategory", "CardType"]
