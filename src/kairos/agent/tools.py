from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.activity_tools import (
    ANALYZE_OPERATIONS,
    CURVE_METRICS,
    SEARCH_SORTS,
    SPLIT_KINDS,
    SPORT_PROFILES,
    activity_analyze_handler,
    activity_get_handler,
    activity_search_handler,
    activity_splits_handler,
)
from kairos.agent.expiry import _parse_expiry
from kairos.agent.format import cap_envelope, drop_last_row
from kairos.agent.render_schemas import RENDER_COMPONENTS, validate_render_config
from kairos.calendar.free_time import BusyBlock, CalendarPrefs, FreeBlock, compute_free_blocks
from kairos.db.models import MetricDailyValue
from kairos.metrics.bootstrap import build_default_registry
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series
from kairos.planning.algorithm import generate_plan_blocks
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.memory import SqlMemoryRepository
from kairos.repositories.plan import PlanRepository
from kairos.routers.calendar import (
    CreateEventRequest,
    _create_calendar_event,
    _delete_calendar_event,
    _load_prefs,
)

_WORKOUT_LABELS: dict[str, str] = {
    "long_run": "Long Run", "hard": "Intervalle/Tempo", "easy": "Lockerer Lauf", "rest": "Ruhetag",
}
_STRESS_KEYWORDS = ("stress", "krank", "müde", "muede", "erkält", "erkaeltet")

# Hardcap per docs/03-agent-design.md §4.5 -- a tool result never dumps a raw
# time series beyond this, the caller re-queries with a narrower window instead
_MAX_ANALYZE_DAYS_RETURNED = 60

_RENDER_COMPONENTS = RENDER_COMPONENTS


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_class: Literal["read", "write", "destructive"]
    requires_confirmation: bool
    json_schema: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]


def _envelope(
    summary: str,
    data: Any,
    *,
    coverage: str | None = None,
    truncated: bool = False,
    next_hint: str | None = None,
    quality: str | None = None,
    max_tokens: int | None = None,
    shrink: Callable[[dict[str, Any]], dict[str, Any] | None] = drop_last_row,
) -> dict[str, Any]:
    if isinstance(data, list):
        row_count: int | None = len(data)
    elif isinstance(data, dict) and isinstance(data.get("rows"), list):
        row_count = len(data["rows"])
    else:
        row_count = None
    meta: dict[str, Any] = {
        "row_count": row_count,
        "truncated": truncated,
        "coverage": coverage,
        "as_of": datetime.now(UTC).isoformat(),
    }
    if quality is not None:
        meta["quality"] = quality
    if next_hint is not None:
        meta["next"] = next_hint
    env = {"summary": summary, "data": data, "meta": meta}
    if max_tokens is not None:
        env = cap_envelope(env, max_tokens=max_tokens, shrink=shrink)
    return env


async def query_health_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    metric_id: str,
    variant: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    registry = build_default_registry()
    variants = registry.variants_for(metric_id)
    if not variants:
        raise ValueError(f"Unknown metric_id: {metric_id!r}")
    chosen = variant or registry.default_variant(metric_id)
    if chosen not in variants:
        raise ValueError(f"Unknown variant {chosen!r} for metric {metric_id!r}")

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    result = await registry.get(metric_id, chosen).compute(
        session, user_id=user_id, as_of=as_of_date
    )
    return _envelope(
        f"{metric_id} ({chosen}) am {as_of_date.isoformat()}: {result.value} {result.unit} "
        f"[{result.confidence}]",
        {
            "metric_id": metric_id, "variant": chosen, "value": result.value,
            "unit": result.unit, "confidence": result.confidence, "note": result.note,
        },
        coverage=f"{result.coverage_days}/{result.coverage_required_days} Tage",
    )


