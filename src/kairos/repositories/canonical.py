"""Concrete SQLAlchemy canonical repository — writes CanonicalRecords to typed tables."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.models import (
    Activity,
    ActivityRecord,
    DailySummary,
    MetricDef,
    SleepSession,
    WellnessSample,
)


class SqlCanonicalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        # code → id, loaded lazily and cached for the session lifetime
        self._metric_cache: dict[str, int] = {}

    async def upsert_many(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        records: list[CanonicalRecord],
        raw_payload_id: int,
    ) -> int:
        del connector_id
        written = 0
        # activity_record is batched, not written one row at a time like the
        # other types below -- a single ~1h activity at 1s resolution is
        # ~7000+ rows, and this repo previously did 2 DB round-trips per row
        # (an Activity.id lookup + the insert itself). Measured against a real
        # 2-year backfill: ~3.3M total activity_record rows, ~2.4ms/round-trip
        # -> over 2 hours just for writes on a run whose fetch+throttle time
        # alone is ~23 minutes. Collected here and flushed once at the end.
        activity_records: list[CanonicalRecord] = []
        for record in records:
            rt = record.record_type
            if rt == "wellness_sample":
                await self._write_wellness(user_id, record, raw_payload_id)
                written += 1
            elif rt == "sleep_session":
                await self._write_sleep(user_id, record, raw_payload_id)
                written += 1
            elif rt == "activity":
                await self._write_activity(user_id, record, raw_payload_id)
                written += 1
            elif rt == "activity_record":
                activity_records.append(record)
            elif rt == "daily_summary":
                await self._write_daily_summary(user_id, record, raw_payload_id)
                written += 1
        if activity_records:
            written += await self._write_activity_records_bulk(
                user_id, activity_records, raw_payload_id
            )
        return written

    # ── Writers ───────────────────────────────────────────────────────────────

    async def _write_wellness(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict):
            return
        metric_code = record.data.get("metric")
        if not isinstance(metric_code, str):
            return
        metric_id = await self._metric_id(metric_code)
        if metric_id is None:
            return
        stmt = (
            insert(WellnessSample)
            .values(
                user_id=user_id,
                metric_id=metric_id,
                observed_at=record.occurred_at,
                value=float(record.data.get("value", 0)),  # type: ignore[arg-type]
                quality=record.data.get("quality", "ok"),
                raw_payload_id=raw_payload_id,
            )
            .on_conflict_do_nothing(constraint="uq_wellness_sample")
        )
        await self._session.execute(stmt)

    async def _write_sleep(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict):
            return
        stmt = (
            insert(SleepSession)
            .values(
                user_id=user_id,
                external_id=record.external_id,
                start_at=record.occurred_at,
                end_at=_parse_dt(record.data.get("end_at")),
                duration_seconds=record.data.get("duration_seconds"),
                raw_payload_id=raw_payload_id,
            )
            .on_conflict_do_nothing(constraint="uq_sleep_session")
        )
        await self._session.execute(stmt)

    async def _write_activity(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict):
            return
        d = record.data
        stmt = (
            insert(Activity)
            .values(
                user_id=user_id,
                external_id=record.external_id,
                name=d.get("name"),
                sport=d.get("sport"),
                activity_type=d.get("activity_type"),
                start_at=record.occurred_at,
                end_at=_parse_dt(d.get("end_at")),
                distance_m=d.get("distance_m"),
                duration_s=d.get("duration_s"),
                avg_hr=d.get("avg_hr"),
                max_hr=d.get("max_hr"),
                elevation_gain_m=d.get("elevation_gain_m"),
                calories=d.get("calories"),
                raw_payload_id=raw_payload_id,
            )
            .on_conflict_do_update(
                constraint="uq_activity",
                set_={
                    "name": d.get("name"),
                    "sport": d.get("sport"),
                    "distance_m": d.get("distance_m"),
                    "duration_s": d.get("duration_s"),
                    "avg_hr": d.get("avg_hr"),
                    "max_hr": d.get("max_hr"),
                    "elevation_gain_m": d.get("elevation_gain_m"),
                    "calories": d.get("calories"),
                },
            )
        )
        await self._session.execute(stmt)

    async def _write_activity_records_bulk(
        self, user_id: UUID, records: list[CanonicalRecord], raw_payload_id: int
    ) -> int:
        ext_ids: set[str] = set()
        for r in records:
            if isinstance(r.data, dict):
                ext_id = r.data.get("activity_external_id")
                if isinstance(ext_id, str):
                    ext_ids.add(ext_id)
        if not ext_ids:
            return 0

        # one lookup for every activity referenced by this batch instead of
        # one per row -- a single window's records typically span 1 activity
        result = await self._session.execute(
            select(Activity.external_id, Activity.id).where(
                Activity.user_id == user_id,
                Activity.external_id.in_(ext_ids),
            )
        )
        activity_pk_by_ext_id: dict[str, int] = dict(result.tuples().all())

        rows = []
        for r in records:
            if not isinstance(r.data, dict):
                continue
            ext_id = r.data.get("activity_external_id")
            activity_pk = activity_pk_by_ext_id.get(ext_id) if isinstance(ext_id, str) else None
            if activity_pk is None:
                continue  # activity_list must run before activity_fit
            rows.append(
                {
                    "user_id": user_id,
                    "activity_id": activity_pk,
                    "recorded_at": r.occurred_at,
                    "metric": r.data.get("metric"),
                    "value": float(r.data.get("value", 0)),  # type: ignore[arg-type]
                    "raw_payload_id": raw_payload_id,
                }
            )
        if not rows:
            return 0

        # a bare insert() (no .values()) executed with a list of parameter
        # dicts uses SQLAlchemy 2.0's insertmanyvalues -- one multi-row
        # INSERT (chunked internally) instead of one round-trip per row
        stmt = insert(ActivityRecord).on_conflict_do_nothing(constraint="uq_activity_record")
        await self._session.execute(stmt, rows)
        return len(rows)

    async def _write_daily_summary(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict) or record.occurred_at is None:
            return
        stmt = (
            insert(DailySummary)
            .values(
                user_id=user_id,
                day=record.occurred_at.date(),
                summary_type=record.data.get("summary_type", "garmin"),
                payload=record.data,
                raw_payload_id=raw_payload_id,
            )
            .on_conflict_do_update(
                constraint="uq_daily_summary",
                set_={"payload": record.data},
            )
        )
        await self._session.execute(stmt)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _metric_id(self, code: str) -> int | None:
        if code not in self._metric_cache:
            result = await self._session.execute(
                select(MetricDef.id).where(MetricDef.code == code)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            self._metric_cache[code] = row
        return self._metric_cache[code]


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except ValueError:
        return None
