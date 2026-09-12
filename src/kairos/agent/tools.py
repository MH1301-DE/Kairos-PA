from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.calendar.free_time import BusyBlock, CalendarPrefs, compute_free_blocks
from kairos.db.models import MetricDailyValue
from kairos.metrics.bootstrap import build_default_registry
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.memory import SqlMemoryRepository
from kairos.routers.calendar import (
    CreateEventRequest,
    _create_calendar_event,
    _delete_calendar_event,
    _load_prefs,
)

# Hardcap per docs/03-agent-design.md §4.5 -- a tool result never dumps a raw
# time series beyond this, the caller re-queries with a narrower window instead
_MAX_ANALYZE_DAYS_RETURNED = 60

_RENDER_COMPONENTS = frozenset(
    {"Gauge", "TimeSeriesChart", "BarChart", "ScatterChart", "StatCard", "Table", "ActivityList"}
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk_class: Literal["read", "write", "destructive"]
    requires_confirmation: bool
    json_schema: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]


def _envelope(
    summary: str, data: Any, *, coverage: str | None = None, truncated: bool = False
) -> dict[str, Any]:
    return {
        "summary": summary,
        "data": data,
        "meta": {
            "row_count": len(data) if isinstance(data, list) else None,
            "truncated": truncated,
            "coverage": coverage,
            "as_of": datetime.now(UTC).isoformat(),
        },
    }


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
    chosen = variant or variants[0]
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
            "unit": result.unit, "confidence": result.confidence,
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
    chosen = variant or variants[0]
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
    entries = await repo.list_for_user(user_id=user_id)
    if query:
        entries = [e for e in entries if query.lower() in e.content.lower()]
    entries = entries[:limit]
    data = [{"id": str(e.id), "content": e.content, "source": e.source} for e in entries]
    return _envelope(f"{len(data)} Gedächtnis-Einträge gefunden.", data)


async def remember_handler(session: AsyncSession, *, user_id: UUID, content: str) -> dict[str, Any]:
    # write-class but executes immediately, no Proposal -- design spec
    # Scope-Entscheidung 4: visible undo chip in the frontend instead of a
    # pre-confirmation, dispatcher.py special-cases this tool by name
    repo = SqlMemoryRepository(session=session)
    entry = await repo.create(user_id=user_id, content=content, source="agent")
    await session.commit()
    return _envelope(
        f"Gemerkt: {content}", {"id": str(entry.id), "content": entry.content, "source": "agent"}
    )


async def render_handler(
    session: AsyncSession, *, user_id: UUID, component: str, config: dict[str, Any]
) -> dict[str, Any]:
    del session, user_id  # no data fetching of its own -- data comes from a prior tool call
    if component not in _RENDER_COMPONENTS:
        raise ValueError(f"Unknown render component: {component!r}")
    return _envelope(f"{component}-Chart erzeugt.", {"component": component, "config": config})


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


CORE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="query_health", risk_class="read", requires_confirmation=False,
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
        name="analyze_records", risk_class="read", requires_confirmation=False,
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
        name="query_calendar", risk_class="read", requires_confirmation=False,
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
        name="recall", risk_class="read", requires_confirmation=False,
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
        name="remember", risk_class="write", requires_confirmation=False,
        json_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
        handler=remember_handler,
    ),
    ToolSpec(
        name="render", risk_class="read", requires_confirmation=False,
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
        name="propose_calendar_event", risk_class="write", requires_confirmation=True,
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
        name="delete_calendar_event", risk_class="destructive", requires_confirmation=True,
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
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in CORE_TOOLS}