async def analyze_records_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    metric_id: str,
    variant: str | None = None,
    window_days: int = 28,
) -> dict[str, Any]:
    registry = build_default_registry()
    variants = registry.variants_for(metric_id)
    if not variants:
        raise ValueError(f"Unknown metric_id: {metric_id!r}")
    chosen = variant or registry.default_variant(metric_id)
    window_days = min(window_days, _MAX_ANALYZE_DAYS_RETURNED)

    end = date.today()
    start = end - timedelta(days=window_days - 1)
    rows = (
        await session.execute(
            select(MetricDailyValue.day, MetricDailyValue.value)
            .where(
                MetricDailyValue.user_id == user_id,
                MetricDailyValue.metric_id == metric_id,
                MetricDailyValue.variant_id == chosen,
                MetricDailyValue.day >= start,
                MetricDailyValue.day <= end,
            )
            .order_by(MetricDailyValue.day)
        )
    ).all()
    values = [r.value for r in rows if r.value is not None]
    if not values:
        return _envelope(
            f"Keine Zeitreihe für {metric_id} ({chosen}) in den letzten {window_days} Tagen.",
            {"mean": None, "min": None, "max": None, "trend_slope": None},
            coverage=f"0/{window_days} Tage",
        )

    mean_val = sum(values) / len(values)
    min_val = min(values)
    max_val = max(values)
    trend_slope = _linear_trend_slope(values)
    return _envelope(
        f"{metric_id} ({chosen}), {window_days} Tage: ⌀ {mean_val:.1f}, "
        f"min {min_val:.1f}, max {max_val:.1f}, Trend {trend_slope:+.2f}/Tag",
        {"mean": mean_val, "min": min_val, "max": max_val, "trend_slope": trend_slope},
        coverage=f"{len(values)}/{window_days} Tage",
    )


def _linear_trend_slope(values: list[float]) -> float:
    # simple least-squares slope over the index (0..n-1) -- good enough for a
    # "is this trending up or down" signal, not a forecasting model
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    numerator = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


async def query_calendar_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    from_date: str,
    to_date: str,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    from_dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
    to_dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, from_dt, to_dt)
    events_data = [
        {"id": str(e.id), "summary": e.summary, "start_at": e.start_at.isoformat(),
         "end_at": e.end_at.isoformat()}
        for e in events
    ]

    if duration_minutes is None:
        return _envelope(f"{len(events)} Termine zwischen {from_date} und {to_date}.", events_data)

    prefs_row = await _load_prefs(session, user_id)
    busy = [BusyBlock(start=e.start_at, end=e.end_at) for e in events]
    prefs = CalendarPrefs(
        work_hours_start=prefs_row["work_hours_start"],
        work_hours_end=prefs_row["work_hours_end"],
        buffer_minutes=prefs_row["calendar_buffer_minutes"],
        min_free_minutes=duration_minutes,
    )
    blocks = compute_free_blocks(busy, from_dt, to_dt, prefs)
    slots = [{"start": b.start.isoformat(), "end": b.end.isoformat()} for b in blocks]
    return _envelope(
        f"{len(events)} Termine, {len(slots)} freie Blöcke ≥ {duration_minutes} min.",
        {"events": events_data, "free_blocks": slots},
    )


async def recall_handler(
    session: AsyncSession, *, user_id: UUID, query: str | None = None, limit: int = 10
) -> dict[str, Any]:
    repo = SqlMemoryRepository(session=session)
    entries = await repo.list_active(user_id=user_id, now=datetime.now(UTC))
    if query:
        entries = [e for e in entries if query.lower() in e.content.lower()]
    entries = entries[:limit]
    data = [{"id": str(e.id), "content": e.content, "source": e.source} for e in entries]
    return _envelope(f"{len(data)} Gedächtnis-Einträge gefunden.", data)


async def remember_handler(
    session: AsyncSession, *, user_id: UUID, content: str, expires_at: str | None = None
) -> dict[str, Any]:
    # write-class but executes immediately, no Proposal -- design spec
    # Scope-Entscheidung 4: visible undo chip in the frontend instead of a
    # pre-confirmation, dispatcher.py special-cases this tool by name
    repo = SqlMemoryRepository(session=session)
    expiry = _parse_expiry(expires_at) if expires_at else None
    entry = await repo.create(user_id=user_id, content=content, source="agent", expires_at=expiry)
    return _envelope(
        f"Gemerkt: {content}",
        {
            "id": str(entry.id),
            "content": entry.content,
            "source": "agent",
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        },
    )


async def render_handler(
    session: AsyncSession, *, user_id: UUID, component: str, config: dict[str, Any]
) -> dict[str, Any]:
    del session, user_id  # no data fetching of its own -- data comes from a prior tool call
    normalized = validate_render_config(component, config)
    return _envelope(f"{component}-Chart erzeugt.", {"component": component, "config": normalized})


