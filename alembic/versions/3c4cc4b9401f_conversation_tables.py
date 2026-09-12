"""conversation_tables

Revision ID: 3c4cc4b9401f
Revises: b1025127c2e0
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3c4cc4b9401f"
down_revision: str | None = "b1025127c2e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE conversation ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON conversation "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE conversation FORCE ROW LEVEL SECURITY")

    op.create_table(
        "conversation_message",
        sa.Column("id", sa.UUID(), nullable=False),
        # ordering key: func.now() resolves to the same value for every statement in
        # one transaction, so ORDER BY created_at alone is not deterministic within a
        # single turn (several messages appended before one commit) -- BigInteger
        # IDENTITY guarantees strict insertion order regardless of transaction timing
        sa.Column(
            "seq", sa.BigInteger(), sa.Identity(always=False), nullable=False, unique=True
        ),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        # redundant to conversation.user_id, but needed directly on this table so
        # its own RLS policy doesn't need a subquery/join
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')", name="conversation_message_role_check"
        ),
    )
    op.execute("ALTER TABLE conversation_message ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON conversation_message "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE conversation_message FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON conversation_message")
    op.execute("ALTER TABLE conversation_message NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversation_message DISABLE ROW LEVEL SECURITY")
    op.drop_table("conversation_message")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON conversation")
    op.execute("ALTER TABLE conversation NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversation DISABLE ROW LEVEL SECURITY")
    op.drop_table("conversation")
