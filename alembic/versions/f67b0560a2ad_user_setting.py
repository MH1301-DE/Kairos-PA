"""user_setting

Revision ID: f67b0560a2ad
Revises: 6bf30be597a0
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f67b0560a2ad"
down_revision: str | None = "6bf30be597a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_setting",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column("resting_hr_override", sa.SmallInteger(), nullable=True),
        sa.Column("hr_max_override", sa.SmallInteger(), nullable=True),
        sa.Column("sleep_target_hours", sa.Float(), nullable=False, server_default="8.0"),
        sa.CheckConstraint("sex IN ('male', 'female')", name="user_setting_sex_check"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute("ALTER TABLE user_setting ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON user_setting "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE user_setting FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_setting")
    op.execute("ALTER TABLE user_setting NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_setting DISABLE ROW LEVEL SECURITY")
    op.drop_table("user_setting")
