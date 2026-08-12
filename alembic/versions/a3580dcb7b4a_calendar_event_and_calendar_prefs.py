"""calendar_event_and_calendar_prefs

Revision ID: a3580dcb7b4a
Revises: 339358b313ef
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3580dcb7b4a"
down_revision: str | None = "339358b313ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False, server_default="primary"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False, server_default="confirmed"),
        sa.Column("source", sa.Text(), nullable=False, server_default="external"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "connector", "external_id", name="uq_calendar_event"),
        sa.CheckConstraint(
            "status IN ('confirmed', 'tentative', 'cancelled')", name="calendar_event_status_check"
        ),
        sa.CheckConstraint("source IN ('external', 'kairos')", name="calendar_event_source_check"),
    )
    op.execute("ALTER TABLE calendar_event ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON calendar_event "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE calendar_event FORCE ROW LEVEL SECURITY")

    op.add_column("user_setting", sa.Column("work_hours_start", sa.Time(), nullable=True))
    op.add_column("user_setting", sa.Column("work_hours_end", sa.Time(), nullable=True))
    op.add_column(
        "user_setting",
        sa.Column(
            "calendar_buffer_minutes", sa.SmallInteger(), nullable=False, server_default="15"
        ),
    )
    op.add_column(
        "user_setting",
        sa.Column(
            "min_free_block_minutes", sa.SmallInteger(), nullable=False, server_default="30"
        ),
    )


def downgrade() -> None:
    op.drop_column("user_setting", "min_free_block_minutes")
    op.drop_column("user_setting", "calendar_buffer_minutes")
    op.drop_column("user_setting", "work_hours_end")
    op.drop_column("user_setting", "work_hours_start")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON calendar_event")
    op.execute("ALTER TABLE calendar_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE calendar_event DISABLE ROW LEVEL SECURITY")
    op.drop_table("calendar_event")
