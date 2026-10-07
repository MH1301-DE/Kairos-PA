"""memory_expiry_and_compaction

Revision ID: 7a1c2e9d4b30
Revises: 27d8fcfada03
Create Date: 2026-10-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7a1c2e9d4b30"
down_revision: str | None = "27d8fcfada03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_memory", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversation", sa.Column("compacted_through_seq", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("conversation", "compacted_through_seq")
    op.drop_column("agent_memory", "expires_at")
