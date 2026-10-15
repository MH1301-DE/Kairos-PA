from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, delete, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive.best_efforts import best_efforts
from kairos.activities.derive.common import ACTIVITY_DERIVED_ALGO_VERSION, prepare
from kairos.activities.derive.splits import distance_splits, lap_splits
from kairos.activities.derive.stats import ActivitySummary, compute_stats
from kairos.activities.derive.steps import step_results
from kairos.activities.fit_archive import load_fit_messages
from kairos.activities.stream_repository import load_stream
from kairos.db.models import (
    Activity,
    ActivityBestEffort,
    ActivitySplit,
    ActivityStats,
    ActivityStepResult,
    UserSetting,
)
from kairos.metrics.hr_zones import resolve_hr_max

logger = logging.getLogger(__name__)

DeriveStatus = Literal["derived", "summary_only", "deleted", "missing", "failed"]

# (birth_date, hr_max_override) from user_setting
_HrSettings = tuple[date | None, int | None]

_DERIVED_TABLES = (ActivityStepResult, ActivityBestEffort, ActivitySplit, ActivityStats)


@dataclass(frozen=True)
class DeriveOutcome:
    activity_id: int
    status: DeriveStatus
    splits: int = 0
    best_efforts: int = 0
    step_results: int = 0
    error: str | None = None


async def derive_activity(
    session: AsyncSession, *, user_id: UUID, activity_id: int
) -> DeriveOutcome:
    hr_settings = await _hr_settings(session, user_id)
    return await _derive_safe(session, user_id, activity_id, hr_settings)


async def derive_pending(
    session: AsyncSession, *, user_id: UUID, activity_ids: Sequence[int] | None = None
) -> list[DeriveOutcome]:
    if activity_ids is None:
        ids = await pending_activity_ids(session, user_id=user_id)
    else:
        ids = sorted(set(activity_ids))
    if not ids:
        return []
    hr_settings = await _hr_settings(session, user_id)
    return [await _derive_safe(session, user_id, i, hr_settings) for i in ids]


async def _derive_safe(
    session: AsyncSession, user_id: UUID, activity_id: int, hr_settings: _HrSettings
) -> DeriveOutcome:
    try:
        async with session.begin_nested():
            return await _derive(
                session, user_id=user_id, activity_id=activity_id, hr_settings=hr_settings
            )
    except Exception as exc:
        logger.warning("Derivation failed for activity %s: %s", activity_id, exc, exc_info=True)
        return DeriveOutcome(activity_id=activity_id, status="failed", error=str(exc))


async def _hr_settings(session: AsyncSession, user_id: UUID) -> _HrSettings:
    row = (
        await session.execute(
            select(UserSetting.birth_date, UserSetting.hr_max_override).where(
                UserSetting.user_id == user_id
            )
        )
    ).one_or_none()
    return (None, None) if row is None else (row[0], row[1])


async def pending_activity_ids(session: AsyncSession, *, user_id: UUID) -> list[int]:
    stmt = (
        select(Activity.id)
        .outerjoin(ActivityStats, ActivityStats.activity_id == Activity.id)
        .where(
            Activity.user_id == user_id,
            or_(
                and_(
                    Activity.deleted_at.is_(None),
                    or_(
                        ActivityStats.activity_id.is_(None),
                        ActivityStats.algo_version < ACTIVITY_DERIVED_ALGO_VERSION,
                    ),
                ),
                # deleted after its last derivation: rows must go
                and_(Activity.deleted_at.is_not(None), ActivityStats.activity_id.is_not(None)),
            ),
        )
        .order_by(Activity.id)
    )
    return list((await session.execute(stmt)).scalars())


