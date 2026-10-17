from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive import service as service_module
from kairos.activities.derive.common import ACTIVITY_DERIVED_ALGO_VERSION
from kairos.activities.derive.service import derive_activity, derive_pending, rederive_all
from kairos.activities.reconcile import reconcile_deleted_activities
from kairos.activities.reprocess import reprocess_activities
from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import StreamSet
from kairos.connectors.types import RawFile, RawPayloadEnvelope, Window
from kairos.db.models import (
    Activity,
    ActivityBestEffort,
    ActivitySplit,
    ActivityStats,
    ActivityStepResult,
)
from kairos.db.rls import install_rls_listener
from kairos.ingestion import garmin_sync
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from tests.activity_fixtures import WORKOUT_RUN, ActivityFixture, load_activity_fixture
from tests.test_fit_decoder import mini_fit_zip

_ACTIVITY_COLUMNS = (
    "sport",
    "sport_profile",
    "start_at",
    "end_at",
    "start_local",
    "utc_offset_min",
    "moving_duration_s",
    "distance_m",
    "duration_s",
    "avg_hr",
    "max_hr",
    "elevation_gain_m",
)
_TABLES = (ActivityStats, ActivitySplit, ActivityBestEffort, ActivityStepResult)


async def _user(session: AsyncSession, *, hr_max: int | None = 190) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'UTC', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    await session.execute(
        text("INSERT INTO user_setting (user_id, hr_max_override) VALUES (:u, :h)"),
        {"u": str(uid), "h": hr_max},
    )
    await session.commit()
    return uid


async def _fixture_activity(
    session: AsyncSession, uid: uuid.UUID, fx: ActivityFixture, external_id: str
) -> int:
    activity = Activity(
        user_id=uid,
        external_id=external_id,
        **{k: fx.summary[k] for k in _ACTIVITY_COLUMNS},
    )
    session.add(activity)
    await session.flush()
    await replace_streams(
        session,
        user_id=uid,
        activity_id=activity.id,
        streams=StreamSet(
            start_at=fx.stream.start_at,
            t_offset_s=fx.stream.t_offset_s,
            channels=fx.stream.channels,
            source="fit_zip",
        ),
        algo_version=STREAM_ALGO_VERSION,
    )
    await session.commit()
    return activity.id


@pytest.fixture
def fixture_messages(monkeypatch: pytest.MonkeyPatch) -> ActivityFixture:
    fx = load_activity_fixture(WORKOUT_RUN)

    async def _load(session: AsyncSession, *, activity: Activity) -> Any:
        del session, activity
        return fx.messages, "fit_zip"

    monkeypatch.setattr(service_module, "load_fit_messages", _load)
    return fx


async def _counts(session: AsyncSession, activity_id: int) -> list[int]:
    return [
        int(
            (
                await session.execute(
                    select(func.count()).select_from(t).where(t.activity_id == activity_id)
                )
            ).scalar_one()
        )
        for t in _TABLES
    ]


