"""user_dashboard_tile

Revision ID: c409728c466e
Revises: 1d9489995959
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c409728c466e"
down_revision: str | None = "1d9489995959"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_dashboard_tile",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "module_id"),
    )
    op.execute("ALTER TABLE user_dashboard_tile ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON user_dashboard_tile "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE user_dashboard_tile FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_dashboard_tile")
    op.execute("ALTER TABLE user_dashboard_tile NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_dashboard_tile DISABLE ROW LEVEL SECURITY")
    op.drop_table("user_dashboard_tile")
