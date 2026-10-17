from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.fit_archive import ingest_fit_files, load_fit_messages
from kairos.activities.stream_repository import load_stream
from kairos.connectors.types import RawFile, RawPayloadEnvelope, Window
from kairos.db.models import Activity, RawPayload
from kairos.db.rls import install_rls_listener
from kairos.ingestion import garmin_sync
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from tests.test_fit_decoder import mini_fit_zip

START = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


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


async def _activity(session: AsyncSession, uid: uuid.UUID, external_id: str) -> int:
    row = await session.execute(
        text(
            "INSERT INTO activity (user_id, external_id, start_at) VALUES (:u, :x, :s) "
            "RETURNING id"
        ),
        {"u": str(uid), "x": external_id, "s": START},
    )
    return int(row.scalar_one())


def _file(key: str, content: bytes) -> RawFile:
    return RawFile(
        kind="activity_fit_file",
        key=key,
        window_start=START,
        content=content,
        payload_format="fit_zip",
    )


def _truncated_fit_zip() -> bytes:
    full = mini_fit_zip(START, list(range(100, 160)))
    fit = zipfile.ZipFile(io.BytesIO(full)).read("activity.fit")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("activity.fit", fit[: len(fit) // 2])
    return buf.getvalue()


# decodable without exception, but the SDK reports errors (and partial records)
UNDECODABLE = {"garbage": b"definitely not a fit file", "truncated": _truncated_fit_zip()}


async def _get_activity(session: AsyncSession, activity_id: int) -> Activity:
    return (await session.execute(select(Activity).where(Activity.id == activity_id))).scalar_one()


@pytest.mark.asyncio
async def test_upsert_file_stores_zip_unchanged_and_is_idempotent(session: AsyncSession) -> None:
    uid = await _user(session)
    repo = SqlRawPayloadRepository(session=session)
    content = mini_fit_zip(START, [120, 121])

    first = await repo.upsert_file(user_id=uid, connector_id="garmin", file=_file("1", content))
    second = await repo.upsert_file(user_id=uid, connector_id="garmin", file=_file("1", content))

    assert first == second
    row = (await session.execute(select(RawPayload).where(RawPayload.id == first))).scalar_one()
    assert row.kind == "activity_fit_file"
    assert row.payload_format == "fit_zip"
    assert row.payload_gzip == content
    assert row.content_hash == hashlib.sha256(content).digest()
    assert row.window_start == START
    assert row.window_end == START


@pytest.mark.asyncio
async def test_ingest_fit_files_writes_streams_and_isolates_broken_zip(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    good_id = await _activity(session, uid, "good")
    bad_id = await _activity(session, uid, "bad")
    broken_ids = {key: await _activity(session, uid, key) for key in UNDECODABLE}
    repo = SqlRawPayloadRepository(session=session)
    files = [
        _file("bad", b"PK\x03\x04 not really a zip"),
        *(_file(key, content) for key, content in UNDECODABLE.items()),
        _file("good", mini_fit_zip(START, [120, 130, 140])),
        _file("unlisted", mini_fit_zip(START, [99])),
    ]
    ids = {
        f.key: await repo.upsert_file(user_id=uid, connector_id="garmin", file=f) for f in files
    }
    await session.commit()
    # RLS-enforced role, as in the sync job
    install_rls_listener(app_session, uid)

    failed = await ingest_fit_files(app_session, user_id=uid, file_ids_by_key=ids, files=files)
    await app_session.commit()

    assert failed == ["bad", "garbage", "truncated"]
    good = await _get_activity(app_session, good_id)
    assert good.fit_payload_id == ids["good"]
    for activity_id in (bad_id, *broken_ids.values()):
        assert (await _get_activity(app_session, activity_id)).fit_payload_id is None
        assert await load_stream(app_session, activity_id=activity_id) is None
    loaded = await load_stream(app_session, activity_id=good_id)
    assert loaded is not None
    assert loaded.source == "fit_zip"
    assert loaded.start_at == START
    assert loaded.t_offset_s == [0, 1, 2]
    assert loaded.channels["hr"] == [120.0, 130.0, 140.0]
    assert loaded.channels["distance_m"] == [0.0, 2.5, 5.0]


@pytest.mark.asyncio
async def test_load_fit_messages_prefers_zip_then_json_fallback(session: AsyncSession) -> None:
    uid = await _user(session)
    zip_id = await _activity(session, uid, "zipped")
    json_id = await _activity(session, uid, "json-only")
    none_id = await _activity(session, uid, "nothing")
    repo = SqlRawPayloadRepository(session=session)
    content = mini_fit_zip(START, [111, 112])
    fit_id = await repo.upsert_file(
        user_id=uid, connector_id="garmin", file=_file("zipped", content)
    )
    await ingest_fit_files(
        session, user_id=uid, file_ids_by_key={"zipped": fit_id}, files=[_file("zipped", content)]
    )
    day = Window(start=START.replace(hour=0), end=START.replace(hour=0) + timedelta(days=1))
    records = [{"timestamp": START.isoformat(), "heart_rate": 101}]
    for i, hr in enumerate((90, 101)):
        await repo.upsert(
            user_id=uid,
            connector_id="garmin",
            kind="activity_fit",
            window=day,
            payload={"activities": [{
                "activity_id": "json-only",
                "records": [{**records[0], "heart_rate": hr}],
                "sessions": [{"sport": "running"}],
                "laps": [],
            }]},
            content_hash=f"json-{uid}-{i}".encode(),
        )
        # fetched_at defaults to now() which is constant within a transaction
        await session.execute(
            text("UPDATE raw_payload SET fetched_at = :t WHERE content_hash = :h"),
            {"t": START + timedelta(hours=i), "h": f"json-{uid}-{i}".encode()},
        )

    zipped = await load_fit_messages(session, activity=await _get_activity(session, zip_id))
    assert zipped is not None
    messages, source = zipped
    assert source == "fit_zip"
    assert [r["heart_rate"] for r in messages["record_mesgs"]] == [111, 112]

    from_json = await load_fit_messages(session, activity=await _get_activity(session, json_id))
    assert from_json is not None
    messages, source = from_json
    assert source == "fit_json"
    assert messages["record_mesgs"] == [{"timestamp": START.isoformat(), "heart_rate": 101}]
    assert messages["session_mesgs"] == [{"sport": "running"}]
    assert messages["lap_mesgs"] == []

    assert await load_fit_messages(session, activity=await _get_activity(session, none_id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(UNDECODABLE))
async def test_load_fit_messages_falls_back_to_json_for_undecodable_zip(
    session: AsyncSession, key: str
) -> None:
    uid = await _user(session)
    activity_id = await _activity(session, uid, key)
    repo = SqlRawPayloadRepository(session=session)
    fit_id = await repo.upsert_file(
        user_id=uid, connector_id="garmin", file=_file(key, UNDECODABLE[key])
    )
    # linked as if archived before strict decoding existed
    await session.execute(
        text("UPDATE activity SET fit_payload_id = :f WHERE id = :a"),
        {"f": fit_id, "a": activity_id},
    )
    day = Window(start=START.replace(hour=0), end=START.replace(hour=0) + timedelta(days=1))
    await repo.upsert(
        user_id=uid,
        connector_id="garmin",
        kind="activity_fit",
        window=day,
        payload={"activities": [{
            "activity_id": key,
            "records": [{"timestamp": START.isoformat(), "heart_rate": 77}],
        }]},
        content_hash=f"json-{uid}".encode(),
    )

    result = await load_fit_messages(session, activity=await _get_activity(session, activity_id))

    assert result is not None
    messages, source = result
    assert source == "fit_json"
    assert messages["record_mesgs"] == [{"timestamp": START.isoformat(), "heart_rate": 77}]


@pytest.mark.asyncio
async def test_sync_hook_ingests_only_activity_fit_windows() -> None:
    uid = uuid.uuid4()
    session = AsyncMock()
    envelope = RawPayloadEnvelope(
        window=Window(start=START, end=START + timedelta(days=1)),
        payload={"activities": []},
        files=(_file("1", b"zip"),),
    )
    hook = garmin_sync._make_fit_ingest_hook(session, uid, set())

    with (
        patch.object(garmin_sync, "ingest_fit_files", AsyncMock(return_value=[])) as ingest,
        patch.object(garmin_sync, "_derive_ingested", AsyncMock()) as derive,
    ):
        await hook("activity_list", envelope, 1, {"1": 5})
        await hook("activity_fit", envelope, 1, {"1": 5})

    ingest.assert_awaited_once_with(
        session, user_id=uid, file_ids_by_key={"1": 5}, files=envelope.files
    )
    derive.assert_awaited_once_with(session, uid, ["1"])