async def propose_calendar_event_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    summary: str,
    start_at: str,
    end_at: str,
    description: str | None = None,
) -> dict[str, Any]:
    req = CreateEventRequest(
        summary=summary,
        start_at=datetime.fromisoformat(start_at),
        end_at=datetime.fromisoformat(end_at),
        description=description,
    )
    created = await _create_calendar_event(session, user_id, req)
    return _envelope(f"Termin \"{summary}\" angelegt.", created)


async def delete_calendar_event_handler(
    session: AsyncSession, *, user_id: UUID, event_id: str, confirm: bool = False
) -> dict[str, Any]:
    await _delete_calendar_event(session, user_id, UUID(event_id), confirm)
    return _envelope(f"Termin {event_id} gelöscht.", {"event_id": event_id})


async def _free_blocks_by_day(
    session: AsyncSession, user_id: UUID, start: date, end: date
) -> dict[date, list[FreeBlock]]:
    """One compute_free_blocks() call per day, sharing a single events fetch
    for the whole range instead of one query per day."""
    prefs_row = await _load_prefs(session, user_id)
    prefs = CalendarPrefs(
        work_hours_start=prefs_row["work_hours_start"],
        work_hours_end=prefs_row["work_hours_end"],
        buffer_minutes=prefs_row["calendar_buffer_minutes"],
        min_free_minutes=0,  # the planning algorithm applies its own thresholds
    )
    range_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
    range_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, range_start, range_end)

    result: dict[date, list[FreeBlock]] = {}
    day = start
    while day <= end:
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        busy = [
            BusyBlock(start=e.start_at, end=e.end_at)
            for e in events
            if e.start_at < day_end and e.end_at > day_start
        ]
        result[day] = compute_free_blocks(busy, day_start, day_end, prefs)
        day += timedelta(days=1)
    return result


async def _current_ctl(session: AsyncSession, user_id: UUID, as_of: date) -> float:
    registry = build_default_registry()
    result = await registry.get("training_load", "default").compute(
        session, user_id=user_id, as_of=as_of
    )
    if result.confidence != "insufficient_data" and isinstance(result.value, dict):
        ctl = result.value.get("ctl")
        if isinstance(ctl, int | float):
            return float(ctl)
    # a brand-new user with no training history yet still gets a (conservative,
    # all-easy-leaning) plan rather than a hard failure
    return 0.0


async def plan_propose_handler(
    session: AsyncSession, *, user_id: UUID, weeks: int, goal_date: str | None = None
) -> dict[str, Any]:
    start = date.today()
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    goal = date.fromisoformat(goal_date) if goal_date else None

    free_blocks = await _free_blocks_by_day(session, user_id, start, end)
    current_ctl = await _current_ctl(session, user_id, start)
    planned = generate_plan_blocks(
        start=start, end=end, goal_date=goal, free_blocks_by_day=free_blocks,
        current_ctl=current_ctl,
    )

    repo = PlanRepository(session=session)
    plan = await repo.create_draft(
        user_id=user_id, title=f"Trainingsplan ab {start.isoformat()}", start_date=start,
        end_date=end, goal_date=goal, blocks=planned,
    )

    lines = [
        f"{b.day.isoformat()}: {_WORKOUT_LABELS[b.workout_type]}"
        + (f" (TRIMP ~{b.target_trimp:.0f})" if b.target_trimp else "")
        for b in planned
    ]
    return _envelope(
        f"Entwurf für {weeks} Wochen erstellt ({len(planned)} Tage). Noch nicht im Kalender --"
        " zum Bestätigen plan_commit aufrufen.",
        {"plan_id": str(plan.id), "blocks": lines},
    )


