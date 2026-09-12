"""llm_model_setting

Revision ID: d01f4413837f
Revises: 3c4cc4b9401f
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d01f4413837f"
down_revision: str | None = "3c4cc4b9401f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_setting",
        sa.Column(
            "llm_model", sa.Text(), nullable=False, server_default="anthropic/claude-sonnet-5"
        ),
    )


def downgrade() -> None:
    op.drop_column("user_setting", "llm_model")
