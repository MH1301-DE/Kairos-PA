from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.coach import service as coach_service
from kairos.db.models import AppUser, Connection
from kairos.metrics.bootstrap import build_default_registry
from kairos.metrics.hr_zones import hr_max_warning, resolve_hr_max
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.goals import SqlGoalRepository
from kairos.repositories.user_setting import get_or_default_user_setting, measured_max_hr_12m

_WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


async def build_situation_brief(session: AsyncSession, *, user_id: UUID, now: datetime) -> str:
    """Deterministic, no LLM call -- see docs/03-agent-design.md §3.

    MVP scope (design spec Scope-Entscheidung 1): always the full form, no
    intent-adaptive shortening.
    """
    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    display_name = user_row.display_name if user_row else "Nutzer"
    today = now.date()

    lines = [f"AKTUELLE LAGE · {display_name} · {_format_now(now)}", ""]
    lines.append(await _datenstand_line(session, user_id))
    lines.append("")
    lines.extend(await _erholung_lines(session, user_id, today))
    lines.append("")
    lines.extend(await _belastung_lines(session, user_id, today))
    lines.append("")
    lines.extend(await _kalender_lines(session, user_id, now))
    lines.append("")
    lines.append(await _ziele_line(session, user_id))
    coach_line = await coach_service.brief_line(session, user_id, today)
    if coach_line:
        lines.append(coach_line)
    hr_max_line = await _hr_max_line(session, user_id, today)
    if hr_max_line:
        lines.append(hr_max_line)
    return "\n".join(lines)


def _format_now(now: datetime) -> str:
    weekday = _WEEKDAYS_DE[now.weekday()]
    return f"{weekday}, {now.strftime('%d.%m.%Y, %H:%M')}"


async def _datenstand_line(session: AsyncSession, user_id: UUID) -> str:
    rows = (
        await session.execute(select(Connection).where(Connection.user_id == user_id))
    ).scalars().all()
    by_connector = {c.connector: c for c in rows}
    parts = []
    for connector, label in (("garmin", "Garmin"), ("google_calendar", "Google Cal")):
        conn = by_connector.get(connector)
        if conn is None:
            parts.append(f"{label} nicht verbunden")
        elif conn.status == "active":
            parts.append(f"{label} ✓")
        else:
            parts.append(f"{label} ⚠ {conn.status}")
    return "Datenstand: " + " · ".join(parts)


async def _erholung_lines(session: AsyncSession, user_id: UUID, today: date) -> list[str]:
    registry = build_default_registry()
    lines = ["Erholung:"]

    hrv = await registry.get("hrv_baseline", "default").compute(
        session, user_id=user_id, as_of=today
    )
    if hrv.confidence != "insufficient_data" and isinstance(hrv.value, dict):
        lines.append(
            f"  HRV {hrv.value['today']:.0f} ms "
            f"(Baseline {hrv.value['baseline_mean']:.0f}, "
            f"{hrv.value['baseline_low']:.0f}-{hrv.value['baseline_high']:.0f})"
        )
    else:
        lines.append("  HRV: nicht genug Daten")

    resting_hr = await registry.get("resting_hr_trend", "default").compute(
        session, user_id=user_id, as_of=today
    )
    if resting_hr.confidence != "insufficient_data" and isinstance(resting_hr.value, dict):
        delta = resting_hr.value["delta_bpm"]
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        lines.append(f"  Ruhepuls-Trend: {resting_hr.value['recent_avg']:.0f} bpm ({arrow})")
    else:
        lines.append("  Ruhepuls-Trend: nicht genug Daten")

    sleep_debt = await registry.get("sleep_debt", "default").compute(
        session, user_id=user_id, as_of=today
    )
    if sleep_debt.confidence != "insufficient_data" and isinstance(sleep_debt.value, int | float):
        lines.append(f"  Schlafdefizit: {sleep_debt.value:.1f} h")
    else:
        lines.append("  Schlaf: nicht genug Daten")

    return lines


async def _belastung_lines(session: AsyncSession, user_id: UUID, today: date) -> list[str]:
    registry = build_default_registry()
    result = await registry.get("training_load", "default").compute(
        session, user_id=user_id, as_of=today
    )
    if result.confidence != "insufficient_data" and isinstance(result.value, dict):
        return [
            "Belastung:",
            f"  CTL {result.value['ctl']:.0f} · "
            f"ATL {result.value['atl']:.0f} · "
            f"TSB {result.value['tsb']:.0f}",
        ]
    return ["Belastung:", "  nicht genug Daten"]


async def _kalender_lines(session: AsyncSession, user_id: UUID, now: datetime) -> list[str]:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tomorrow_end = today_end + timedelta(days=1)

    repo = CalendarEventRepository(session)
    today_events = await repo.list_between(user_id, today_start, today_end)
    tomorrow_events = await repo.list_between(user_id, today_end, tomorrow_end)

    lines = ["Kalender:"]
    if today_events:
        first = min(today_events, key=lambda e: e.start_at)
        last = max(today_events, key=lambda e: e.end_at)
        lines.append(
            f"  Heute {len(today_events)} Termine, "
            f"erster {first.start_at.strftime('%H:%M')}, "
            f"letzter endet {last.end_at.strftime('%H:%M')}"
        )
    else:
        lines.append("  Heute keine Termine")
    lines.append(
        f"  Morgen: {len(tomorrow_events)} Termine" if tomorrow_events else "  Morgen: frei"
    )
    return lines


async def _ziele_line(session: AsyncSession, user_id: UUID) -> str:
    repo = SqlGoalRepository(session=session)
    goals = [g for g in await repo.list_for_user(user_id=user_id) if g.status == "active"]
    if not goals:
        return "Aktive Ziele: keine"
    parts = []
    for g in goals:
        target = f" ({g.target_date.isoformat()})" if g.target_date else ""
        parts.append(f"{g.title}{target}")
    return "Aktive Ziele: " + " · ".join(parts)


async def _hr_max_line(session: AsyncSession, user_id: UUID, today: date) -> str | None:
    setting = await get_or_default_user_setting(session, user_id=user_id)
    used, source = resolve_hr_max(setting.birth_date, setting.hr_max_override, as_of=today)
    if used is None:
        return "HFmax fehlt (Einstellungen)"
    measured = await measured_max_hr_12m(session, user_id=user_id)
    warning = hr_max_warning(used, source, measured)
    return f"HFmax: {warning}" if warning else None