async def plan_commit_handler(
    session: AsyncSession, *, user_id: UUID, plan_id: str
) -> dict[str, Any]:
    plan_uuid = UUID(plan_id)
    repo = PlanRepository(session=session)
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan_uuid)

    event_ids_by_block_id: dict[UUID, str] = {}
    for block in blocks:
        if block.workout_type == "rest" or block.calendar_event_id is not None:
            continue
        summary = _WORKOUT_LABELS[block.workout_type]
        if block.target_trimp:
            summary += f" (TRIMP ~{block.target_trimp:.0f})"
        req = CreateEventRequest(
            summary=summary,
            start_at=datetime(block.day.year, block.day.month, block.day.day, 7, 0, tzinfo=UTC),
            end_at=datetime(block.day.year, block.day.month, block.day.day, 8, 0, tzinfo=UTC),
        )
        created = await _create_calendar_event(session, user_id, req)
        event_ids_by_block_id[block.id] = created["id"]

    await repo.commit(
        user_id=user_id, plan_id=plan_uuid, event_ids_by_block_id=event_ids_by_block_id
    )
    return _envelope(
        f"Plan bestätigt, {len(event_ids_by_block_id)} Termine angelegt.",
        {"plan_id": plan_id, "events_created": len(event_ids_by_block_id)},
    )


async def plan_adjust_handler(
    session: AsyncSession, *, user_id: UUID, plan_id: str, reason: str
) -> dict[str, Any]:
    # 0.7 for stress/illness-flavored reasons, else a conservative 0.85 default
    multiplier = 0.7 if any(kw in reason.lower() for kw in _STRESS_KEYWORDS) else 0.85
    plan_uuid = UUID(plan_id)
    repo = PlanRepository(session=session)
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan_uuid)

    today = date.today()
    adjusted = 0
    for block in blocks:
        if block.status != "planned" or block.day < today or block.target_trimp is None:
            continue
        block.target_trimp = block.target_trimp * multiplier
        adjusted += 1
        # NOTE: does not rename already-committed calendar events -- the
        # calendar API has no PATCH/update endpoint (Phase 3 deliberately
        # built only POST+DELETE, see docs/HANDOVER.md), so a committed
        # event's title keeps showing the pre-adjustment TRIMP estimate.
        # The plan data itself (and plan_progress's comparison) reflects the
        # adjustment correctly regardless.
    return _envelope(
        f"{adjusted} künftige Blöcke angepasst (Faktor {multiplier}, Grund: \"{reason}\").",
        {"plan_id": plan_id, "adjusted_blocks": adjusted, "multiplier": multiplier},
    )


async def plan_progress_handler(
    session: AsyncSession, *, user_id: UUID, plan_id: str | None = None
) -> dict[str, Any]:
    repo = PlanRepository(session=session)
    plan = (
        await repo.get(user_id=user_id, plan_id=UUID(plan_id))
        if plan_id
        else await repo.get_active_for_user(user_id=user_id)
    )
    if plan is None:
        return _envelope("Kein aktiver Plan gefunden.", {"plan_id": None})

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    week_blocks = [b for b in blocks if week_start <= b.day <= week_end]
    planned_total = sum(b.target_trimp or 0.0 for b in week_blocks)

    load = await edwards_daily_load_series(
        session, user_id=user_id, end_day=min(today, week_end),
        days=(min(today, week_end) - week_start).days + 1,
    )
    actual_total = sum(load.series.values())

    days = [
        {
            "day": b.day.isoformat(), "workout_type": b.workout_type,
            "planned_trimp": b.target_trimp, "actual_trimp": load.series.get(b.day),
        }
        for b in week_blocks
    ]
    return _envelope(
        f"Diese Woche: geplant {planned_total:.0f} TRIMP, tatsächlich {actual_total:.0f} TRIMP.",
        {"plan_id": str(plan.id), "planned_total": planned_total, "actual_total": actual_total,
         "days": days},
    )


