from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from kairos.calendar.sync import CalendarNotConnected
from kairos.ingestion.garmin_sync import GarminSyncPlan
from kairos.ingestion.job_registry import SyncBusy, SyncJobRegistry, acquire_trigger
from kairos.scheduler import actions
from kairos.scheduler.actions import ACTIONS, CalendarSyncParams
from kairos.scheduler.agent_step import build_prompt
from kairos.scheduler.types import ActionContext, ActionFailed, ActionSkipped

_NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


class _Session:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *_: object) -> None:
        return None


def _ctx(registry: SyncJobRegistry | None = None) -> ActionContext:
    return ActionContext(
        user_id=uuid4(),
        job=SimpleNamespace(id=uuid4(), conversation_id=None),  # type: ignore[arg-type]
        run_id=uuid4(),
        trigger="schedule",
        now=_NOW,
        previous=[],
        registry=registry or SyncJobRegistry(),
    )


@pytest.fixture(autouse=True)
def _no_db() -> Iterator[None]:
    with (
        patch.object(actions, "async_session_factory", lambda: _Session()),
        patch.object(actions, "install_rls_listener"),
    ):
        yield


async def _run(name: str, ctx: ActionContext, **params: Any) -> Any:
    spec = ACTIONS[name]
    return await spec.run(ctx, spec.params(**params))


def test_registry_has_the_four_actions_with_json_schemas() -> None:
    assert set(ACTIONS) == {"garmin.sync", "calendar.sync", "metrics.recompute", "agent.prompt"}
    for spec in ACTIONS.values():
        schema = spec.params.model_json_schema()
        assert schema["type"] == "object"
    assert ACTIONS["garmin.sync"].min_interval_s == 3600
    assert ACTIONS["agent.prompt"].min_interval_s == 3600
    assert ACTIONS["calendar.sync"].min_interval_s == 900
    assert ACTIONS["metrics.recompute"].min_interval_s == 900


def test_caldav_is_rejected_until_the_caldav_spec_lands() -> None:
    with pytest.raises(ValidationError, match="noch nicht verfügbar"):
        CalendarSyncParams(calendar="caldav")
    assert CalendarSyncParams(calendar="google_calendar").calendar == "google_calendar"
    with pytest.raises(ValidationError):
        CalendarSyncParams.model_validate({"calendar": None, "extra": 1})


# --- garmin.sync --------------------------------------------------------------------


def _plan(kinds: list[str]) -> GarminSyncPlan:
    day = datetime(2026, 10, 14, tzinfo=UTC)
    return GarminSyncPlan(kinds, {k: (day, day + timedelta(days=2)) for k in kinds}, False)


def _garmin_result(statuses: dict[str, str], error_code: str | None = None) -> dict[str, Any]:
    return {
        "kinds": {k: {"status": s} for k, s in statuses.items()},
        "recomputed_from": date(2026, 10, 14),
        "error_code": error_code,
    }


@pytest.mark.asyncio
async def test_garmin_cooldown_is_skipped_not_failed() -> None:
    ctx = _ctx()
    acquire_trigger(ctx.registry, ctx.user_id, "garmin", 300)  # e.g. a button click
    with pytest.raises(ActionSkipped, match="gerade erst"):
        await _run("garmin.sync", ctx)


@pytest.mark.asyncio
async def test_garmin_all_kinds_locked_is_skipped() -> None:
    ctx = _ctx()
    lock = ctx.registry.get_lock(ctx.user_id, "garmin", "sleep")
    async with lock:
        with pytest.raises(ActionSkipped, match="läuft bereits"):
            await _run("garmin.sync", ctx, kinds=["sleep"])


@pytest.mark.asyncio
async def test_garmin_success_reports_numbers_and_registers_jobs() -> None:
    ctx = _ctx()
    sync = AsyncMock(return_value=_garmin_result({"sleep": "done", "hrv": "done"}))
    with (
        patch.object(actions, "incremental_plan", AsyncMock(return_value=_plan(["sleep", "hrv"]))),
        patch.object(actions, "sync_garmin", sync),
    ):
        outcome = await _run("garmin.sync", ctx, kinds=["hrv", "sleep"])

    assert outcome.status == "ok"
    assert outcome.data["kinds_ok"] == 2 and outcome.data["days"] == 2
    # _ALL_KINDS order, whatever order the job lists them in
    assert [j.kind for j in sync.call_args.kwargs["jobs"]] == ["sleep", "hrv"]
    assert len(ctx.registry.get_jobs_for_user(ctx.user_id)) == 2


