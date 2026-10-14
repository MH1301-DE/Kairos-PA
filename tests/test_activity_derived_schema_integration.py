import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import (
    ActivityBestEffort,
    ActivitySplit,
    ActivityStats,
    ActivityStepResult,
)
from kairos.db.rls import install_rls_listener

TABLES = ("activity_stats", "activity_split", "activity_best_effort", "activity_step_result")


async def _user(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'UTC', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    return uid


async def _activity(session: AsyncSession, uid: uuid.UUID) -> int:
    row = await session.execute(
        text("INSERT INTO activity (user_id, external_id) VALUES (:u, :x) RETURNING id"),
        {"u": str(uid), "x": str(uuid.uuid4())},
    )
    return int(row.scalar_one())


def _rows(uid: uuid.UUID, aid: int) -> list[object]:
    return [
        ActivityStats(
            activity_id=aid, user_id=uid, sport_profile="running", algo_version=1,
            quality="ok", distance_source="gps", hr_zone_s={"z1": 10},
        ),
        ActivitySplit(
            activity_id=aid, kind="distance", idx=1, user_id=uid, distance_m=1000.0,
            quality="ok",
        ),
        ActivityBestEffort(
            activity_id=aid, distance_key="5k", user_id=uid, distance_m=5000.0,
            duration_s=1200.0, start_offset_s=0.0, start_km=0.0, quality="ok",
        ),
        ActivityStepResult(
            activity_id=aid, exec_idx=1, user_id=uid, wkt_step_index=0, step_type="warmup",
            target_source="fit",
        ),
    ]


async def _seed(session: AsyncSession, uid: uuid.UUID, aid: int) -> None:
    session.add_all(_rows(uid, aid))
    await session.flush()


@pytest.mark.asyncio
async def test_tables_exist_with_forced_rls(session: AsyncSession) -> None:
    rows = await session.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(:t)"
        ),
        {"t": list(TABLES)},
    )
    assert {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows} == {
        t: (True, True) for t in TABLES
    }


@pytest.mark.asyncio
async def test_defaults_applied(session: AsyncSession) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    await _seed(session, uid, aid)
    stats = (await session.execute(select(ActivityStats))).scalars().one()
    split = (await session.execute(select(ActivitySplit))).scalars().one()
    await session.refresh(stats)
    assert stats.sport_metrics == {}
    assert stats.computed_at is not None
    assert split.is_partial is False
    await session.rollback()


@pytest.mark.asyncio
async def test_rls_isolates_users(session: AsyncSession, app_session: AsyncSession) -> None:
    a = await _user(session)
    b = await _user(session)
    aid = await _activity(session, a)
    await _seed(session, a, aid)
    await session.commit()

    models = (ActivityStats, ActivitySplit, ActivityBestEffort, ActivityStepResult)
    install_rls_listener(app_session, b)
    for model in models:
        assert (await app_session.execute(select(model))).scalars().all() == []
    await app_session.rollback()

    install_rls_listener(app_session, a)
    for model in models:
        assert len((await app_session.execute(select(model))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_activity_delete_cascades(session: AsyncSession) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    await _seed(session, uid, aid)
    await session.execute(text("DELETE FROM activity WHERE id = :i"), {"i": aid})
    for t in TABLES:
        q = text(f"SELECT count(*) FROM {t} WHERE activity_id = :i")
        n = await session.execute(q, {"i": aid})
        assert n.scalar_one() == 0
    await session.commit()


@pytest.mark.asyncio
async def test_stats_quality_check_rejects_bad(session: AsyncSession) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    session.add(
        ActivityStats(
            activity_id=aid, user_id=uid, sport_profile="running", algo_version=1,
            quality="bad",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_idx", "field", "value"),
    [
        (0, "distance_source", "satellite"),
        (1, "kind", "interval"),
        (3, "target_source", "guess"),
    ],
)
async def test_check_constraints_reject(
    session: AsyncSession, model_idx: int, field: str, value: str
) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    row = _rows(uid, aid)[model_idx]
    setattr(row, field, value)
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
