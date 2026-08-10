"""metrics_raw_tables

Revision ID: 339358b313ef
Revises: f67b0560a2ad
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "339358b313ef"
down_revision: str | None = "f67b0560a2ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Plain tables, not TimescaleDB Continuous Aggregates: Timescale cannot create
# a Continuous Aggregate on a hypertable with row-level security enabled
# (timescale/timescaledb#5787, a permanent limitation). Both source tables
# (activity_record, wellness_sample) have FORCE ROW LEVEL SECURITY, which is
# non-negotiable per CLAUDE.md. Kept fresh by an explicit recompute function
# (src/kairos/repositories/metrics_recompute.py) instead.

_TABLES = ("hr_bucket_seconds_daily", "wellness_daily_stats")


def upgrade() -> None:
    op.create_table(
        "hr_bucket_seconds_daily",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("bpm_bucket", sa.SmallInteger(), nullable=False),
        sa.Column("seconds", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "day", "bpm_bucket"),
    )
    op.create_table(
        "wellness_daily_stats",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("avg_value", sa.Float(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["metric_id"], ["metric_def.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "metric_id", "day"),
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("wellness_daily_stats")
    op.drop_table("hr_bucket_seconds_daily")
