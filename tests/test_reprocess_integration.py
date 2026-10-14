from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import garminconnect
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.reprocess import reprocess_activities
from kairos.activities.stream_repository import load_stream
from kairos.connectors.types import JSONValue, Window
from kairos.db.models import Activity, ActivityStream
from kairos.db.rls import install_rls_listener
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from tests.test_fit_decoder import mini_fit_zip

START = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
DAY = Window(start=START.replace(hour=0), end=START.replace(hour=0) + timedelta(days=1))
IDS = ("1001", "1002", "1003")


class FakeGarmin:
    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.calls: list[str] = []
        self._errors = errors or {}

    def download_activity(self, activity_id: str, dl_fmt: Any = None) -> bytes:
        del dl_fmt
        self.calls.append(str(activity_id))
        if str(activity_id) in self._errors:
            raise self._errors[str(activity_id)]
        return mini_fit_zip(START, [150 + len(self.calls), 151, 152])


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def _user(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'UTC', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    await session.commit()
    return uid


def _summary(external_id: str, start: datetime, name: str) -> dict[str, JSONValue]:
    return {
        "activityId": int(external_id),
        "activityName": name,
        "startTimeGMT": start.strftime("%Y-%m-%d %H:%M:%S"),
        "activityType": {"typeKey": "running"},
        "duration": 60.0,
    }


async def _payload(
    session: AsyncSession,
    uid: uuid.UUID,
    *,
    kind: str,
    payload: JSONValue,
    tag: str,
    fetched_at: datetime,
    window: Window = DAY,
) -> None:
    content_hash = f"{kind}-{uid}-{tag}".encode()
    await SqlRawPayloadRepository(session=session).upsert(
        user_id=uid,
        connector_id="garmin",
        kind=kind,
        window=window,
        payload=payload,
        content_hash=content_hash,
    )
    # fetched_at defaults to now() which is constant within a transaction
    await session.execute(
        text("UPDATE raw_payload SET fetched_at = :t WHERE content_hash = :h"),
        {"t": fetched_at, "h": content_hash},
    )


async def _seed_list(session: AsyncSession, uid: uuid.UUID, ids: tuple[str, ...] = IDS) -> None:
    await _payload(
        session,
        uid,
        kind="activity_list",
        payload=[_summary(x, START + timedelta(hours=i), f"Run {x}") for i, x in enumerate(ids)],
        tag="list",
        fetched_at=START,
    )


async def _seed_json(session: AsyncSession, uid: uuid.UUID, external_id: str, hr: int) -> None:
    await _payload(
        session,
        uid,
        kind="activity_fit",
        payload={"activities": [{
            "activity_id": external_id,
            "records": [{"timestamp": START.isoformat(), "heart_rate": hr}],
        }]},
        tag=f"json-{external_id}-{hr}",
        fetched_at=START + timedelta(hours=hr),
    )


async def _activities(session: AsyncSession, uid: uuid.UUID) -> dict[str, Activity]:
    rows = (await session.execute(select(Activity).where(Activity.user_id == uid))).scalars()
    return {a.external_id: a for a in rows}


async def _run(
    session: AsyncSession, uid: uuid.UUID, garmin: FakeGarmin, **kwargs: Any
) -> Any:
    install_rls_listener(session, uid)
    params: dict[str, Any] = {
        "from_date": None,
        "to_date": None,
        "activity_ids": None,
        "refetch_fit": False,
        "pause_s": 2.0,
    }
    params.update(kwargs)
    return await reprocess_activities(session, user_id=uid, garmin=garmin, **params)


@pytest.mark.asyncio
async def test_without_refetch_uses_newest_payloads_and_never_calls_garmin(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    for tag, name, hours in (("new", "Newer", 2), ("old", "Older", 1)):
        await _payload(
            session,
            uid,
            kind="activity_list",
            payload=[_summary("1001", START, name)],
            tag=tag,
            fetched_at=START + timedelta(hours=hours),
        )
    await _seed_json(session, uid, "1001", 90)
    await _seed_json(session, uid, "1001", 101)
    await session.commit()
    garmin = FakeGarmin()
    sleep = SleepRecorder()

    result = await _run(app_session, uid, garmin, sleep=sleep)

    assert garmin.calls == []
    assert sleep.calls == []
    assert result.activities_total == 1
    assert result.streams_written == 1
    assert (result.from_zip, result.from_json, result.fetched) == (0, 1, 0)
    assert result.no_data == [] and result.fetch_failed == []
    assert result.aborted_reason is None
    activity = (await _activities(app_session, uid))["1001"]
    assert activity.name == "Newer"
    loaded = await load_stream(app_session, activity_id=activity.id)
    assert loaded is not None
    assert loaded.source == "fit_json"
    assert loaded.channels["hr"] == [101.0]


@pytest.mark.asyncio
async def test_refetch_downloads_missing_zips_with_pause_between(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    await _seed_list(session, uid)
    await session.commit()
    garmin = FakeGarmin()
    sleep = SleepRecorder()
    progress: list[tuple[int, int]] = []

    result = await _run(
        app_session,
        uid,
        garmin,
        refetch_fit=True,
        sleep=sleep,
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert garmin.calls == list(IDS)
    assert sleep.calls == [2.0, 2.0]
    assert (result.fetched, result.from_zip, result.from_json) == (3, 3, 0)
    assert result.streams_written == 3
    assert progress[-1] == (3, 3)
    for activity in (await _activities(app_session, uid)).values():
        assert activity.fit_payload_id is not None
        loaded = await load_stream(app_session, activity_id=activity.id)
        assert loaded is not None and loaded.source == "fit_zip"


@pytest.mark.asyncio
async def test_failed_download_is_listed_and_falls_back_to_json(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    await _seed_list(session, uid)
    await _seed_json(session, uid, "1002", 88)
    await session.commit()
    garmin = FakeGarmin({"1002": garminconnect.GarminConnectNotFoundError("404 gone")})

    result = await _run(app_session, uid, garmin, refetch_fit=True, sleep=SleepRecorder())

    assert garmin.calls == list(IDS)
    assert result.fetch_failed == [{"activity_id": "1002", "reason": "404 gone"}]
    assert result.aborted_reason is None
    assert (result.fetched, result.from_zip, result.from_json) == (2, 2, 1)
    fallback = (await _activities(app_session, uid))["1002"]
    assert fallback.fit_payload_id is None
    loaded = await load_stream(app_session, activity_id=fallback.id)
    assert loaded is not None and loaded.source == "fit_json"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (garminconnect.GarminConnectTooManyRequestsError("429"), "rate_limited"),
        (garminconnect.GarminConnectAuthenticationError("401"), "auth"),
    ],
)
async def test_rate_limit_or_auth_aborts_further_downloads(
    session: AsyncSession, app_session: AsyncSession, error: Exception, reason: str
) -> None:
    uid = await _user(session)
    await _seed_list(session, uid)
    await _seed_json(session, uid, "1003", 77)
    await session.commit()
    garmin = FakeGarmin({"1002": error})

    result = await _run(app_session, uid, garmin, refetch_fit=True, sleep=SleepRecorder())

    assert garmin.calls == ["1001", "1002"]
    assert result.aborted_reason == reason
    assert result.fetch_failed == []
    assert (result.fetched, result.from_zip, result.from_json) == (1, 1, 1)
    assert result.no_data == ["1002"]


@pytest.mark.asyncio
async def test_filters_by_date_and_activity_ids(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    await _seed_list(session, uid, ("2001", "2002"))
    later = START + timedelta(days=3)
    await _payload(
        session,
        uid,
        kind="activity_list",
        payload=[_summary("2003", later, "Later")],
        tag="later",
        fetched_at=later,
        window=Window(start=DAY.start + timedelta(days=3), end=DAY.end + timedelta(days=3)),
    )
    await session.commit()

    in_range = await _run(
        app_session, uid, FakeGarmin(), from_date=later.date(), to_date=later.date()
    )
    assert in_range.activities_total == 1
    assert set(await _activities(app_session, uid)) == {"2003"}
    assert in_range.no_data == ["2003"]

    await _run(app_session, uid, FakeGarmin())
    by_id = (await _activities(app_session, uid))["2002"].id
    combined = await _run(
        app_session, uid, FakeGarmin(), activity_ids=[by_id], to_date=date(2026, 8, 4)
    )
    assert combined.activities_total == 1
    assert combined.no_data == ["2002"]


@pytest.mark.asyncio
async def test_reprocess_twice_keeps_stream_row_counts(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    await _seed_list(session, uid)
    await _seed_json(session, uid, "1003", 70)
    await session.commit()

    async def _count() -> int:
        stmt = select(func.count()).select_from(ActivityStream).where(ActivityStream.user_id == uid)
        return int((await app_session.execute(stmt)).scalar_one())

    await _run(app_session, uid, FakeGarmin(), refetch_fit=True, sleep=SleepRecorder())
    first = await _count()
    await _run(app_session, uid, FakeGarmin(), refetch_fit=True, sleep=SleepRecorder())

    assert first > 0
    assert await _count() == first
