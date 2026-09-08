from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from kairos.connectors.types import CanonicalRecord, RawPayloadEnvelope, Window
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.service import BackfillResult, SyncService


class StubConnector:
    connector_id = "garmin"

    def __init__(self) -> None:
        self.windows: list[Window] = []

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id, kind
        self.windows.append(window)
        return RawPayloadEnvelope(window=window, payload={"ok": True})

    def normalize(self, kind: str, payload: object) -> list[CanonicalRecord]:
        del kind
        return [
            CanonicalRecord(
                record_type="daily_summary",
                external_id="daily:2026-08-01",
                data={"steps": 1234},
                occurred_at=None,
            )
        ]

    def write_back(self, user_id: UUID, kind: str, records: list[CanonicalRecord]) -> object:
        del user_id, kind, records
        return None


class StubRawRepo:
    async def upsert(self, **_: object) -> int:
        return 1


class StubCanonicalRepo:
    async def upsert_many(self, **_: object) -> int:
        return 1


class StubSyncStateRepo:
    def __init__(self) -> None:
        self.cursor: datetime | None = None
        self.complete_from: datetime | None = None
        self.complete_to: datetime | None = None
        self.cursor_updates: list[datetime] = []
        self.complete_updates: list[tuple[datetime, datetime]] = []

    async def mark_success(self, **_: object) -> None:
        return None

    async def get_backfill_state(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
    ) -> tuple[datetime | None, datetime | None, datetime | None]:
        del user_id, connector_id, kind
        return self.cursor, self.complete_from, self.complete_to

    async def set_backfill_cursor(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        cursor: datetime,
    ) -> None:
        del user_id, connector_id, kind
        self.cursor = cursor
        self.cursor_updates.append(cursor)

    async def mark_backfill_complete(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        complete_from: datetime,
        complete_to: datetime,
    ) -> None:
        del user_id, connector_id, kind
        self.cursor = None
        self.complete_from = complete_from
        self.complete_to = complete_to
        self.complete_updates.append((complete_from, complete_to))


def _service(sync_state_repo: StubSyncStateRepo) -> SyncService:
    return SyncService(
        raw_repo=StubRawRepo(),
        canonical_repo=StubCanonicalRepo(),
        sync_state_repo=sync_state_repo,
        hash_payload=payload_sha256,
    )


@pytest.mark.asyncio
async def test_run_backfill_decrements_cursor_until_from_date() -> None:
    repo = StubSyncStateRepo()
    service = _service(repo)
    connector = StubConnector()
    user_id = uuid4()

    from_date = datetime(2026, 8, 1, tzinfo=UTC)
    to_date = datetime(2026, 8, 4, tzinfo=UTC)

    result = await service.run_backfill(
        connector=connector,
        user_id=user_id,
        kind="sleep",
        from_date=from_date,
        to_date=to_date,
        step=timedelta(days=1),
    )

    assert result == BackfillResult(windows_processed=3, completed=True, next_cursor=None)
    assert connector.windows == [
        Window(start=datetime(2026, 8, 3, tzinfo=UTC), end=datetime(2026, 8, 4, tzinfo=UTC)),
        Window(start=datetime(2026, 8, 2, tzinfo=UTC), end=datetime(2026, 8, 3, tzinfo=UTC)),
        Window(start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    assert repo.cursor_updates == [
        datetime(2026, 8, 3, tzinfo=UTC),
        datetime(2026, 8, 2, tzinfo=UTC),
        datetime(2026, 8, 1, tzinfo=UTC),
    ]
    assert repo.complete_updates == [(from_date, to_date)]


@pytest.mark.asyncio
async def test_run_backfill_can_stop_and_resume_from_cursor() -> None:
    repo = StubSyncStateRepo()
    service = _service(repo)
    connector = StubConnector()
    user_id = uuid4()

    from_date = datetime(2026, 8, 1, tzinfo=UTC)
    to_date = datetime(2026, 8, 4, tzinfo=UTC)

    stop_calls = 0

    def should_stop() -> bool:
        nonlocal stop_calls
        stop_calls += 1
        return stop_calls == 1

    first_run = await service.run_backfill(
        connector=connector,
        user_id=user_id,
        kind="sleep",
        from_date=from_date,
        to_date=to_date,
        step=timedelta(days=1),
        should_stop=should_stop,
    )

    assert first_run == BackfillResult(
        windows_processed=1,
        completed=False,
        next_cursor=datetime(2026, 8, 3, tzinfo=UTC),
    )
    assert repo.complete_updates == []

    resumed_connector = StubConnector()
    second_run = await service.run_backfill(
        connector=resumed_connector,
        user_id=user_id,
        kind="sleep",
        from_date=from_date,
        to_date=to_date,
        step=timedelta(days=1),
    )

    assert second_run == BackfillResult(windows_processed=2, completed=True, next_cursor=None)
    assert resumed_connector.windows == [
        Window(start=datetime(2026, 8, 2, tzinfo=UTC), end=datetime(2026, 8, 3, tzinfo=UTC)),
        Window(start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    assert repo.complete_updates == [(from_date, to_date)]


@pytest.mark.asyncio
async def test_run_backfill_skips_when_completion_marker_reaches_target() -> None:
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2026, 8, 1, tzinfo=UTC)
    repo.complete_to = datetime(2026, 8, 4, tzinfo=UTC)
    service = _service(repo)
    connector = StubConnector()
    user_id = uuid4()

    result = await service.run_backfill(
        connector=connector,
        user_id=user_id,
        kind="sleep",
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert result == BackfillResult(windows_processed=0, completed=True, next_cursor=None)
    assert connector.windows == []


@pytest.mark.asyncio
async def test_run_backfill_extends_further_into_the_past_when_requested() -> None:
    """A second, explicit request for an OLDER range than what's already
    covered must not short-circuit -- this is what lets a follow-up backfill
    fill in older history (e.g. extending 15 months of coverage to 24) without
    re-fetching the part that's already there."""
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2026, 8, 2, tzinfo=UTC)
    repo.complete_to = datetime(2026, 8, 4, tzinfo=UTC)
    service = _service(repo)
    connector = StubConnector()
    user_id = uuid4()

    # requests exactly the not-yet-covered older slice
    result = await service.run_backfill(
        connector=connector,
        user_id=user_id,
        kind="sleep",
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 2, tzinfo=UTC),
        step=timedelta(days=1),
    )

    assert result == BackfillResult(windows_processed=1, completed=True, next_cursor=None)
    assert connector.windows == [
        Window(start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    # SyncService reports exactly the range it just walked; reconciling this
    # against the wider previously-known coverage (GREATEST/LEAST so the
    # forward bound never regresses) is the SQL repository's job, not
    # SyncService's -- covered by mark_backfill_complete's own SQL, this stub
    # intentionally doesn't replicate that merge.
    assert repo.complete_updates == [
        (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 2, tzinfo=UTC)),
    ]
