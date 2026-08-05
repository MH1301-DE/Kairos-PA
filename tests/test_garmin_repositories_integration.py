from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord, RawPayloadEnvelope, Window
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.service import SyncService
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from kairos.repositories.sync_state import SqlSyncStateRepository


class SpyCanonicalRepo:
    def __init__(self) -> None:
        self.last_call: dict[str, object] | None = None

    async def upsert_many(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        records: list[CanonicalRecord],
        raw_payload_id: int,
    ) -> int:
        self.last_call = {
            "user_id": user_id,
            "connector_id": connector_id,
            "kind": kind,
            "records": records,
            "raw_payload_id": raw_payload_id,
        }
        return len(records)


class StubGarminConnector:
    connector_id = "garmin"

    def __init__(self, payload: dict[str, object], kind: str) -> None:
        self._payload = payload
        self._kind = kind

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id
        assert kind == self._kind
        return RawPayloadEnvelope(window=window, payload=self._payload)

    def normalize(self, kind: str, payload: object) -> list[CanonicalRecord]:
        del payload
        if self._kind == "hr_intraday":
            return [
                CanonicalRecord(
                    record_type="wellness_sample",
                    external_id="hr:2026-08-04T09:00:00+00:00",
                    occurred_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
                    data={"metric": "hr", "value": 62.0},
                )
            ]
        return [
            CanonicalRecord(
                record_type="sleep_session",
                external_id="sleep-123",
                occurred_at=datetime(2026, 8, 3, 22, 30, tzinfo=UTC),
                data={
                    "start_at": "2026-08-03T22:30:00+00:00",
                    "end_at": "2026-08-04T06:45:00+00:00",
                    "duration_seconds": 29700,
                    "day": "2026-08-04",
                },
            )
        ]

    def write_back(self, user_id: UUID, kind: str, records: list[CanonicalRecord]) -> object:
        del user_id, kind, records
        return None


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


@pytest.mark.asyncio
async def test_raw_payload_repository_upsert_returns_same_id_for_duplicate(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    window = Window(
        start=datetime(2026, 8, 4, tzinfo=UTC),
        end=datetime(2026, 8, 5, tzinfo=UTC),
    )

    await _insert_user(session, user_id, "raw-repo@test.com", "sub-raw-repo")
    repo = SqlRawPayloadRepository(session=session)

    first_id = await repo.upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="hr_intraday",
        window=window,
        payload={"heartRateValues": [{"timestamp": "2026-08-04T09:00:00Z", "value": 62}]},
        content_hash=b"hash-1",
    )
    second_id = await repo.upsert(
        user_id=user_id,
        connector_id="garmin",
        kind="hr_intraday",
        window=window,
        payload={"heartRateValues": [{"timestamp": "2026-08-04T09:00:00Z", "value": 62}]},
        content_hash=b"hash-1",
    )
    await session.commit()

    count = (
        await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM raw_payload
                WHERE user_id = :user_id AND connector = 'garmin' AND kind = 'hr_intraday'
                """
            ),
            {"user_id": str(user_id)},
        )
    ).scalar_one()

    assert first_id == second_id
    assert count == 1


@pytest.mark.asyncio
async def test_sync_state_repository_mark_success_sets_watermark_and_timestamps(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    first_sync = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    second_sync = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)

    await _insert_user(session, user_id, "sync-state@test.com", "sub-sync-state")
    repo = SqlSyncStateRepository(session=session)

    await repo.mark_success(
        user_id=user_id,
        connector_id="garmin",
        kind="sleep",
        synced_through=first_sync,
    )
    await repo.mark_success(
        user_id=user_id,
        connector_id="garmin",
        kind="sleep",
        synced_through=second_sync,
    )
    await session.commit()

    row = (
        await session.execute(
            text(
                """
                SELECT synced_through, last_run_at, last_success_at, consecutive_failures
                FROM sync_state
                WHERE user_id = :user_id AND connector = 'garmin' AND kind = 'sleep'
                """
            ),
            {"user_id": str(user_id)},
        )
    ).one()

    assert row.synced_through == first_sync
    assert row.last_run_at is not None
    assert row.last_success_at is not None
    assert row.consecutive_failures == 0


@pytest.mark.asyncio
async def test_sync_service_persists_raw_and_sync_state_with_db_repositories(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    window = Window(
        start=datetime(2026, 8, 4, tzinfo=UTC),
        end=datetime(2026, 8, 5, tzinfo=UTC),
    )
    payload = {"heartRateValues": [{"timestamp": "2026-08-04T09:00:00Z", "value": 62}]}

    await _insert_user(session, user_id, "sync-service@test.com", "sub-sync-service")

    canonical_spy = SpyCanonicalRepo()
    service = SyncService(
        raw_repo=SqlRawPayloadRepository(session=session),
        canonical_repo=canonical_spy,
        sync_state_repo=SqlSyncStateRepository(session=session),
        hash_payload=payload_sha256,
    )

    result = await service.run_window(
        connector=StubGarminConnector(payload=payload, kind="hr_intraday"),
        user_id=user_id,
        kind="hr_intraday",
        window=window,
    )
    await session.commit()

    raw_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM raw_payload WHERE user_id = :user_id"),
            {"user_id": str(user_id)},
        )
    ).scalar_one()
    state = (
        await session.execute(
            text(
                """
                SELECT synced_through
                FROM sync_state
                WHERE user_id = :user_id AND connector = 'garmin' AND kind = 'hr_intraday'
                """
            ),
            {"user_id": str(user_id)},
        )
    ).one()

    assert result.records_written == 1
    assert raw_count == 1
    assert state.synced_through == window.end
    assert canonical_spy.last_call is not None
    assert canonical_spy.last_call["raw_payload_id"] == result.raw_payload_id