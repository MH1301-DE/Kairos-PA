"""scheduler_tables

Revision ID: 5c8e1d2f7a90
Revises: 7a1c2e9d4b30
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c8e1d2f7a90"
down_revision: str | None = "7a1c2e9d4b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("scheduled_job", "scheduled_job_run")


def upgrade() -> None:
    op.create_table(
        "scheduled_job",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cron_exprs", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Europe/Berlin"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("context_reset_every", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("agent_runs_since_reset", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.UUID(), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="scheduled_job_name_check"),
        sa.CheckConstraint(
            "cardinality(cron_exprs) BETWEEN 1 AND 6", name="scheduled_job_cron_exprs_check"
        ),
        sa.CheckConstraint(
            "context_reset_every BETWEEN 0 AND 30", name="scheduled_job_context_reset_check"
        ),
    )
    op.create_index(
        "ix_scheduled_job_due",
        "scheduled_job",
        ["next_run_at"],
        postgresql_where=sa.text("enabled AND running_since IS NULL"),
    )

    op.create_table(
        "scheduled_job_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("prompt_message_seq", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'catch_up', 'manual')", name="scheduled_job_run_trigger_check"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'failed', 'skipped', 'interrupted')",
            name="scheduled_job_run_status_check",
        ),
    )
    op.create_index(
        "ix_scheduled_job_run_job_started",
        "scheduled_job_run",
        ["job_id", sa.text("started_at DESC")],
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # the loop must see due jobs of all users; these return ids and timestamps only
    op.execute(
        """
        CREATE FUNCTION scheduler_due_jobs(p_now timestamptz, p_limit int)
        RETURNS TABLE (job_id uuid, user_id uuid, next_run_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT j.id, j.user_id, j.next_run_at FROM scheduled_job j
          WHERE j.enabled AND j.running_since IS NULL AND j.next_run_at <= p_now
          ORDER BY j.next_run_at LIMIT p_limit
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION scheduler_mark_interrupted(p_now timestamptz)
        RETURNS TABLE (job_id uuid, user_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          UPDATE scheduled_job_run r SET status = 'interrupted', finished_at = p_now
          WHERE r.status = 'running';
          RETURN QUERY
            UPDATE scheduled_job j
            SET running_since = NULL, last_status = 'interrupted', updated_at = p_now
            WHERE j.running_since IS NOT NULL
            RETURNING j.id, j.user_id;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS scheduler_mark_interrupted(timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS scheduler_due_jobs(timestamptz, int)")
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_scheduled_job_run_job_started", table_name="scheduled_job_run")
    op.drop_table("scheduled_job_run")
    op.drop_index("ix_scheduled_job_due", table_name="scheduled_job")
    op.drop_table("scheduled_job")
