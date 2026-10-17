import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import ActivityStream, ActivityStreamAxis
from kairos.db.rls import install_rls_listener

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


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


async def _axis_and_channel(session: AsyncSession, uid: uuid.UUID, aid: int) -> None:
    session.add(
        ActivityStreamAxis(
            activity_id=aid, user_id=uid, start_at=START, t_offset_s=[0, 1, 2],
            source="fit_zip", algo_version=1,
        )
    )
    session.add(
        ActivityStream(activity_id=aid, channel="hr", user_id=uid, v4=[100.0, None, 120.0])
    )
    await session.flush()


@pytest.mark.asyncio
async def test_stream_tables_exist_with_rls(session: AsyncSession) -> None:
    rows = await session.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('activity_stream_axis', 'activity_stream')"
        )
    )
    found = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    assert found == {"activity_stream_axis": (True, True), "activity_stream": (True, True)}


@pytest.mark.asyncio
async def test_stream_columns_use_lz4(session: AsyncSession) -> None:
    rows = await session.execute(
        text(
            "SELECT c.relname, a.attname, a.attcompression::text AS attcompression "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE (c.relname, a.attname) IN "
            "(('activity_stream_axis','t_offset_s'),('activity_stream','v4'),"
            "('activity_stream','v8'))"
        )
    )
    got = {(r.relname, r.attname): r.attcompression for r in rows}
    assert len(got) == 3
    assert set(got.values()) == {"l"}


@pytest.mark.asyncio
async def test_stream_check_exactly_one_array(session: AsyncSession) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    session.add(
        ActivityStreamAxis(
            activity_id=aid, user_id=uid, start_at=START, t_offset_s=[0],
            source="fit_zip", algo_version=1,
        )
    )
    session.add(ActivityStream(activity_id=aid, channel="hr", user_id=uid, v4=[1.0], v8=[1.0]))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


@pytest.mark.asyncio
async def test_payload_format_defaults_to_json_gzip(session: AsyncSession) -> None:
    uid = await _user(session)
    ins = (
        "INSERT INTO raw_payload (user_id, connector, kind, window_start, window_end, "
        "content_hash{col}) VALUES (:u, 'garmin', 'k', now(), now(), :h{val}) "
        "RETURNING payload_format"
    )
    fmt = await session.execute(
        text(ins.format(col="", val="")), {"u": str(uid), "h": b"a"}
    )
    assert fmt.scalar_one() == "json_gzip"
    with pytest.raises(IntegrityError):
        await session.execute(
            text(ins.format(col=", payload_format", val=", 'xml'")), {"u": str(uid), "h": b"b"}
        )
    await session.rollback()


@pytest.mark.asyncio
async def test_stream_rls_isolates_users(session: AsyncSession, app_session: AsyncSession) -> None:
    a = await _user(session)
    b = await _user(session)
    aid = await _activity(session, a)
    await _axis_and_channel(session, a, aid)
    await session.commit()

    install_rls_listener(app_session, b)
    assert (await app_session.execute(select(ActivityStreamAxis))).scalars().all() == []
    assert (await app_session.execute(select(ActivityStream))).scalars().all() == []
    await app_session.rollback()

    install_rls_listener(app_session, a)
    assert len((await app_session.execute(select(ActivityStreamAxis))).scalars().all()) == 1
    assert len((await app_session.execute(select(ActivityStream))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_activity_delete_cascades_streams(session: AsyncSession) -> None:
    uid = await _user(session)
    aid = await _activity(session, uid)
    await _axis_and_channel(session, uid, aid)
    await session.execute(text("DELETE FROM activity WHERE id = :i"), {"i": aid})
    n = await session.execute(
        text(
            "SELECT (SELECT count(*) FROM activity_stream WHERE activity_id = :i) + "
            "(SELECT count(*) FROM activity_stream_axis WHERE activity_id = :i)"
        ),
        {"i": aid},
    )
    assert n.scalar_one() == 0
    await session.commit()
