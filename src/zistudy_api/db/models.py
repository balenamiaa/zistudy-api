from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from zistudy_api.domain.enums import CardCategory, CardType


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


class UserAccount(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    study_sets: Mapped[list["StudySet"]] = relationship(back_populates="owner")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    study_cards: Mapped[list["StudyCard"]] = relationship(back_populates="owner")


class StudySet(Base):
    __tablename__ = "study_sets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    tags: Mapped[list["StudySetTag"]] = relationship(
        back_populates="study_set", cascade="all, delete-orphan"
    )
    cards: Mapped[list["StudySetCard"]] = relationship(
        back_populates="study_set", cascade="all, delete-orphan"
    )
    owner: Mapped[UserAccount | None] = relationship(back_populates="study_sets")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    study_sets: Mapped[list["StudySetTag"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class StudySetTag(Base):
    __tablename__ = "study_set_tags"
    __table_args__ = (UniqueConstraint("study_set_id", "tag_id", name="uq_study_set_tag"),)

    study_set_id: Mapped[int] = mapped_column(
        ForeignKey("study_sets.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    study_set: Mapped[StudySet] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="study_sets")


class StudyCard(Base):
    __tablename__ = "study_cards"

    __table_args__ = (
        Index("ix_study_cards_card_type", "card_type"),
        Index("ix_study_cards_difficulty", "difficulty"),
        Index("ix_study_cards_created_at", "created_at"),
        Index("ix_study_cards_updated_at", "updated_at"),
        Index("ix_study_cards_owner_id", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    card_type: Mapped[CardType] = mapped_column(String(50), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    search_document: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    answers: Mapped[list["Answer"]] = relationship(
        back_populates="study_card", cascade="all, delete-orphan"
    )
    study_sets: Mapped[list["StudySetCard"]] = relationship(
        back_populates="study_card", cascade="all, delete-orphan"
    )
    owner: Mapped[UserAccount | None] = relationship(back_populates="study_cards")


class StudySetCard(Base):
    __tablename__ = "study_set_cards"
    __table_args__ = (
        UniqueConstraint("study_set_id", "card_id", "card_category", name="uq_study_set_card"),
        Index("ix_study_set_cards_set_position", "study_set_id", "position"),
        Index("ix_study_set_cards_card", "card_id", "card_category"),
    )

    study_set_id: Mapped[int] = mapped_column(
        ForeignKey("study_sets.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("study_cards.id", ondelete="CASCADE"), primary_key=True
    )
    card_category: Mapped[CardCategory] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    study_set: Mapped[StudySet] = relationship(back_populates="cards")
    study_card: Mapped[StudyCard] = relationship(back_populates="study_sets")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        Index("ix_answers_user_id", "user_id"),
        Index("ix_answers_study_card_id", "study_card_id"),
        Index("ix_answers_is_correct", "is_correct"),
        Index("ix_answers_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_card_id: Mapped[int] = mapped_column(
        ForeignKey("study_cards.id", ondelete="CASCADE"), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    answer_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_correct: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    study_card: Mapped[StudyCard] = relationship(back_populates="answers")
    user: Mapped[UserAccount] = relationship()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_token_hash", "token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[UserAccount] = relationship(back_populates="refresh_tokens")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[UserAccount] = relationship(back_populates="api_keys")


class AsyncJob(Base):
    __tablename__ = "async_jobs"
    __table_args__ = (
        Index("ix_async_jobs_owner", "owner_id"),
        Index("ix_async_jobs_status", "status"),
        Index("ix_async_jobs_type", "job_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
    error: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "AsyncJob",
    "ApiKey",
    "Answer",
    "Base",
    "RefreshToken",
    "StudyCard",
    "StudySet",
    "StudySetCard",
    "StudySetTag",
    "Tag",
    "UserAccount",
    "utcnow",
]
