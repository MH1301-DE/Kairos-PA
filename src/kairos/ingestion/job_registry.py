"""In-memory job registry and per-(user, connector, kind) async locks."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


@dataclass
class SyncJob:
    job_id: str
    user_id: UUID
    connector: str
    kind: str
    from_date: str
    to_date: str
    status: str = "queued"
    windows_processed: int = 0
    # total windows this job will process, so the UI can show a percentage.
    # None for job kinds that don't process date-range windows one at a time
    # (e.g. google_calendar's single-fetch "events" sync) -- there is no
    # meaningful total to show for those.
    windows_total: int | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "connector": self.connector,
            "kind": self.kind,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "status": self.status,
            "windows_processed": self.windows_processed,
            "windows_total": self.windows_total,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class SyncJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, SyncJob] = {}
        # prevents duplicate concurrent runs for the same (user, connector, kind)
        self._locks: dict[tuple[UUID, str, str], asyncio.Lock] = {}
        # trigger cooldown per (user, connector) -- repeated Garmin login attempts
        # from rapid re-triggering caused a real Cloudflare account lockout once,
        # so this is checked before any connector client is built, not just before
        # the actual sync work runs
        self._last_triggered_monotonic: dict[tuple[UUID, str], float] = {}

    def create_jobs(
        self,
        *,
        user_id: UUID,
        connector: str,
        kinds: list[str],
        from_date: str,
        to_date: str,
        windows_total: int | None = None,
    ) -> list[SyncJob]:
        jobs = []
        for kind in kinds:
            job = SyncJob(
                job_id=str(uuid.uuid4()),
                user_id=user_id,
                connector=connector,
                kind=kind,
                from_date=from_date,
                to_date=to_date,
                windows_total=windows_total,
            )
            self._jobs[job.job_id] = job
            jobs.append(job)
        return jobs

    def get_jobs_for_user(self, user_id: UUID) -> list[SyncJob]:
        return [j for j in self._jobs.values() if j.user_id == user_id]

    def get_lock(self, user_id: UUID, connector: str, kind: str) -> asyncio.Lock:
        key = (user_id, connector, kind)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def is_locked(self, user_id: UUID, connector: str, kind: str) -> bool:
        lock = self._locks.get((user_id, connector, kind))
        return lock is not None and lock.locked()

    def seconds_until_trigger_allowed(
        self, user_id: UUID, connector: str, cooldown_seconds: float
    ) -> float:
        """0.0 if a new trigger is allowed now, else the remaining cooldown in seconds."""
        last = self._last_triggered_monotonic.get((user_id, connector))
        if last is None:
            return 0.0
        remaining = cooldown_seconds - (time.monotonic() - last)
        return max(0.0, remaining)

    def record_trigger(self, user_id: UUID, connector: str) -> None:
        self._last_triggered_monotonic[(user_id, connector)] = time.monotonic()


_registry = SyncJobRegistry()


def get_registry() -> SyncJobRegistry:
    return _registry
