import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_repository import load_stream, replace_streams
from kairos.activities.streams import StreamSet
from kairos.db.models import ActivityStream
from kairos.db.rls import install_rls_listener

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


async def _user_activity(session: AsyncSession) -> tuple[uuid.UUID, int]:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'UTC', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    row = await session.execute(
        text("INSERT INTO activity (user_id, external_id) VALUES (:u, :x) RETURNING id"),
        {"u": str(uid), "x": str(uuid.uuid4())},
    )
    return uid, int(row.scalar_one())


def _streams(hr: list[float | None] | None = None) -> StreamSet:
    return StreamSet(
        start_at=START,
        t_offset_s=[0, 1, 2],
        channels={
            "hr": hr or [100.0, None, 120.0],
            "lat_deg": [48.1, 48.2, None],
        },
        source="fit_zip",
    )


@pytest.mark.asyncio
async def test_roundtrip_with_none_elements(session: AsyncSession) -> None:
    uid, aid = await _user_activity(session)
    n = await replace_streams(
        session, user_id=uid, activity_id=aid, streams=_streams(), algo_version=1
    )
    assert n == 2
    loaded = await load_stream(session, activity_id=aid)
    assert loaded is not None
    assert loaded.start_at == START
    assert loaded.t_offset_s == [0, 1, 2]
    assert loaded.channels == {"hr": [100.0, None, 120.0], "lat_deg": [48.1, 48.2, None]}
    assert loaded.source == "fit_zip"


@pytest.mark.asyncio
async def test_replace_twice_keeps_row_count_and_new_values(session: AsyncSession) -> None:
    uid, aid = await _user_activity(session)
    await replace_streams(session, user_id=uid, activity_id=aid, streams=_streams(), algo_version=1)
    await replace_streams(
        session, user_id=uid, activity_id=aid, streams=_streams([90.0, 91.0, 92.0]), algo_version=1
    )
    count = await session.scalar(
        select(func.count()).select_from(ActivityStream).where(ActivityStream.activity_id == aid)
    )
    assert count == 2
    loaded = await load_stream(session, activity_id=aid)
    assert loaded is not None
    assert loaded.channels["hr"] == [90.0, 91.0, 92.0]


@pytest.mark.asyncio
async def test_channel_filter(session: AsyncSession) -> None:
    uid, aid = await _user_activity(session)
    await replace_streams(session, user_id=uid, activity_id=aid, streams=_streams(), algo_version=1)
    loaded = await load_stream(session, activity_id=aid, channels=["hr"])
    assert loaded is not None
    assert list(loaded.channels) == ["hr"]


@pytest.mark.asyncio
async def test_wrong_length_channel_raises(session: AsyncSession) -> None:
    uid, aid = await _user_activity(session)
    bad = _streams([1.0, 2.0])
    with pytest.raises(ValueError, match="hr"):
        await replace_streams(session, user_id=uid, activity_id=aid, streams=bad, algo_version=1)


@pytest.mark.asyncio
async def test_unknown_channel_raises(session: AsyncSession) -> None:
    uid, aid = await _user_activity(session)
    bad = StreamSet(START, [0], {"bogus": [1.0]}, "fit_zip")
    with pytest.raises(ValueError, match="bogus"):
        await replace_streams(session, user_id=uid, activity_id=aid, streams=bad, algo_version=1)


@pytest.mark.asyncio
async def test_load_without_rls_listener_returns_none(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid, aid = await _user_activity(session)
    await replace_streams(session, user_id=uid, activity_id=aid, streams=_streams(), algo_version=1)
    await session.commit()

    assert await load_stream(app_session, activity_id=aid) is None
    await app_session.rollback()

    install_rls_listener(app_session, uid)
    loaded = await load_stream(app_session, activity_id=aid)
    assert loaded is not None
    assert loaded.channels["hr"] == [100.0, None, 120.0]
