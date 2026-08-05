from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import RawPayload, SyncFailure


@pytest.mark.asyncio
async def test_raw_payload_has_dedupe_uniqueness_constraint(session: AsyncSession) -> None:
    user_id = uuid4()
    now = datetime(2026, 8, 4, tzinfo=UTC)

    await session.execute(
        text(
            """
        INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
        VALUES (:id, :email, :name, :sub, 'UTC', 'user')
        """
        ),
        {
            "id": str(user_id),
            "email": "dedupe@test.com",
            "name": "Dedupe",
            "sub": "sub-dedupe",
        },
    )

    session.add(
        RawPayload(
            user_id=user_id,
            connector="garmin",
            kind="activity",
            window_start=now,
            window_end=now,
            content_hash=b"hash-a",
            payload_gzip=b"{}",
        )
    )
    await session.commit()

    session.add(
        RawPayload(
            user_id=user_id,
            connector="garmin",
            kind="activity",
            window_start=now,
            window_end=now,
            content_hash=b"hash-a",
            payload_gzip=b"{}",
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_sync_failure_persists_tenant_key_and_metadata(session: AsyncSession) -> None:
    user_id = uuid4()

    await session.execute(
        text(
            """
        INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
        VALUES (:id, :email, :name, :sub, 'UTC', 'user')
        """
        ),
        {
            "id": str(user_id),
            "email": "failure@test.com",
            "name": "Failure",
            "sub": "sub-failure",
        },
    )

    row = SyncFailure(
        user_id=user_id,
        connector="garmin",
        kind="activity",
        details={"status": 429, "request_id": "req-1"},
        error_code="rate_limit",
        error_message="Too many requests",
    )
    session.add(row)
    await session.commit()

    persisted = await session.get(SyncFailure, row.id)

    assert persisted is not None
    assert persisted.user_id == user_id
    assert persisted.connector == "garmin"
    assert persisted.kind == "activity"
    assert persisted.details["status"] == 429
    assert persisted.details["request_id"] == "req-1"