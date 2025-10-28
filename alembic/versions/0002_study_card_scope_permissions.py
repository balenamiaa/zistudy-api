"""Add study card ownership and sanitised search document.

Revision ID: 0002_study_card_scope_permissions
Revises: 0001_initial_schema
Create Date: 2024-11-24 00:00:00.000000
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_study_card_scope_permissions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


HIDDEN_SEARCH_FIELDS = frozenset({"generator"})


def _strip_hidden_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_hidden_fields(item)
            for key, item in value.items()
            if key not in HIDDEN_SEARCH_FIELDS
        }
    if isinstance(value, list):
        return [_strip_hidden_fields(item) for item in value]
    return value


def _build_search_document(*, card_type: Any, data: Any) -> str:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    sanitized = _strip_hidden_fields(data)
    payload: dict[str, Any] = {"data": sanitized}
    if card_type is not None:
        payload["card_type"] = str(card_type)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def upgrade() -> None:
    op.add_column(
        "study_cards",
        sa.Column("owner_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "study_cards",
        sa.Column("search_document", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_study_cards_owner_id",
        "study_cards",
        ["owner_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_study_cards_owner",
        "study_cards",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    study_cards = sa.Table(
        "study_cards",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("card_type", sa.String(length=50)),
        sa.Column("data", postgresql.JSONB().with_variant(sa.JSON(), "sqlite")),
        sa.Column("search_document", sa.Text()),
    )

    rows = list(
        bind.execute(sa.select(study_cards.c.id, study_cards.c.card_type, study_cards.c.data))
    )
    for row in rows:
        search_document = _build_search_document(card_type=row.card_type, data=row.data)
        bind.execute(
            study_cards.update()
            .where(study_cards.c.id == row.id)
            .values(search_document=search_document)
        )

    op.alter_column("study_cards", "search_document", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_study_cards_owner", "study_cards", type_="foreignkey")
    op.drop_index("ix_study_cards_owner_id", table_name="study_cards")
    op.drop_column("study_cards", "search_document")
    op.drop_column("study_cards", "owner_id")
