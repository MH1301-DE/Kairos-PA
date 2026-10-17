"""Action registry: fixed actions with a Pydantic parameter schema and an HTTP-free run.

Every run opens its own session and installs the RLS listener for the job's user before
calling a service function (CalDAV spec 7, scheduler spec 5).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kairos.calendar.sync import (
    GOOGLE_CALENDAR_COOLDOWN_SECONDS,
    CalendarNotConnected,
    default_window,
    sync_google_calendar,
)
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.garmin_sync import (
    ALL_KINDS,
    GARMIN_COOLDOWN_SECONDS,
    incremental_plan,
    sync_garmin,
)
from kairos.ingestion.job_registry import SyncBusy, SyncCooldown, acquire_trigger
from kairos.repositories.metrics_recompute import recompute_daily_tables
from kairos.repositories.sync_state import SqlSyncStateRepository
from kairos.scheduler.agent_step import run_agent_step
from kairos.scheduler.types import (
    ActionContext,
    ActionFailed,
    ActionSkipped,
    StepOutcome,
)

logger = logging.getLogger(__name__)

GarminKind = Literal[
    "hr_intraday",
    "sleep",
    "stress",
    "body_battery",
    "hrv",
    "respiration",
    "spo2",
    "daily_summary",
    "activity_list",
    "activity_fit",
]


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    description: str
    params: type[BaseModel]
    timeout_s: float
    min_interval_s: int
    run: Callable[[ActionContext, Any], Awaitable[StepOutcome]] = field(repr=False)


# --- parameter schemas --------------------------------------------------------------


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GarminSyncParams(_Params):
    kinds: list[GarminKind] | None = Field(
        None, title="Datenarten", description="leer = alle Datenarten"
    )


class CalendarSyncParams(_Params):
    calendar: Literal["google_calendar", "caldav"] | None = Field(
        None, title="Kalender", description="leer = Standardkalender"
    )

    @field_validator("calendar")
    @classmethod
    def _caldav_not_yet(cls, value: str | None) -> str | None:
        # the scheduler lands before CalDAV (spec 5.3); sync_calendar replaces this
        if value == "caldav":
            raise ValueError("Apple Kalender (CalDAV) ist noch nicht verfügbar")
        return value


class MetricsRecomputeParams(_Params):
    days: int = Field(60, ge=1, le=730, title="Tage")


class AgentPromptParams(_Params):
    prompt: str = Field(min_length=1, max_length=2000, title="Frage an den Agenten")


# --- actions ------------------------------------------------------------------------


async def _garmin_sync(ctx: ActionContext, params: GarminSyncParams) -> StepOutcome:
    wanted = set(params.kinds or ALL_KINDS)
    kinds = [k for k in ALL_KINDS if k in wanted]
    try:
        acquire_trigger(ctx.registry, ctx.user_id, "garmin", GARMIN_COOLDOWN_SECONDS)
    except SyncCooldown:
        raise ActionSkipped("Garmin wurde gerade erst synchronisiert") from None
    queued = [k for k in kinds if not ctx.registry.is_locked(ctx.user_id, "garmin", k)]
    if not queued:
        raise ActionSkipped("Garmin-Sync läuft bereits")

    async with async_session_factory() as session:
        install_rls_listener(session, ctx.user_id)
        plan = await incremental_plan(
            SqlSyncStateRepository(session=session), ctx.user_id, queued, ctx.now
        )
        start = min(r[0] for r in plan.ranges.values())
        end = max(r[1] for r in plan.ranges.values())
        # same registry entries as the button, so scheduler syncs show up on /sync
        jobs = ctx.registry.create_jobs(
            user_id=ctx.user_id,
            connector="garmin",
            kinds=queued,
            from_date=start.date().isoformat(),
            to_date=end.date().isoformat(),
        )
        result = await sync_garmin(session, ctx.user_id, plan, registry=ctx.registry, jobs=jobs)

    if result["error_code"] == "reauth_required":
        raise ActionFailed("reauth_required", "Garmin-Sitzung abgelaufen, bitte neu verbinden")
    if result["error_code"] is not None:
        raise ActionFailed("not_connected", "Keine aktive Garmin-Verbindung")
    statuses = [k["status"] for k in result["kinds"].values()]
    data: dict[str, Any] = {
        "kinds_ok": statuses.count("done"),
        "kinds_skipped": statuses.count("skipped") + len(kinds) - len(queued),
        "kinds_failed": statuses.count("failed"),
        "days": (end - start).days,
        "recomputed_from": (
            result["recomputed_from"].isoformat() if result["recomputed_from"] else None
        ),
    }
    if data["kinds_failed"]:
        raise ActionFailed(
            "sync_failed", f"Garmin-Sync: {data['kinds_failed']} Datenart(en) fehlgeschlagen"
        )
    if not data["kinds_ok"]:
        raise ActionSkipped("Garmin-Sync läuft bereits", data)
    return StepOutcome(
        summary=f"{data['kinds_ok']} Datenarten, {data['days']} Tage synchronisiert", data=data
    )


async def _calendar_sync(ctx: ActionContext, params: CalendarSyncParams) -> StepOutcome:
    # until CalDAV spec AP 3 only Google exists, so the default calendar is Google
    del params
    try:
        acquire_trigger(
            ctx.registry, ctx.user_id, "google_calendar", GOOGLE_CALENDAR_COOLDOWN_SECONDS
        )
    except SyncCooldown:
        raise ActionSkipped("Kalender wurde gerade erst synchronisiert") from None
    window = default_window(ctx.now.date())
    (job,) = ctx.registry.create_jobs(
        user_id=ctx.user_id,
        connector="google_calendar",
        kinds=["events"],
        from_date=window.start.date().isoformat(),
        to_date=window.end.date().isoformat(),
    )
    job.status = "running"
    try:
        async with async_session_factory() as session:
            install_rls_listener(session, ctx.user_id)
            result = await sync_google_calendar(session, ctx.user_id, window)
    except SyncBusy:
        _finish(job, "skipped", "Already running in another request")
        raise ActionSkipped("Kalender-Sync läuft bereits") from None
    except CalendarNotConnected:
        _finish(job, "failed", "No active Google Calendar connection or decryption failed")
        raise ActionFailed("not_connected", "Kein Kalender verbunden") from None
    if result["error_code"] is not None:
        _finish(job, "failed", "Kalender-Sync fehlgeschlagen")
        message = (
            "Kalenderzugriff abgelaufen, bitte neu anmelden"
            if result["error_code"] == "reauth_required"
            else "Kalender nicht erreichbar"
        )
        raise ActionFailed(result["error_code"], message)
    job.windows_processed = result["upserted"]
    _finish(job, "done", None)
    return StepOutcome(
        summary=f"{result['fetched']} Termine abgeglichen",
        data={"events": result["fetched"], "cancelled": result["cancelled"]},
    )


def _finish(job: Any, status: str, error: str | None) -> None:
    job.status = status
    job.error = error
    job.finished_at = datetime.now(UTC).isoformat()


async def _metrics_recompute(ctx: ActionContext, params: MetricsRecomputeParams) -> StepOutcome:
    end: date = ctx.now.date()
    start = end - timedelta(days=params.days)
    async with async_session_factory() as session:
        install_rls_listener(session, ctx.user_id)
        await recompute_daily_tables(session, ctx.user_id, start, end)
    return StepOutcome(
        summary=f"Kennzahlen für {params.days} Tage neu berechnet", data={"days": params.days}
    )


async def _agent_prompt(ctx: ActionContext, params: AgentPromptParams) -> StepOutcome:
    return await run_agent_step(ctx, params.prompt)


ACTIONS: dict[str, ActionSpec] = {
    spec.name: spec
    for spec in (
        ActionSpec(
            name="garmin.sync",
            label="Garmin synchronisieren",
            description="Holt neue Garmin-Daten seit dem letzten Sync, inklusive heute.",
            params=GarminSyncParams,
            # the first run after a long pause may fetch many day windows (spec 6.2)
            timeout_s=3600,
            min_interval_s=3600,
            run=_garmin_sync,
        ),
        ActionSpec(
            name="calendar.sync",
            label="Kalender synchronisieren",
            description="Gleicht die Termine der nächsten Wochen mit dem Kalender ab.",
            params=CalendarSyncParams,
            timeout_s=120,
            min_interval_s=900,
            run=_calendar_sync,
        ),
        ActionSpec(
            name="metrics.recompute",
            label="Kennzahlen neu berechnen",
            description="Berechnet die Tageswerte des Dashboards für einen Zeitraum neu.",
            params=MetricsRecomputeParams,
            timeout_s=300,
            min_interval_s=900,
            run=_metrics_recompute,
        ),
        ActionSpec(
            name="agent.prompt",
            label="Agent fragen",
            description="Stellt dem Agenten eine feste Frage; die Antwort landet im Job-Chat.",
            params=AgentPromptParams,
            timeout_s=300,
            min_interval_s=3600,
            run=_agent_prompt,
        ),
    )
}
