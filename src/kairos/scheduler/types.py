from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from kairos.db.models import ScheduledJob
from kairos.ingestion.job_registry import SyncJobRegistry


class StepRecord(TypedDict, total=False):
    action: str
    params: dict[str, Any]
    status: str  # ok | skipped | failed | not_run | running
    started_at: str | None
    finished_at: str | None
    summary: str | None
    data: dict[str, Any]
    error_code: str | None


class StepOutcome(BaseModel):
    status: Literal["ok", "skipped"] = "ok"
    # fixed German message, never upstream text
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class ActionSkipped(Exception):
    """Cooldown, lock, daily limit, active conversation -- not an error."""

    def __init__(self, summary: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(summary)
        self.summary = summary
        self.data = data or {}


class ActionFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ActionContext:
    user_id: UUID
    job: ScheduledJob
    run_id: UUID
    trigger: str
    # injectable clock (tests)
    now: datetime
    previous: list[StepRecord]
    registry: SyncJobRegistry


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    description: str
    params: type[BaseModel]
    timeout_s: float
    min_interval_s: int
    run: Callable[[ActionContext, Any], Awaitable[StepOutcome]] = field(repr=False)


STEP_LABELS = {
    "garmin.sync": "Garmin-Sync",
    "calendar.sync": "Kalender-Sync",
    "metrics.recompute": "Kennzahlen",
    "agent.prompt": "Agent",
}