CORE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="query_health",
        description=(
            "Wert einer Kennzahl an einem Tag (Default heute). metric_id aus VERFÜGBARE "
            "KENNZAHLEN. Für Erholung: hrv_baseline, resting_hr_trend, sleep_debt; "
            "für Belastung: training_load, acwr."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "metric_id": {
                    "type": "string", "description": "z.B. 'hrv_baseline', 'training_load'"
                },
                "variant": {"type": "string"},
                "as_of": {"type": "string", "description": "ISO-Datum, Default heute"},
            },
            "required": ["metric_id"],
        },
        handler=query_health_handler,
    ),
    ToolSpec(
        name="analyze_records",
        description=(
            "Tages-Zeitreihe einer Kennzahl über window_days (max. 60) mit "
            "Mittelwert/Min/Max. Nur für Kennzahlen mit 'Zeitreihe: ja' (trimp, sleep_debt)."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "variant": {"type": "string"},
                "window_days": {"type": "integer", "default": 28},
            },
            "required": ["metric_id"],
        },
        handler=analyze_records_handler,
    ),
    ToolSpec(
        name="query_calendar",
        description=(
            "Termine zwischen from_date und to_date; mit duration_minutes zusätzlich "
            "freie Blöcke mindestens dieser Länge (für Trainingsplanung)."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "description": "ISO-Datum"},
                "to_date": {"type": "string", "description": "ISO-Datum"},
                "duration_minutes": {
                    "type": "integer",
                    "description": (
                        "wenn gesetzt, werden auch freie Blöcke dieser Mindestdauer "
                        "zurückgegeben"
                    ),
                },
            },
            "required": ["from_date", "to_date"],
        },
        handler=query_calendar_handler,
    ),
    ToolSpec(
        name="recall",
        description=(
            "Durchsucht gespeicherte Erinnerungen über den Nutzer (Ziele, Vorlieben, "
            "Einschränkungen). Ohne query: die neuesten Einträge."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        },
        handler=recall_handler,
    ),
    ToolSpec(
        name="remember",
        description=(
            "Speichert einen Fakt über den Nutzer, der in späteren Gesprächen wichtig "
            "ist (Ziel, Verletzung, Vorliebe). Keine Messwerte speichern."
        ),
        risk_class="write", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "expires_at": {
                    "type": "string",
                    "description": (
                        "ISO-Datum, nur für zeitlich begrenzte Fakten (z.B. 'nächste Woche "
                        "viel Stress' → Sonntag dieser Woche). Stabile Fakten ohne Ablauf."
                    ),
                },
            },
            "required": ["content"],
        },
        handler=remember_handler,
    ),
    ToolSpec(
        name="render",
        description=(
            "Zeigt Daten aus einem vorherigen Tool-Ergebnis als Diagramm oder Karte im "
            "Chat. Nur Zahlen aus Tool-Ergebnissen dieses Turns verwenden. "
            "config je Komponente: "
            "TimeSeriesChart {title, unit, points:[{date:'YYYY-MM-DD', value}]} (1-366 Punkte); "
            "BarChart {title, unit, bars:[{label, value}]} (1-50); "
            "Gauge {title, unit, value, min, max} mit min<max; "
            "StatCard {title, items:[{label, value (Text oder Zahl), unit?}]} (1-8); "
            "Table {title, columns:[Text] (1-8), rows:[[Text oder Zahl]]} "
            "(Zeilenlänge = Spaltenzahl, max 50 Zeilen)."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "enum": sorted(_RENDER_COMPONENTS)},
                "config": {"type": "object"},
            },
            "required": ["component", "config"],
        },
        handler=render_handler,
    ),
    ToolSpec(
        name="propose_calendar_event",
        description=(
            "Schlägt einen Kalendertermin vor; wird erst nach Bestätigung durch den "
            "Nutzer in Google Calendar angelegt."
        ),
        risk_class="write", requires_confirmation=True,
        json_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_at": {"type": "string", "description": "ISO-Datetime"},
                "end_at": {"type": "string", "description": "ISO-Datetime"},
                "description": {"type": "string"},
            },
            "required": ["summary", "start_at", "end_at"],
        },
        handler=propose_calendar_event_handler,
    ),
    ToolSpec(
        name="delete_calendar_event",
        description=(
            "Schlägt das Löschen eines Kalendertermins vor; wird erst nach Bestätigung "
            "ausgeführt."
        ),
        risk_class="destructive", requires_confirmation=True,
        json_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["event_id"],
        },
        handler=delete_calendar_event_handler,
    ),
    ToolSpec(
        name="plan_propose",
        description=(
            "Erstellt einen Trainingsplan-Entwurf für weeks Wochen auf Basis freier "
            "Kalenderzeit und aktueller Belastung, optional bis goal_date."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "weeks": {"type": "integer", "description": "Planungsdauer in Wochen"},
                "goal_date": {"type": "string", "description": "ISO-Datum, optional (Renntag)"},
            },
            "required": ["weeks"],
        },
        handler=plan_propose_handler,
    ),
    ToolSpec(
        name="plan_commit",
        description=(
            "Überträgt einen Plan-Entwurf in den Kalender; wird erst nach Bestätigung "
            "ausgeführt."
        ),
        risk_class="write", requires_confirmation=True,
        json_schema={
            "type": "object",
            "properties": {"plan_id": {"type": "string"}},
            "required": ["plan_id"],
        },
        handler=plan_commit_handler,
    ),
    ToolSpec(
        name="plan_adjust",
        description=(
            "Reduziert die Belastung künftiger Einheiten eines Plans (z.B. bei Stress "
            "oder Krankheit); wird erst nach Bestätigung ausgeführt."
        ),
        risk_class="write", requires_confirmation=True,
        json_schema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "reason": {"type": "string", "description": "z.B. 'viel Stress nächste Woche'"},
            },
            "required": ["plan_id", "reason"],
        },
        handler=plan_adjust_handler,
    ),
    ToolSpec(
        name="plan_progress",
        description=(
            "Soll/Ist-Vergleich des aktiven (oder angegebenen) Trainingsplans für die "
            "laufende Woche."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "optional, sonst aktiver Plan"},
            },
        },
        handler=plan_progress_handler,
    ),
    ToolSpec(
        name="activity_search",
        description=(
            "Sucht eigene Aktivitäten (Laufen, Rad, Schwimmen, Wandern …) und liefert eine "
            "kompakte Liste mit IDs. Details danach mit activity_get."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string", "description": "YYYY-MM-DD, Default: heute − 30 Tage",
                },
                "to_date": {"type": "string", "description": "YYYY-MM-DD, Default: heute"},
                "sport_profile": {"type": "string", "enum": list(SPORT_PROFILES)},
                "name_contains": {"type": "string"},
                "min_distance_km": {"type": "number"},
                "max_distance_km": {"type": "number"},
                "sort": {"type": "string", "enum": list(SEARCH_SORTS)},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        handler=activity_search_handler,
    ),
    ToolSpec(
        name="activity_get",
        description=(
            "Steckbrief einer Aktivität: Umfang, Pace/Tempo, Herzfrequenz, Zonen, Belastung, "
            "schnellster und langsamster km. Ohne activity_id: die letzte Aktivität (optional "
            "gefiltert nach sport_profile)."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer"},
                "sport_profile": {"type": "string", "enum": list(SPORT_PROFILES)},
            },
        },
        handler=activity_get_handler,
    ),
    ToolSpec(
        name="activity_splits",
        description=(
            "Split-Tabelle einer Aktivität: eine Zeile pro km (Rad 5 km, Schwimmen 100 m), pro "
            "Uhr-Runde oder pro Workout-Schritt mit Ziel und Treffer (Soll/Ist), jeweils mit "
            "Pace, Höhenmetern und HF."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer"},
                "kind": {"type": "string", "enum": list(SPLIT_KINDS)},
                "from_idx": {"type": "integer", "minimum": 1},
                "to_idx": {"type": "integer", "minimum": 1},
            },
            "required": ["activity_id"],
        },
        handler=activity_splits_handler,
    ),
    ToolSpec(
        name="activity_analyze",
        description=(
            "Serverseitige Auswertung einer Aktivität: segment (Abschnitt nach km oder "
            "Minuten), compare (Vergleich mit zweiter Aktivität), hr_drift (aerobe "
            "Entkopplung), curve (Verlauf mit höchstens 60 Punkten für render)."
        ),
        risk_class="read", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer"},
                "operation": {"type": "string", "enum": list(ANALYZE_OPERATIONS)},
                "other_activity_id": {"type": "integer", "description": "nur compare"},
                "from_km": {"type": "number"},
                "to_km": {"type": "number"},
                "from_min": {"type": "number"},
                "to_min": {"type": "number"},
                "metric": {
                    "type": "string", "enum": list(CURVE_METRICS), "description": "nur curve",
                },
                "points": {"type": "integer", "minimum": 10, "maximum": 60},
            },
            "required": ["activity_id", "operation"],
        },
        handler=activity_analyze_handler,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in CORE_TOOLS}
