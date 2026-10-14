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
        fields = {
            "name": d.get("name"),
            "sport": d.get("sport"),
            "sport_profile": d.get("sport_profile") or "generic",
            "garmin_type_id": d.get("garmin_type_id"),
            "garmin_parent_type_id": d.get("garmin_parent_type_id"),
            "description": d.get("description"),
            "start_at": record.occurred_at,
            "end_at": _parse_dt(d.get("end_at")),
            "start_local": _parse_naive_dt(d.get("start_local")),
            "utc_offset_min": d.get("utc_offset_min"),
            "distance_m": d.get("distance_m"),
            "duration_s": d.get("duration_s"),
            "moving_duration_s": d.get("moving_duration_s"),
            "avg_speed_mps": d.get("avg_speed_mps"),
            "avg_hr": d.get("avg_hr"),
            "max_hr": d.get("max_hr"),
            "elevation_gain_m": d.get("elevation_gain_m"),
            "calories": d.get("calories"),
            "lap_count": d.get("lap_count"),
            "garmin_training_load": d.get("garmin_training_load"),
            "garmin_vo2max": d.get("garmin_vo2max"),
            "raw_payload_id": raw_payload_id,
        }
        stmt = (
            insert(Activity)
            .values(user_id=user_id, external_id=record.external_id, **fields)
            .on_conflict_do_update(
                constraint="uq_activity",
                set_={**fields, "deleted_at": None, "deleted_reason": None},
            )
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


def _parse_naive_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except ValueError:
        return None
