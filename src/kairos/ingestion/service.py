from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from kairos.connectors.base import Connector
from kairos.connectors.types import CanonicalRecord, JSONValue, Window


class RawPayloadRepository(Protocol):
    async def upsert(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        window: Window,
        payload: JSONValue,
        content_hash: bytes,
    ) -> int:
        ...


class CanonicalRepository(Protocol):
    async def upsert_many(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        records: list[CanonicalRecord],
        raw_payload_id: int,
    ) -> int:
        ...


class SyncStateRepository(Protocol):
    async def mark_success(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        synced_through: datetime,
    ) -> None:
        ...

    async def get_backfill_state(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
    ) -> tuple[datetime | None, datetime | None]:
        ...

    async def set_backfill_cursor(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        cursor: datetime,
    ) -> None:
        ...

    async def mark_backfill_complete(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        complete_to: datetime,
    ) -> None:
        ...


class SyncFailureRepository(Protocol):
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
        details: JSONValue,
    ) -> None:
        ...


HashPayload = Callable[[JSONValue], bytes]


@dataclass(frozen=True)
class SyncRunResult:
    raw_payload_id: int
    records_written: int


@dataclass(frozen=True)
class BackfillResult:
    windows_processed: int
    completed: bool
    next_cursor: datetime | None


class SyncService:
    def __init__(
        self,
        *,
        raw_repo: RawPayloadRepository,
        canonical_repo: CanonicalRepository,
        sync_state_repo: SyncStateRepository,
        hash_payload: HashPayload,
        sync_failure_repo: SyncFailureRepository | None = None,
    ) -> None:
        self._raw_repo = raw_repo
        self._canonical_repo = canonical_repo
        self._sync_state_repo = sync_state_repo
        self._hash_payload = hash_payload
        self._sync_failure_repo = sync_failure_repo

    async def run_backfill(
        self,
        *,
        connector: Connector,
        user_id: UUID,
        kind: str,
        from_date: datetime,
        to_date: datetime,
        step: timedelta = timedelta(days=1),
        throttle: Callable[[], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> BackfillResult:
        if from_date >= to_date:
            return BackfillResult(windows_processed=0, completed=True, next_cursor=None)

        cursor, complete_to = await self._sync_state_repo.get_backfill_state(
            user_id=user_id,
            connector_id=connector.connector_id,
            kind=kind,
        )
        if complete_to is not None and complete_to >= to_date:
            return BackfillResult(windows_processed=0, completed=True, next_cursor=None)

        if cursor is None:
            cursor = to_date

        windows_processed = 0
        while cursor > from_date:
            window_start = max(from_date, cursor - step)
            window = Window(start=window_start, end=cursor)

            if throttle is not None:
                throttle()

            await self.run_window(
                connector=connector,
                user_id=user_id,
                kind=kind,
                window=window,
            )

            cursor = window_start
            windows_processed += 1

            await self._sync_state_repo.set_backfill_cursor(
                user_id=user_id,
                connector_id=connector.connector_id,
                kind=kind,
                cursor=cursor,
            )

            if should_stop is not None and should_stop():
                return BackfillResult(
                    windows_processed=windows_processed,
                    completed=False,
                    next_cursor=cursor,
                )

        await self._sync_state_repo.mark_backfill_complete(
            user_id=user_id,
            connector_id=connector.connector_id,
            kind=kind,
            complete_to=to_date,
        )
        return BackfillResult(windows_processed=windows_processed, completed=True, next_cursor=None)

    async def run_window(
        self,
        *,
        connector: Connector,
        user_id: UUID,
        kind: str,
        window: Window,
    ) -> SyncRunResult:
        try:
            envelope = connector.fetch(user_id=user_id, kind=kind, window=window)
            content_hash = self._hash_payload(envelope.payload)

            raw_payload_id = await self._raw_repo.upsert(
                user_id=user_id,
                connector_id=connector.connector_id,
                kind=kind,
                window=envelope.window,
                payload=envelope.payload,
                content_hash=content_hash,
            )

            records = connector.normalize(envelope.payload)
            records_written = await self._canonical_repo.upsert_many(
                user_id=user_id,
                connector_id=connector.connector_id,
                kind=kind,
                records=records,
                raw_payload_id=raw_payload_id,
            )

            await self._sync_state_repo.mark_success(
                user_id=user_id,
                connector_id=connector.connector_id,
                kind=kind,
                synced_through=envelope.window.end,
            )

            return SyncRunResult(raw_payload_id=raw_payload_id, records_written=records_written)
        except Exception as exc:
            retryable = self._is_retryable(exc)
            if self._sync_failure_repo is not None:
                await self._sync_failure_repo.record_failure(
                    user_id=user_id,
                    connector_id=connector.connector_id,
                    kind=kind,
                    window=window,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    retryable=retryable,
                    details={"stage": "run_window"},
                )
            raise

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        non_retryable = (ValueError, PermissionError)
        return not isinstance(exc, non_retryable)