async def _derive(
    session: AsyncSession, *, user_id: UUID, activity_id: int, hr_settings: _HrSettings
) -> DeriveOutcome:
    activity = (
        await session.execute(
            select(Activity)
            .where(Activity.id == activity_id, Activity.user_id == user_id)
            # raw UPDATEs (reconcile) bypass the identity map
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    for table in _DERIVED_TABLES:
        await session.execute(delete(table).where(table.activity_id == activity_id))
    if activity is None:
        return DeriveOutcome(activity_id=activity_id, status="missing")
    if activity.deleted_at is not None:
        return DeriveOutcome(activity_id=activity_id, status="deleted")

    profile = activity.sport_profile
    summary = ActivitySummary(
        sport_profile=profile,
        sport=activity.sport,
        distance_m=activity.distance_m,
        duration_s=activity.duration_s,
        moving_duration_s=activity.moving_duration_s,
        avg_hr=activity.avg_hr,
        max_hr=activity.max_hr,
        elevation_gain_m=activity.elevation_gain_m,
    )
    hr_max = _hr_max(hr_settings, activity)
    stream = await load_stream(session, activity_id=activity_id)
    if stream is None:
        stats = compute_stats(
            None, activity=summary, sessions=[], lengths=[], splits=[], hr_max=hr_max
        )
        await _insert(session, ActivityStats, user_id, activity_id, [asdict(stats)])
        return DeriveOutcome(activity_id=activity_id, status="summary_only")

    loaded = await load_fit_messages(session, activity=activity)
    messages: dict[str, Any] = loaded[0] if loaded is not None else {}

    def mesgs(key: str) -> list[dict[str, Any]]:
        return list(messages.get(key) or [])

    sessions, laps, lengths = mesgs("session_mesgs"), mesgs("lap_mesgs"), mesgs("length_mesgs")
    prep = prepare(stream, sport_profile=profile, events=mesgs("event_mesgs"))
    pool_length = sessions[0].get("pool_length") if sessions else None
    splits = distance_splits(
        prep,
        sport_profile=profile,
        lengths=lengths,
        pool_length_m=pool_length if isinstance(pool_length, int | float) else None,
        start_at=stream.start_at,
    ) + lap_splits(prep, sport_profile=profile, laps=laps, start_at=stream.start_at)
    stats = compute_stats(
        prep, activity=summary, sessions=sessions, lengths=lengths, splits=splits, hr_max=hr_max
    )
    efforts = best_efforts(
        prep, sport_profile=profile, distance_source=stats.distance_source or "none"
    )
    # spec B.6: only activities run as a Garmin workout
    steps = (
        step_results(
            prep,
            sport_profile=profile,
            workout_steps=mesgs("workout_step_mesgs"),
            laps=laps,
            start_at=stream.start_at,
            hr_targets=None,
        )
        if mesgs("workout_mesgs")
        else []
    )

    await _insert(session, ActivityStats, user_id, activity_id, [asdict(stats)])
    await _insert(session, ActivitySplit, user_id, activity_id, [asdict(r) for r in splits])
    await _insert(session, ActivityBestEffort, user_id, activity_id, [asdict(r) for r in efforts])
    await _insert(session, ActivityStepResult, user_id, activity_id, [asdict(r) for r in steps])
    return DeriveOutcome(
        activity_id=activity_id,
        status="derived",
        splits=len(splits),
        best_efforts=len(efforts),
        step_results=len(steps),
    )


def _hr_max(hr_settings: _HrSettings, activity: Activity) -> int | None:
    birth_date, override = hr_settings
    if activity.start_local is not None:
        as_of = activity.start_local.date()
    elif activity.start_at is not None:
        as_of = activity.start_at.date()
    else:
        as_of = date.today()
    hr_max, _ = resolve_hr_max(birth_date, override, as_of=as_of)
    return hr_max


async def _insert(
    session: AsyncSession,
    table: type[ActivityStats | ActivitySplit | ActivityBestEffort | ActivityStepResult],
    user_id: UUID,
    activity_id: int,
    rows: list[dict[str, Any]],
) -> None:
    if rows:
        await session.execute(
            insert(table), [{**r, "activity_id": activity_id, "user_id": user_id} for r in rows]
        )