@pytest.mark.asyncio
async def test_derive_writes_all_four_tables_and_is_idempotent(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    uid = await _user(session)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "w1")
    install_rls_listener(app_session, uid)

    first = await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.commit()
    counts = await _counts(app_session, activity_id)

    assert first.status == "derived"
    assert counts[0] == 1 and all(c > 0 for c in counts), counts
    stats = (
        await app_session.execute(
            select(ActivityStats).where(ActivityStats.activity_id == activity_id)
        )
    ).scalar_one()
    assert stats.algo_version == ACTIVITY_DERIVED_ALGO_VERSION
    assert stats.distance_source == "gps"
    assert stats.hr_zone_s is not None

    # spec B.5: < 200 ms per activity without decoding; 1 s guards against CI load
    started = time.perf_counter()
    second = await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    elapsed = time.perf_counter() - started
    await app_session.commit()
    print(f"derive_activity {WORKOUT_RUN}: {elapsed * 1000:.0f} ms")

    assert second.status == "derived"
    assert await _counts(app_session, activity_id) == counts
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_pending_rederives_older_algo_version_and_skips_current(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    uid = await _user(session)
    a = await _fixture_activity(session, uid, fixture_messages, "a")
    b = await _fixture_activity(session, uid, fixture_messages, "b")
    install_rls_listener(app_session, uid)

    assert {o.activity_id for o in await derive_pending(app_session, user_id=uid)} == {a, b}
    await app_session.commit()
    assert await derive_pending(app_session, user_id=uid) == []

    await app_session.execute(
        update(ActivityStats)
        .where(ActivityStats.activity_id == b)
        .values(algo_version=ACTIVITY_DERIVED_ALGO_VERSION - 1)
    )
    outcomes = await derive_pending(app_session, user_id=uid)
    await app_session.commit()

    assert [(o.activity_id, o.status) for o in outcomes] == [(b, "derived")]
    version = (
        await app_session.execute(
            select(ActivityStats.algo_version).where(ActivityStats.activity_id == b)
        )
    ).scalar_one()
    assert version == ACTIVITY_DERIVED_ALGO_VERSION


@pytest.mark.asyncio
async def test_deleted_activity_has_no_derived_rows(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    uid = await _user(session)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "d")
    install_rls_listener(app_session, uid)
    await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.commit()

    await app_session.execute(
        update(Activity)
        .where(Activity.id == activity_id)
        .values(deleted_at=datetime.now(UTC), deleted_reason="kairos")
    )
    outcomes = await derive_pending(app_session, user_id=uid)
    await app_session.commit()

    assert [(o.activity_id, o.status) for o in outcomes] == [(activity_id, "deleted")]
    assert await _counts(app_session, activity_id) == [0, 0, 0, 0]
    assert await derive_pending(app_session, user_id=uid) == []


@pytest.mark.asyncio
async def test_without_stream_only_summary_stats_are_written(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    activity = Activity(
        user_id=uid,
        external_id="s",
        sport="running",
        sport_profile="running",
        start_at=datetime(2026, 8, 4, 9, tzinfo=UTC),
        distance_m=5000.0,
        duration_s=1500.0,
        avg_hr=150,
    )
    session.add(activity)
    await session.commit()
    install_rls_listener(app_session, uid)

    outcome = await derive_activity(app_session, user_id=uid, activity_id=activity.id)
    await app_session.commit()

    assert outcome.status == "summary_only"
    assert await _counts(app_session, activity.id) == [1, 0, 0, 0]
    stats = (
        await app_session.execute(
            select(ActivityStats).where(ActivityStats.activity_id == activity.id)
        )
    ).scalar_one()
    assert stats.quality == "partial"
    assert stats.avg_pace_s_km == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_failure_of_one_activity_does_not_stop_the_others(
    session: AsyncSession,
    app_session: AsyncSession,
    fixture_messages: ActivityFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = await _user(session)
    good = await _fixture_activity(session, uid, fixture_messages, "good")
    bad = await _fixture_activity(session, uid, fixture_messages, "bad")
    real = service_module.best_efforts
    calls: list[int] = []

    # derive_pending runs in id order, so the second call belongs to "bad"
    def _flaky(prep: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(prep, **kwargs)

    monkeypatch.setattr(service_module, "best_efforts", _flaky)
    install_rls_listener(app_session, uid)

    outcomes = {o.activity_id: o for o in await derive_pending(app_session, user_id=uid)}
    await app_session.commit()

    assert outcomes[bad].status == "failed" and outcomes[bad].error == "boom"
    assert outcomes[good].status == "derived"
    assert await _counts(app_session, bad) == [0, 0, 0, 0]
    assert (await _counts(app_session, good))[0] == 1


@pytest.mark.asyncio
async def test_failed_rederive_keeps_previous_rows_and_is_retried(
    session: AsyncSession,
    app_session: AsyncSession,
    fixture_messages: ActivityFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = await _user(session)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "keep")
    install_rls_listener(app_session, uid)
    await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    old_version = ACTIVITY_DERIVED_ALGO_VERSION - 1
    await app_session.execute(update(ActivityStats).values(algo_version=old_version))
    await app_session.commit()
    counts = await _counts(app_session, activity_id)
    real = service_module.compute_stats

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(service_module, "compute_stats", _boom)
    outcomes = await derive_pending(app_session, user_id=uid)
    await app_session.commit()

    assert [(o.activity_id, o.status) for o in outcomes] == [(activity_id, "failed")]
    assert await _counts(app_session, activity_id) == counts
    version = select(ActivityStats.algo_version).where(ActivityStats.activity_id == activity_id)
    assert (await app_session.execute(version)).scalar_one() == old_version

    monkeypatch.setattr(service_module, "compute_stats", real)
    outcomes = await derive_pending(app_session, user_id=uid)
    await app_session.commit()

    assert [(o.activity_id, o.status) for o in outcomes] == [(activity_id, "derived")]
    assert await _counts(app_session, activity_id) == counts
    assert (await app_session.execute(version)).scalar_one() == ACTIVITY_DERIVED_ALGO_VERSION


@pytest.mark.asyncio
async def test_reprocess_reports_each_failure_once_and_derives_stale_outside_range(
    session: AsyncSession,
    app_session: AsyncSession,
    fixture_messages: ActivityFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = await _user(session)
    target = await _fixture_activity(session, uid, fixture_messages, "target")
    stale = await _fixture_activity(session, uid, fixture_messages, "stale")
    real = service_module.best_efforts
    calls: list[int] = []

    # every derivation fails except the one after the first: pass 2 handles "stale"
    def _flaky(prep: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) != 2:
            raise RuntimeError("boom")
        return real(prep, **kwargs)

    monkeypatch.setattr(service_module, "best_efforts", _flaky)
    install_rls_listener(app_session, uid)

    result = await reprocess_activities(
        app_session,
        user_id=uid,
        from_date=None,
        to_date=None,
        activity_ids=[target],
        refetch_fit=False,
        garmin=None,
        pause_s=0.0,
    )

    assert result.derive_failed == ["target"]
    assert result.derived == 1
    assert len(calls) == 2
    assert (await _counts(app_session, stale))[0] == 1


@pytest.mark.asyncio
async def test_reconcile_removes_derived_rows(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    uid = await _user(session)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "gone")
    install_rls_listener(app_session, uid)
    await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.commit()
    local_day = fixture_messages.summary["start_local"].replace(hour=0, minute=0, second=0)
    window = Window(start=local_day, end=local_day + timedelta(days=1))

    marked = await reconcile_deleted_activities(
        app_session, user_id=uid, window=window, payload=[{"activityId": 1}]
    )
    await app_session.commit()

    assert [i for i, _ in marked] == [activity_id]
    assert await _counts(app_session, activity_id) == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_reprocess_derives_affected_activities(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    uid = await _user(session)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "r")
    install_rls_listener(app_session, uid)
    await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.execute(update(ActivitySplit).values(hr_avg=1))
    await app_session.commit()

    result = await reprocess_activities(
        app_session,
        user_id=uid,
        from_date=None,
        to_date=None,
        activity_ids=[activity_id],
        refetch_fit=False,
        garmin=None,
        pause_s=0.0,
    )

    assert result.derived == 1 and result.derive_failed == []
    hr = (
        await app_session.execute(
            select(func.min(ActivitySplit.hr_avg)).where(ActivitySplit.activity_id == activity_id)
        )
    ).scalar_one()
    assert hr is not None and hr > 1


@pytest.mark.asyncio
async def test_fit_ingest_hook_derives_touched_activities(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    start = datetime(2026, 8, 4, 9, tzinfo=UTC)
    activity_id = int(
        (
            await session.execute(
                text(
                    "INSERT INTO activity (user_id, external_id, start_at) "
                    "VALUES (:u, '77', :s) RETURNING id"
                ),
                {"u": str(uid), "s": start},
            )
        ).scalar_one()
    )
    file = RawFile(
        kind="activity_fit_file",
        key="77",
        window_start=start,
        content=mini_fit_zip(start, [120, 130, 140, 150]),
        payload_format="fit_zip",
    )
    payload_id = await SqlRawPayloadRepository(session=session).upsert_file(
        user_id=uid, connector_id="garmin", file=file
    )
    await session.commit()
    install_rls_listener(app_session, uid)
    hook = garmin_sync._make_fit_ingest_hook(app_session, uid, set())
    envelope = RawPayloadEnvelope(
        window=Window(start=start, end=start + timedelta(days=1)), payload={}, files=(file,)
    )

    await hook("activity_fit", envelope, 1, {"77": payload_id})
    await app_session.commit()

    stats = (
        await app_session.execute(
            select(ActivityStats).where(ActivityStats.activity_id == activity_id)
        )
    ).scalar_one()
    assert stats.hr_max == 150
    assert stats.quality == "ok"


@pytest.mark.asyncio
async def test_rederive_all_picks_up_hr_max_entered_after_sync(
    session: AsyncSession, app_session: AsyncSession, fixture_messages: ActivityFixture
) -> None:
    # spec A.6: syncing first and entering HRmax later must not leave zones empty
    uid = await _user(session, hr_max=None)
    activity_id = await _fixture_activity(session, uid, fixture_messages, "late")
    install_rls_listener(app_session, uid)
    await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.commit()
    stats = await app_session.get(ActivityStats, activity_id)
    assert stats is not None and stats.hr_zone_s is None and stats.trimp_edwards is None

    await session.execute(
        text("UPDATE user_setting SET hr_max_override = 190 WHERE user_id = :u"), {"u": str(uid)}
    )
    await session.commit()
    outcomes = await rederive_all(app_session, user_id=uid)
    await app_session.commit()

    assert [o.status for o in outcomes] == ["derived"]
    app_session.expire_all()
    stats = await app_session.get(ActivityStats, activity_id)
    assert stats is not None and stats.hr_zone_s and stats.trimp_edwards
