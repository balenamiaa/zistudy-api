from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from zistudy_api.domain.enums import CardType
from zistudy_api.domain.schemas.base import BaseSchema, TimestampedSchema
from zistudy_api.domain.schemas.common import PaginatedResponse
from zistudy_api.domain.schemas.study_cards import StudyCardRead
from zistudy_api.domain.schemas.tags import TagRead

TitleStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]

DescriptionStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=1000),
]


class StudySetBase(BaseSchema):
    title: TitleStr
    description: DescriptionStr | None = None
    is_private: bool = True


class StudySetCreate(StudySetBase):
    tag_names: list[str] = Field(default_factory=list, max_length=20)


class StudySetUpdate(BaseSchema):
    title: TitleStr | None = None
    description: DescriptionStr | None = None
    is_private: bool | None = None
    tag_names: list[str] | None = Field(default=None, description="Replace existing tags.")


class StudySetRead(StudySetBase, TimestampedSchema):
    id: int = Field(..., description="Study set identifier.", gt=0, examples=[1])
    owner_id: str | None = Field(default=None, description="Identifier of the owner if any.")

    def can_access(self, user_id: str | None) -> bool:
        if not self.is_private:
            return True
        if not self.owner_id or not user_id:
            return False
        return self.owner_id == user_id

    def can_modify(self, user_id: str | None) -> bool:
        if not self.owner_id or not user_id:
            return False
        return self.owner_id == user_id


class StudySetWithMeta(BaseSchema):
    study_set: StudySetRead
    tags: list[TagRead]
    card_count: int = Field(0, ge=0)
    question_count: int = Field(0, ge=0)
    owner_email: str | None = None


class StudySetForCard(BaseSchema):
    study_set: StudySetRead
    contains_card: bool
    card_count: int
    owner_email: str | None = None
    tags: list[TagRead] = Field(default_factory=list)


class AddCardsToSet(BaseSchema):
    study_set_id: int
    card_ids: list[int]
    card_type: CardType


class RemoveCardsFromSet(BaseSchema):
    study_set_id: int
    card_ids: list[int]
    card_type: CardType


class BulkAddToSets(BaseSchema):
    study_set_ids: list[int]
    card_ids: list[int]
    card_type: CardType


class PaginatedStudySets(PaginatedResponse[StudySetWithMeta]):
    pass


class StudySetCardEntry(BaseSchema):
    card: StudyCardRead
    position: int = Field(..., ge=0)


class StudySetCardsPage(PaginatedResponse[StudySetCardEntry]):
    pass


class BulkOperationResult(BaseSchema):
    success_count: int = Field(0, ge=0)
    error_count: int = Field(0, ge=0)
    errors: list[str] = Field(default_factory=list)
    affected_ids: list[int] = Field(default_factory=list)


class BulkDeleteStudySets(BaseSchema):
    study_set_ids: list[int] = Field(..., min_length=1)


class CloneStudySetsRequest(BaseSchema):
    study_set_ids: list[int] = Field(..., min_length=1)
    title_prefix: str | None = Field(default=None, max_length=255)


class ExportStudySetsRequest(BaseSchema):
    study_set_ids: list[int] = Field(..., min_length=1)


__all__ = [
    "AddCardsToSet",
    "BulkDeleteStudySets",
    "BulkAddToSets",
    "BulkOperationResult",
    "PaginatedStudySets",
    "StudySetCardsPage",
    "StudySetCardEntry",
    "RemoveCardsFromSet",
    "StudySetCreate",
    "StudySetForCard",
    "StudySetRead",
    "StudySetUpdate",
    "StudySetWithMeta",
    "CloneStudySetsRequest",
    "ExportStudySetsRequest",
]
