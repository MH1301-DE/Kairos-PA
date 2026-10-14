"""V8: compare activity_stream element counts with activity_record rows.

Usage: .venv/bin/python scripts/verify_activity_streams.py --user-id <uuid>
Only meaningful before migration fed6d2d1311b (drop_timescaledb) removes activity_record.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_verification import Counts, compare_counts
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory

_STREAM_COUNTS = text(
    "SELECT s.activity_id, s.channel, count(x) FROM activity_stream s, "
    "unnest(coalesce(s.v4::float8[], s.v8)) x WHERE s.user_id = :u GROUP BY 1, 2"
)
_RECORD_COUNTS = text(
    "SELECT activity_id, metric, count(*) FROM activity_record WHERE user_id = :u GROUP BY 1, 2"
)
_RECORDS_TABLE = text("SELECT to_regclass('activity_record')")
_EXTERNAL_IDS = text("SELECT id, external_id FROM activity WHERE user_id = :u")
_SOURCES = text("SELECT source, count(*) FROM activity_stream_axis WHERE user_id = :u GROUP BY 1")
_SIZE = text(
    "SELECT avg(sz) FROM (SELECT a.activity_id, pg_column_size(a.t_offset_s) + "
    "coalesce((SELECT sum(coalesce(pg_column_size(s.v4), 0) + coalesce(pg_column_size(s.v8), 0)) "
    "FROM activity_stream s WHERE s.activity_id = a.activity_id), 0) AS sz "
    "FROM activity_stream_axis a WHERE a.user_id = :u) t"
)


async def _counts(session: AsyncSession, stmt: TextClause, uid: uuid.UUID) -> Counts:
    out: Counts = {}
    for activity_id, channel, n in (await session.execute(stmt, {"u": str(uid)})).all():
        out.setdefault(int(activity_id), {})[str(channel)] = int(n)
    return out


async def run(uid: uuid.UUID) -> int:
    async with async_session_factory() as session:
        install_rls_listener(session, uid)
        if (await session.execute(_RECORDS_TABLE)).scalar_one() is None:
            print(
                "activity_record no longer exists (dropped by migration fed6d2d1311b); "
                "V8 can only run before that migration."
            )
            return 0
        stream = await _counts(session, _STREAM_COUNTS, uid)
        records = await _counts(session, _RECORD_COUNTS, uid)
        ext = {
            int(i): str(e) for i, e in (await session.execute(_EXTERNAL_IDS, {"u": str(uid)})).all()
        }
        sources = {
            str(s): int(n) for s, n in (await session.execute(_SOURCES, {"u": str(uid)})).all()
        }
        avg_bytes = (await session.execute(_SIZE, {"u": str(uid)})).scalar_one()

    result = compare_counts(stream, records, set(ext))

    def name(activity_id: int) -> str:
        return ext.get(activity_id, f"id={activity_id}")

    covered = len(set(ext) & set(stream))
    print(f"{covered}/{len(ext)} activities with stream")
    print()
    print(f"Deviations ({len(result.deviations)}):")
    print(f"  {'activity':<14}{'channel':<14}{'stream':>9}{'records':>9}")
    for d in result.deviations:
        print(f"  {name(d.activity_id):<14}{d.channel:<14}{d.stream_count:>9}{d.record_count:>9}")
    print(f"\nActivities without stream ({len(result.missing_stream)}):")
    for a in result.missing_stream:
        print(f"  {name(a)}")
    print(f"\nChannels only in stream ({len(result.stream_only)}):")
    for a, channel, n in result.stream_only:
        print(f"  {name(a):<14}{channel:<14}{n:>9}")
    print(f"\nSources: fit_zip={sources.get('fit_zip', 0)} fit_json={sources.get('fit_json', 0)}")
    avg_kb = float(avg_bytes) / 1024 if avg_bytes is not None else 0.0
    print(f"Average stored size per activity: {avg_kb:.1f} KB")
    print("\nRESULT: " + ("OK" if result.ok else "FAIL"))
    return 0 if result.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=uuid.UUID, required=True)
    sys.exit(asyncio.run(run(parser.parse_args().user_id)))


if __name__ == "__main__":
    main()
