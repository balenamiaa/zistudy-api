"""Drop unique constraint on answers to allow multiple attempts.

Revision ID: 0003_drop_answer_unique_constraint
Revises: 0002_study_card_scope_permissions
Create Date: 2024-11-24 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_drop_answer_unique_constraint"
down_revision = "0002_study_card_scope_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_answer_user_card", "answers", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_answer_user_card", "answers", ["user_id", "study_card_id"])
