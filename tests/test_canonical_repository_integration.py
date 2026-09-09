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
async def test_upsert_many_bulk_writes_activity_records_and_resolves_activity_id(
    session: AsyncSession,
) -> None:
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

    repo = SqlCanonicalRepository(session)
    records = _activity_records("ext-activity-1", 500)

    written = await repo.upsert_many(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_fit",
        records=records,
        raw_payload_id=raw_payload_id,
    )
    await session.commit()

    assert written == 500
    count = (
        await session.execute(
            text("SELECT COUNT(*) FROM activity_record WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar_one()
    assert count == 500

    activity_id = (
        await session.execute(
            text(
                "SELECT DISTINCT activity_id FROM activity_record WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).scalar_one()
    expected_activity_id = (
        await session.execute(
            text("SELECT id FROM activity WHERE external_id = 'ext-activity-1'"),
        )
    ).scalar_one()
    assert activity_id == expected_activity_id


@pytest.mark.asyncio
async def test_upsert_many_bulk_activity_records_is_idempotent_on_conflict(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id, "canonical-idempotent@test.com", "sub-canonical-idem")
    raw_repo = SqlRawPayloadRepository(session=session)
    raw_payload_id = await raw_repo.upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_fit",
        window=Window(start=datetime(2026, 8, 4, tzinfo=UTC), end=datetime(2026, 8, 5, tzinfo=UTC)),
        payload={"activities": []},
        content_hash=b"hash-idempotent",
    )
    await _insert_activity(session, user_id, "ext-activity-2", raw_payload_id)

    repo = SqlCanonicalRepository(session)
    records = _activity_records("ext-activity-2", 50)

    await repo.upsert_many(
        user_id=user_id, connector_id="garmin", kind="activity_fit",
        records=records, raw_payload_id=raw_payload_id,
    )
    # same records again -- e.g. a re-run of the same backfill window
    await repo.upsert_many(
        user_id=user_id, connector_id="garmin", kind="activity_fit",
        records=records, raw_payload_id=raw_payload_id,
    )
    await session.commit()

    count = (
        await session.execute(
            text("SELECT COUNT(*) FROM activity_record WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar_one()
    assert count == 50


@pytest.mark.asyncio
async def test_upsert_many_skips_activity_records_for_unknown_activity(
    session: AsyncSession,
) -> None:
    # activity_list hasn't run for this activity yet -- must not error, must not
    # write orphaned rows, and must not count them as written
    user_id = uuid4()
    await _insert_user(session, user_id, "canonical-orphan@test.com", "sub-canonical-orphan")
    raw_repo = SqlRawPayloadRepository(session=session)
    raw_payload_id = await raw_repo.upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="activity_fit",
        window=Window(start=datetime(2026, 8, 4, tzinfo=UTC), end=datetime(2026, 8, 5, tzinfo=UTC)),
        payload={"activities": []},
        content_hash=b"hash-orphan",
    )

    repo = SqlCanonicalRepository(session)
    records = _activity_records("never-listed", 10)

    written = await repo.upsert_many(
        user_id=user_id, connector_id="garmin", kind="activity_fit",
        records=records, raw_payload_id=raw_payload_id,
    )
    await session.commit()

    assert written == 0
    count = (
        await session.execute(
            text("SELECT COUNT(*) FROM activity_record WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar_one()
    assert count == 0
