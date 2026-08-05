from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from kairos.connectors.types import CanonicalRecord, RawPayloadEnvelope, Window
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.service import SyncService


class SpyConnector:
    connector_id = "spy"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fetch_args: tuple[UUID, str, Window] | None = None
        self.normalize_args: object | None = None

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        self.events.append("fetch")
        self.fetch_args = (user_id, kind, window)
        payload = {"steps": 1200, "nested": {"a": 1, "b": 2}}
        return RawPayloadEnvelope(window=window, payload=payload)

    def normalize(self, kind: str, payload: object) -> list[CanonicalRecord]:
        self.events.append("normalize")
        self.normalize_args = payload
        return [CanonicalRecord(record_type="activity", external_id="a1", data={"steps": 1200})]

    def write_back(self, user_id: UUID, kind: str, records: list[CanonicalRecord]) -> Any:
        del user_id, kind, records
        self.events.append("write_back")
        return None


class SpyRawRepo:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_call: dict[str, object] | None = None

    async def upsert(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        window: Window,
        payload: object,
        content_hash: bytes,
    ) -> int:
        self.events.append("raw_upsert")
        self.last_call = {
            "user_id": user_id,
            "connector_id": connector_id,
            "kind": kind,
            "window": window,
            "payload": payload,
            "content_hash": content_hash,
        }
        return 7


class SpyCanonicalRepo:
    def __init__(self, events: list[str]) -> None:
        self.events = events
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
        self.events.append("canonical_upsert_many")
        self.last_call = {
            "user_id": user_id,
            "connector_id": connector_id,
            "kind": kind,
            "records": records,
            "raw_payload_id": raw_payload_id,
        }
        return len(records)


class SpySyncStateRepo:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_call: dict[str, object] | None = None

    async def mark_success(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        synced_through: datetime,
    ) -> None:
        self.events.append("mark_success")
        self.last_call = {
            "user_id": user_id,
            "connector_id": connector_id,
            "kind": kind,
            "synced_through": synced_through,
        }


class SpySyncFailureRepo:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.last_call: dict[str, object] | None = None

    async def record_failure(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        window: Window,
        error_code: str,
        error_message: str,
        retryable: bool,
        details: object,
    ) -> None:
        self.events.append("record_failure")
        self.last_call = {
            "user_id": user_id,
            "connector_id": connector_id,
            "kind": kind,
            "window": window,
            "error_code": error_code,
            "error_message": error_message,
            "retryable": retryable,
            "details": details,
        }


class FailingConnector(SpyConnector):
    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id, kind, window
        self.events.append("fetch")
        raise RuntimeError("upstream timeout")


class NonRetryableFailingConnector(SpyConnector):
    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id, kind, window
        self.events.append("fetch")
        raise ValueError("invalid request")


def test_payload_sha256_is_deterministic_for_different_key_order() -> None:
    first = {"b": 2, "a": 1, "nested": {"z": 9, "m": 7}}
    second = {"nested": {"m": 7, "z": 9}, "a": 1, "b": 2}

    assert payload_sha256(first) == payload_sha256(second)


@pytest.mark.asyncio
async def test_sync_service_orchestrates_steps_in_order() -> None:
    events: list[str] = []
    connector = SpyConnector(events)
    raw_repo = SpyRawRepo(events)
    canonical_repo = SpyCanonicalRepo(events)
    sync_state_repo = SpySyncStateRepo(events)

    service = SyncService(
        raw_repo=raw_repo,
        canonical_repo=canonical_repo,
        sync_state_repo=sync_state_repo,
        hash_payload=payload_sha256,
    )

    user_id = uuid4()
    window = Window(
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    result = await service.run_window(
        connector=connector,
        user_id=user_id,
        kind="activities",
        window=window,
    )

    assert events == ["fetch", "raw_upsert", "normalize", "canonical_upsert_many", "mark_success"]

    assert connector.fetch_args == (user_id, "activities", window)
    assert raw_repo.last_call is not None
    assert raw_repo.last_call["connector_id"] == "spy"
    assert raw_repo.last_call["kind"] == "activities"
    assert connector.normalize_args == raw_repo.last_call["payload"]

    assert canonical_repo.last_call is not None
    assert canonical_repo.last_call["raw_payload_id"] == 7

    assert sync_state_repo.last_call is not None
    assert sync_state_repo.last_call["synced_through"] == window.end
    assert result.records_written == 1


@pytest.mark.asyncio
async def test_sync_service_records_failure_and_reraises() -> None:
    events: list[str] = []
    connector = FailingConnector(events)
    raw_repo = SpyRawRepo(events)
    canonical_repo = SpyCanonicalRepo(events)
    sync_state_repo = SpySyncStateRepo(events)
    sync_failure_repo = SpySyncFailureRepo(events)

    service = SyncService(
        raw_repo=raw_repo,
        canonical_repo=canonical_repo,
        sync_state_repo=sync_state_repo,
        hash_payload=payload_sha256,
        sync_failure_repo=sync_failure_repo,
    )

    user_id = uuid4()
    window = Window(
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="upstream timeout"):
        await service.run_window(
            connector=connector,
            user_id=user_id,
            kind="activities",
            window=window,
        )

    assert events == ["fetch", "record_failure"]
    assert sync_failure_repo.last_call is not None
    assert sync_failure_repo.last_call["user_id"] == user_id
    assert sync_failure_repo.last_call["connector_id"] == "spy"
    assert sync_failure_repo.last_call["kind"] == "activities"
    assert sync_failure_repo.last_call["window"] == window
    assert sync_failure_repo.last_call["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_sync_service_marks_non_retryable_failures() -> None:
    events: list[str] = []
    connector = NonRetryableFailingConnector(events)
    raw_repo = SpyRawRepo(events)
    canonical_repo = SpyCanonicalRepo(events)
    sync_state_repo = SpySyncStateRepo(events)
    sync_failure_repo = SpySyncFailureRepo(events)

    service = SyncService(
        raw_repo=raw_repo,
        canonical_repo=canonical_repo,
        sync_state_repo=sync_state_repo,
        hash_payload=payload_sha256,
        sync_failure_repo=sync_failure_repo,
    )

    user_id = uuid4()
    window = Window(
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="invalid request"):
        await service.run_window(
            connector=connector,
            user_id=user_id,
            kind="activities",
            window=window,
        )

    assert events == ["fetch", "record_failure"]
    assert sync_failure_repo.last_call is not None
    assert sync_failure_repo.last_call["error_code"] == "ValueError"
    assert sync_failure_repo.last_call["retryable"] is False
