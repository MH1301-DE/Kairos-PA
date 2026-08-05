"""In-memory job registry and per-(user, connector, kind) async locks."""

from __future__ import annotations

import asyncio
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
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class SyncJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, SyncJob] = {}
        # prevents duplicate concurrent runs for the same (user, connector, kind)
        self._locks: dict[tuple[UUID, str, str], asyncio.Lock] = {}

    def create_jobs(
        self,
        *,
        user_id: UUID,
        connector: str,
        kinds: list[str],
        from_date: str,
        to_date: str,
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


_registry = SyncJobRegistry()


def get_registry() -> SyncJobRegistry:
    return _registry
