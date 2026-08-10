"""hypertables_wellness_activity_record

Revision ID: 6bf30be597a0
Revises: c4d2e3f5a6b7
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "6bf30be597a0"
down_revision: str | None = "c4d2e3f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHUNK_INTERVAL = "7 days"

# No compression policy: TimescaleDB does not support columnstore compression
# on tables with row-level security enabled (both wellness_sample and
# activity_record have FORCE ROW LEVEL SECURITY from a7f9f3d1c2b4), and RLS is
# non-negotiable per 02-datenmodell-und-volumen.md §2.6. Uncompressed 5-year,
# 5-user volume is ~4.8 GB per the same doc — trivial without compression.


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # Timescale requires the partitioning column in every unique/primary-key
    # constraint, so the surrogate id-only PK must become composite first.
    op.drop_constraint("wellness_sample_pkey", "wellness_sample", type_="primary")
    op.create_primary_key(
        "wellness_sample_pkey", "wellness_sample", ["id", "observed_at"]
    )
    op.execute(
        f"SELECT create_hypertable('wellness_sample', 'observed_at', "
        f"chunk_time_interval => INTERVAL '{_CHUNK_INTERVAL}', migrate_data => TRUE)"
    )

    op.drop_constraint("activity_record_pkey", "activity_record", type_="primary")
    op.create_primary_key(
        "activity_record_pkey", "activity_record", ["id", "recorded_at"]
    )
    op.execute(
        f"SELECT create_hypertable('activity_record', 'recorded_at', "
        f"chunk_time_interval => INTERVAL '{_CHUNK_INTERVAL}', migrate_data => TRUE)"
    )


def downgrade() -> None:
    # Timescale has no un-hypertable operation; reverting requires restoring
    # the pre-migration backup rather than an in-place schema change.
    raise NotImplementedError(
        "hypertable conversion is not reversible in-place — restore from backup"
    )