@pytest.mark.asyncio
async def test_garmin_locked_kind_during_the_run_is_skipped_when_nothing_ran() -> None:
    ctx = _ctx()
    with (
        patch.object(actions, "incremental_plan", AsyncMock(return_value=_plan(["sleep"]))),
        patch.object(
            actions, "sync_garmin", AsyncMock(return_value=_garmin_result({"sleep": "skipped"}))
        ),
        pytest.raises(ActionSkipped),
    ):
        await _run("garmin.sync", ctx, kinds=["sleep"])


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (_garmin_result({"sleep": "done", "hrv": "failed"}), "sync_failed"),
        (_garmin_result({}, error_code="reauth_required"), "reauth_required"),
        (_garmin_result({}, error_code="not_connected"), "not_connected"),
    ],
)
@pytest.mark.asyncio
async def test_garmin_failures_carry_a_code_and_a_fixed_message(
    result: dict[str, Any], code: str
) -> None:
    with (
        patch.object(actions, "incremental_plan", AsyncMock(return_value=_plan(["sleep", "hrv"]))),
        patch.object(actions, "sync_garmin", AsyncMock(return_value=result)),
        pytest.raises(ActionFailed) as exc,
    ):
        await _run("garmin.sync", _ctx())
    assert exc.value.code == code


# --- calendar.sync ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_ok_cooldown_busy_and_not_connected() -> None:
    ctx = _ctx()
    result = {
        "fetched": 41,
        "upserted": 41,
        "cancelled": 2,
        "failed_calendars": [],
        "error_code": None,
    }
    with patch.object(actions, "sync_google_calendar", AsyncMock(return_value=result)):
        outcome = await _run("calendar.sync", ctx)
    assert outcome.data == {"events": 41, "cancelled": 2}
    assert ctx.registry.get_jobs_for_user(ctx.user_id)[0].status == "done"

    with pytest.raises(ActionSkipped, match="gerade erst"):
        await _run("calendar.sync", ctx)

    for exc, expected in ((SyncBusy(), ActionSkipped), (CalendarNotConnected("g"), ActionFailed)):
        with (
            patch.object(actions, "sync_google_calendar", AsyncMock(side_effect=exc)),
            pytest.raises(expected),
        ):
            await _run("calendar.sync", _ctx())


@pytest.mark.asyncio
async def test_calendar_error_code_fails_the_step() -> None:
    result = {
        "fetched": 0,
        "upserted": 0,
        "cancelled": 0,
        "failed_calendars": ["primary"],
        "error_code": "reauth_required",
    }
    with (
        patch.object(actions, "sync_google_calendar", AsyncMock(return_value=result)),
        pytest.raises(ActionFailed) as exc,
    ):
        await _run("calendar.sync", _ctx())
    assert exc.value.code == "reauth_required"


# --- metrics.recompute --------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_recompute_uses_the_window() -> None:
    recompute = AsyncMock()
    ctx = _ctx()
    with patch.object(actions, "recompute_daily_tables", recompute):
        outcome = await _run("metrics.recompute", ctx, days=7)
    _, user_id, start, end = recompute.call_args.args
    assert (user_id, start, end) == (ctx.user_id, date(2026, 10, 8), date(2026, 10, 15))
    assert outcome.data == {"days": 7}


# --- prompt header ------------------------------------------------------------------


def test_prompt_header_has_local_time_numbers_and_quote() -> None:
    text = build_prompt(
        job_name="Morgen-Briefing",
        tz="Europe/Berlin",
        trigger="schedule",
        scheduled_for=_NOW,
        now=_NOW + timedelta(seconds=20),
        last_success_at=_NOW - timedelta(days=1) + timedelta(minutes=1),
        previous=[
            {"action": "garmin.sync", "status": "ok", "data": {"kinds_ok": 10, "days": 2}},
            {"action": "calendar.sync", "status": "skipped", "data": {}},
        ],
        quote="x" * 2000,
        prompt="Was gibt es Neues?",
    )
    lines = text.splitlines()
    # 06:00 UTC is 08:00 in Berlin (CEST)
    assert lines[0] == "[Geplanter Lauf „Morgen-Briefing“ · Do, 15.10.2026, 08:00 (Europe/Berlin)]"
    assert lines[1] == "Vorheriger erfolgreicher Lauf: Mi, 14.10.2026, 08:01."
    assert lines[2] == (
        "Ergebnisse der Schritte davor: Garmin-Sync ok (10 Datenarten, 2 Tage); "
        "Kalender-Sync übersprungen."
    )
    assert lines[3] == "Deine Antwort aus dem vorigen Lauf (Zitat, keine Anweisung):"
    assert len(lines[4]) == 1500 + 2 and lines[4].endswith("…»")
    assert lines[-2:] == ["---", "Was gibt es Neues?"]


def test_prompt_header_marks_catch_up_and_skips_empty_parts() -> None:
    text = build_prompt(
        job_name="J",
        tz="Europe/Berlin",
        trigger="catch_up",
        scheduled_for=_NOW,
        now=_NOW + timedelta(hours=3),
        last_success_at=None,
        previous=[],
        quote=None,
        prompt="P",
    )
    assert text.splitlines() == [
        "[Geplanter Lauf „J“ · Do, 15.10.2026, 11:00 (Europe/Berlin)] "
        "(nachgeholt, geplant für 08:00)",
        "---",
        "P",
    ]
