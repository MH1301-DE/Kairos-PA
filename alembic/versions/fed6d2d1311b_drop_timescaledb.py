"""drop_timescaledb

Revision ID: fed6d2d1311b
Revises: 8c6af9fb1361
Create Date: 2026-10-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fed6d2d1311b"
down_revision: str | None = "8c6af9fb1361"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS = (
    ("wellness_sample_user_id_fkey", "user_id", "app_user", "CASCADE"),
    ("wellness_sample_metric_id_fkey", "metric_id", "metric_def", "RESTRICT"),
    ("wellness_sample_data_source_id_fkey", "data_source_id", "data_source", "SET NULL"),
    ("wellness_sample_raw_payload_id_fkey", "raw_payload_id", "raw_payload", "SET NULL"),
)


def _scalar(sql: str) -> object:
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def upgrade() -> None:
    # FORCE RLS would hide every row from a non-bypassing role and turn the copy into data loss
    if not _scalar(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ):
        raise RuntimeError("drop_timescaledb must run as a role that bypasses RLS")

    unverified = _scalar(
        "SELECT count(DISTINCT r.activity_id) FROM activity_record r "
        "LEFT JOIN activity_stream_axis a ON a.activity_id = r.activity_id "
        "WHERE a.activity_id IS NULL"
    )
    if unverified:
        raise RuntimeError(
            f"{unverified} activities have activity_record rows but no activity_stream_axis; "
            "run the reprocess job and V8 first"
        )

    seq = _scalar("SELECT pg_get_serial_sequence('wellness_sample', 'id')")
    op.execute("CREATE TABLE wellness_sample_new (LIKE wellness_sample INCLUDING DEFAULTS)")
    op.execute("INSERT INTO wellness_sample_new SELECT * FROM wellness_sample")
    before = _scalar("SELECT count(*) FROM wellness_sample")
    after = _scalar("SELECT count(*) FROM wellness_sample_new")
    if before != after:
        raise RuntimeError(f"wellness_sample copy mismatch: {before} rows before, {after} after")

    # the old table owns the sequence; dropping it would take the sequence along
    op.execute(f"ALTER SEQUENCE {seq} OWNED BY wellness_sample_new.id")
    op.execute("DROP TABLE wellness_sample")
    op.execute("ALTER TABLE wellness_sample_new RENAME TO wellness_sample")
    op.execute(
        f"SELECT setval('{seq}', coalesce(max(id), 1), max(id) IS NOT NULL) "
        "FROM wellness_sample"
    )

    op.create_primary_key("wellness_sample_pkey", "wellness_sample", ["id"])
    op.create_unique_constraint(
        "uq_wellness_sample", "wellness_sample", ["user_id", "metric_id", "observed_at"]
    )
    for name, column, target, ondelete in _FOREIGN_KEYS:
        op.create_foreign_key(
            name, "wellness_sample", target, [column], ["id"], ondelete=ondelete
        )
    op.execute("ALTER TABLE wellness_sample ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON wellness_sample "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE wellness_sample FORCE ROW LEVEL SECURITY")

    op.execute("DROP TABLE activity_record")
    op.execute("DROP EXTENSION IF EXISTS timescaledb_toolkit")
    op.execute("DROP EXTENSION IF EXISTS timescaledb")


def downgrade() -> None:
    raise NotImplementedError("restore pg_dump")
