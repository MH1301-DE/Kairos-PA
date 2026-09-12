"""conversation_message_tool_call_id

Revision ID: 1d9489995959
Revises: d01f4413837f
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1d9489995959"
down_revision: str | None = "d01f4413837f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_message", sa.Column("tool_call_id", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("conversation_message", "tool_call_id")
