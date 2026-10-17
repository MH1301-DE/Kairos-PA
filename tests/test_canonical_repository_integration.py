from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord, Window
from kairos.repositories.canonical import SqlCanonicalRepository
from kairos.repositories.raw_payload import SqlRawPayloadRepository


async def _insert_user(session: AsyncSession, user_id: UUID, email: str, sub: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, :name, :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": email, "name": "Test", "sub": sub},
    )


async def _insert_activity(
    session: AsyncSession, user_id: UUID, external_id: str, raw_payload_id: int
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO activity (user_id, external_id, start_at, raw_payload_id)
            VALUES (:user_id, :external_id, :start_at, :raw_payload_id)
            """
        ),
        {
            "user_id": str(user_id),
            "external_id": external_id,
            "start_at": datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
            "raw_payload_id": raw_payload_id,
        },
    )


def _activity_records(external_id: str, n: int) -> list[CanonicalRecord]:
    base = datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC)
    return [
        CanonicalRecord(
            record_type="activity_record",
            external_id=f"{external_id}:hr:{i}",
            occurred_at=base + timedelta(seconds=i),
            data={"activity_external_id": external_id, "metric": "hr", "value": float(100 + i)},
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_upsert_many_no_longer_writes_activity_records(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id, "canonical-bulk@test.com", "sub-canonical-bulk")
    raw_repo = SqlRawPayloadRepository(session=session)
    raw_payload_id = await raw_repo.upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_fit",
        window=Window(start=datetime(2026, 8, 4, tzinfo=UTC), end=datetime(2026, 8, 5, tzinfo=UTC)),
        payload={"activities": []},
        content_hash=b"hash-activity-fit",
    )
    await _insert_activity(session, user_id, "ext-activity-1", raw_payload_id)

    written = await SqlCanonicalRepository(session).upsert_many(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_fit",
        records=_activity_records("ext-activity-1", 50),
        raw_payload_id=raw_payload_id,
    )
    await session.commit()

    assert written == 0


def _activity_record(external_id: str, start: datetime, name: str) -> CanonicalRecord:
    return CanonicalRecord(
        record_type="activity",
        external_id=external_id,
        occurred_at=start,
        data={
            "name": name,
            "sport": "running",
            "sport_profile": "running",
            "garmin_type_id": 1,
            "garmin_parent_type_id": 17,
            "start_local": (start + timedelta(hours=2)).replace(tzinfo=None).isoformat(),
            "utc_offset_min": 120,
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "distance_m": 10000.0,
            "lap_count": 10,
        },
    )


async def _upsert_activity(
    session: AsyncSession, user_id: UUID, raw_payload_id: int, record: CanonicalRecord
) -> None:
    await SqlCanonicalRepository(session).upsert_many(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_list",
        records=[record],
        raw_payload_id=raw_payload_id,
    )


async def _activity_setup(session: AsyncSession, email: str) -> tuple[UUID, int]:
    user_id = uuid4()
    await _insert_user(session, user_id, email, f"sub-{email}")
    raw_payload_id = await SqlRawPayloadRepository(session=session).upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_list",
        window=Window(start=datetime(2026, 8, 4, tzinfo=UTC), end=datetime(2026, 8, 5, tzinfo=UTC)),
        payload=[],
        content_hash=email.encode(),
    )
    return user_id, raw_payload_id


@pytest.mark.asyncio
async def test_activity_upsert_updates_times_and_new_columns(session: AsyncSession) -> None:
    user_id, raw_id = await _activity_setup(session, "upsert-times@test.com")
    first = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await _upsert_activity(session, user_id, raw_id, _activity_record("a-1", first, "Run"))
    moved = first + timedelta(minutes=30)
    await _upsert_activity(session, user_id, raw_id, _activity_record("a-1", moved, "Run 2"))

    row = (
        await session.execute(
            text(
                "SELECT name, start_at, end_at, start_local, utc_offset_min, sport_profile,"
                " lap_count FROM activity WHERE user_id = :u"
            ),
            {"u": str(user_id)},
        )
    ).one()
    assert row.name == "Run 2"
    assert row.start_at == moved
    assert row.end_at == moved + timedelta(hours=1)
    assert row.start_local == datetime(2026, 8, 4, 11, 30)
    assert row.utc_offset_min == 120
    assert row.sport_profile == "running"
    assert row.lap_count == 10


@pytest.mark.asyncio
async def test_activity_upsert_reactivates_deleted_and_keeps_fit_payload(
    session: AsyncSession,
) -> None:
    user_id, raw_id = await _activity_setup(session, "upsert-reactivate@test.com")
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await _upsert_activity(session, user_id, raw_id, _activity_record("a-2", start, "Run"))
    await session.execute(
        text(
            "UPDATE activity SET deleted_at = now(), deleted_reason = 'garmin_sync',"
            " fit_payload_id = :p WHERE user_id = :u"
        ),
        {"u": str(user_id), "p": raw_id},
    )

    await _upsert_activity(session, user_id, raw_id, _activity_record("a-2", start, "Run"))

    row = (
        await session.execute(
            text("SELECT deleted_at, deleted_reason, fit_payload_id FROM activity"
                 " WHERE user_id = :u"),
            {"u": str(user_id)},
        )
    ).one()
    assert row.deleted_at is None
    assert row.deleted_reason is None
    assert row.fit_payload_id == raw_id
