"""Concrete SQLAlchemy canonical repository — writes CanonicalRecords to typed tables."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.models import Activity, ActivityRecord, DailySummary, MetricDef, SleepSession, WellnessSample


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
                await self._write_activity_record(user_id, record, raw_payload_id)
                written += 1
            elif rt == "daily_summary":
                await self._write_daily_summary(user_id, record, raw_payload_id)
                written += 1
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

    async def _write_activity_record(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict):
            return
        activity_ext_id = record.data.get("activity_external_id")
        if not isinstance(activity_ext_id, str):
            return

        # look up internal activity.id by external_id
        result = await self._session.execute(
            select(Activity.id).where(
                Activity.user_id == user_id,
                Activity.external_id == activity_ext_id,
            )
        )
        activity_pk = result.scalar_one_or_none()
        if activity_pk is None:
            return  # activity_list must run before activity_fit

        stmt = (
            insert(ActivityRecord)
            .values(
                user_id=user_id,
                activity_id=activity_pk,
                recorded_at=record.occurred_at,
                metric=record.data.get("metric"),
                value=float(record.data.get("value", 0)),  # type: ignore[arg-type]
                raw_payload_id=raw_payload_id,
            )
            .on_conflict_do_nothing(constraint="uq_activity_record")
        )
        await self._session.execute(stmt)

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
