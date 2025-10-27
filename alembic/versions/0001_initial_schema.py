"""Initial schema

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2025-01-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "study_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "owner_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "study_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("card_type", sa.String(length=50), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_study_cards_card_type", "study_cards", ["card_type"])
    op.create_index("ix_study_cards_difficulty", "study_cards", ["difficulty"])
    op.create_index("ix_study_cards_created_at", "study_cards", ["created_at"])
    op.create_index("ix_study_cards_updated_at", "study_cards", ["updated_at"])

    op.create_table(
        "study_set_tags",
        sa.Column(
            "study_set_id",
            sa.Integer(),
            sa.ForeignKey("study_sets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_unique_constraint("uq_study_set_tag", "study_set_tags", ["study_set_id", "tag_id"])

    op.create_table(
        "study_set_cards",
        sa.Column(
            "study_set_id",
            sa.Integer(),
            sa.ForeignKey("study_sets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("study_cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("card_category", sa.Integer(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint(
        "uq_study_set_card", "study_set_cards", ["study_set_id", "card_id", "card_category"]
    )
    op.create_index(
        "ix_study_set_cards_set_position", "study_set_cards", ["study_set_id", "position"]
    )
    op.create_index("ix_study_set_cards_card", "study_set_cards", ["card_id", "card_category"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "study_card_id",
            sa.Integer(),
            sa.ForeignKey("study_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer_type", sa.String(length=50), nullable=False),
        sa.Column("is_correct", sa.Integer(), nullable=False, server_default="2"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_unique_constraint("uq_answer_user_card", "answers", ["user_id", "study_card_id"])
    op.create_index("ix_answers_user_id", "answers", ["user_id"])
    op.create_index("ix_answers_study_card_id", "answers", ["study_card_id"])
    op.create_index("ix_answers_is_correct", "answers", ["is_correct"])
    op.create_index("ix_answers_created_at", "answers", ["created_at"])

    op.create_table(
        "async_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_async_jobs_owner", "async_jobs", ["owner_id"])
    op.create_index("ix_async_jobs_status", "async_jobs", ["status"])
    op.create_index("ix_async_jobs_type", "async_jobs", ["job_type"])


def downgrade() -> None:
    op.drop_index("ix_answers_created_at", table_name="answers")
    op.drop_index("ix_answers_is_correct", table_name="answers")
    op.drop_index("ix_answers_study_card_id", table_name="answers")
    op.drop_index("ix_answers_user_id", table_name="answers")
    op.drop_constraint("uq_answer_user_card", "answers", type_="unique")
    op.drop_table("answers")

    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_study_set_cards_card", table_name="study_set_cards")
    op.drop_index("ix_study_set_cards_set_position", table_name="study_set_cards")
    op.drop_constraint("uq_study_set_card", "study_set_cards", type_="unique")
    op.drop_table("study_set_cards")

    op.drop_constraint("uq_study_set_tag", "study_set_tags", type_="unique")
    op.drop_table("study_set_tags")

    op.drop_index("ix_study_cards_updated_at", table_name="study_cards")
    op.drop_index("ix_study_cards_created_at", table_name="study_cards")
    op.drop_index("ix_study_cards_difficulty", table_name="study_cards")
    op.drop_index("ix_study_cards_card_type", table_name="study_cards")
    op.drop_table("study_cards")

    op.drop_table("study_sets")

    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_async_jobs_type", table_name="async_jobs")
    op.drop_index("ix_async_jobs_status", table_name="async_jobs")
    op.drop_index("ix_async_jobs_owner", table_name="async_jobs")
    op.drop_table("async_jobs")
