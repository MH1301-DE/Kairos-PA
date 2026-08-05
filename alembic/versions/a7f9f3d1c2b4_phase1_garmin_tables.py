"""phase1_garmin_tables

Revision ID: a7f9f3d1c2b4
Revises: dd1f10a99d35
Create Date: 2026-08-04 11:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7f9f3d1c2b4"
down_revision: Union[str, Sequence[str], None] = "dd1f10a99d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_def",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "data_source",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("external_account", sa.Text(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "connector", "source_key", name="uq_data_source"),
    )

    op.create_table(
        "sync_failure",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wellness_sample",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_source.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["metric_id"], ["metric_def.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "metric_id", "observed_at", name="uq_wellness_sample"),
    )

    op.create_table(
        "sleep_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("data_source_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_source.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_sleep_session"),
    )

    op.create_table(
        "activity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_source_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_source.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_activity"),
    )

    op.create_table(
        "activity_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "activity_id", "recorded_at", "metric", name="uq_activity_record"),
    )

    op.create_table(
        "daily_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("summary_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payload.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", "summary_type", name="uq_daily_summary"),
    )

    rls_tables = [
        "data_source",
        "sync_failure",
        "wellness_sample",
        "sleep_session",
        "activity",
        "activity_record",
        "daily_summary",
    ]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    rls_tables = [
        "daily_summary",
        "activity_record",
        "activity",
        "sleep_session",
        "wellness_sample",
        "sync_failure",
        "data_source",
    ]
    for table in rls_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("daily_summary")
    op.drop_table("activity_record")
    op.drop_table("activity")
    op.drop_table("sleep_session")
    op.drop_table("wellness_sample")
    op.drop_table("sync_failure")
    op.drop_table("data_source")
    op.drop_table("metric_def")