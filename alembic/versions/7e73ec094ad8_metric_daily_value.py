"""metric_daily_value

Revision ID: 7e73ec094ad8
Revises: 9f3d6a1b2c48
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e73ec094ad8"
down_revision: str | None = "9f3d6a1b2c48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_daily_value",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.Text(), nullable=False),
        sa.Column("variant_id", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "metric_id", "variant_id", "day"),
    )
    op.execute("ALTER TABLE metric_daily_value ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON metric_daily_value "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE metric_daily_value FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON metric_daily_value")
    op.execute("ALTER TABLE metric_daily_value NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE metric_daily_value DISABLE ROW LEVEL SECURITY")
    op.drop_table("metric_daily_value")
