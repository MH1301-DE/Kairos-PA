"""Coach orchestration for tools and API (coach spec 6.1 ``service.py``).

Loads the generator inputs, persists drafts, computes plan progress, matches activities
to plan blocks and derives reference values. Every function expects a session with
``install_rls_listener`` for the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.coach.generator import PlanInput, generate
from kairos.coach.history import load_history
from kairos.coach.knowledge import KnowledgeBase, PlanType, get_knowledge
from kairos.coach.model import (
    BlockDraft,
    GoalSpec,
    PlanOutput,
    ReferenceValues,
    Verstoss,
    WeekPlan,
    availability_from_json,
    week_start,
)
from kairos.coach.rules import Einheit, Test
from kairos.coach.validator import PlanView, validate
from kairos.coach.zones import (
    format_pace,
    pace_s_per_km,
    race_time_s,
    vdot_from_race,
)
from kairos.db.models import (
    Activity,
    ActivitySplit,
    ActivityStats,
    ActivityStepResult,
    AppUser,
    Goal,
    Plan,
    PlanBlock,
    UserSetting,
)
from kairos.metrics.hr_zones import resolve_hr_max
from kairos.repositories.coach import CoachProfileRepository, ReferenceValueRepository
from kairos.repositories.plan import PlanRepository

REFERENCE_VALUE_STALE_DAYS = 84
PARTIAL_SHARE = 0.80
_STRENGTH_SPORTS = frozenset({"strength_training", "indoor_cardio", "hiit"})


class CoachNotReady(Exception):
    """A precondition is missing; the message is shown to the user as is."""


def next_monday(today: date) -> date:
    return today if today.weekday() == 0 else today + timedelta(days=7 - today.weekday())


def goal_distance_m(goal: Goal | None) -> float | None:
    """Race distance from the goal title ("Marathon April", "Halbmarathon", "10 km Lauf")."""
    if goal is None:
        return None
    title = goal.title.lower()
    if "halbmarathon" in title or re.search(r"\bhm\b", title):
        return 21_097.5
    if "marathon" in title:
        return 42_195.0
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(km|k)\b", title)
    if match:
        return float(match.group(1).replace(",", ".")) * 1000
    if goal.target_unit == "km" and goal.target_value:
        return float(goal.target_value) * 1000
    return None


@dataclass(frozen=True)
class CoachContext:
    plan_type: PlanType
    parameters: dict[str, Any]
    timezone: str
    references: ReferenceValues
    supplementary: tuple[str, ...]


async def context(session: AsyncSession, user_id: UUID, today: date) -> CoachContext:
    profile = await CoachProfileRepository(session).get(user_id)
    if profile is None:
        raise CoachNotReady(
            "Es gibt noch kein Coach-Profil. Bitte zuerst den Einstieg auf der Seite "
            "„Coach“ ausfüllen (Ziel, Tage, Sportarten, Bezugswert)."
        )
    kb = get_knowledge()
    plan_type = kb.plan_types.get(profile.plan_type)
    if plan_type is None:
        raise CoachNotReady(f"Plantyp „{profile.plan_type}“ ist nicht verfügbar.")
    return CoachContext(
        plan_type=plan_type,
        parameters=dict(profile.parameters or {}),
        timezone=await _timezone(session, user_id),
        references=await reference_values(session, user_id, today),
        supplementary=tuple(profile.supplementary or ()),
    )


async def _timezone(session: AsyncSession, user_id: UUID) -> str:
    tz = (
        await session.execute(select(AppUser.home_timezone).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    return tz or "Europe/Berlin"


async def reference_values(session: AsyncSession, user_id: UUID, today: date) -> ReferenceValues:
    current = await ReferenceValueRepository(session).current(user_id)
    setting = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one_or_none()
    hr_max, source = resolve_hr_max(
        setting.birth_date if setting else None,
        setting.hr_max_override if setting else None,
        as_of=today,
    )
    vdot = current.get("vdot")
    lthr = current.get("lthr_laufen")
    return ReferenceValues(
        vdot=vdot.value if vdot else None,
        vdot_measured_on=vdot.measured_on if vdot else None,
        lthr_laufen=lthr.value if lthr else None,
        hf_max=hr_max,
        hf_max_estimated=source == "aus Alter",
    )


async def _goal(session: AsyncSession, user_id: UUID, goal_id: UUID | None) -> Goal | None:
    stmt = select(Goal).where(Goal.user_id == user_id)
    if goal_id is not None:
        goal = (await session.execute(stmt.where(Goal.id == goal_id))).scalar_one_or_none()
        if goal is None:
            raise CoachNotReady("Ziel nicht gefunden.")
        return goal
    # the nearest active goal with a date is the race the plan works towards
    rows = await session.execute(
        stmt.where(Goal.status == "active", Goal.target_date.is_not(None)).order_by(
            Goal.target_date
        )
    )
    return next(iter(rows.scalars()), None)


async def propose(
    session: AsyncSession,
    user_id: UUID,
    *,
    today: date,
    goal_id: UUID | None = None,
    start: date | None = None,
    overrides: dict[str, Any] | None = None,
) -> tuple[Plan, PlanOutput, Goal | None]:
    ctx = await context(session, user_id, today)
    goal = await _goal(session, user_id, goal_id)
    distance = goal_distance_m(goal)
    if (
        goal is not None
        and goal.target_date
        and distance
        and "wettkampf" in ctx.plan_type.head.ziele
    ):
        spec = GoalSpec("wettkampf", goal.target_date, distance, None, goal.title)
    else:
        spec = GoalSpec("gesundheit", None, distance, None, goal.title if goal else "")
    profile = await CoachProfileRepository(session).get(user_id)
    assert profile is not None
    begin = start or next_monday(today)
    inp = PlanInput(
        plan_type=ctx.plan_type,
        parameters={**ctx.parameters, **(overrides or {})},
        goal=spec,
        start=begin,
        availability=availability_from_json(profile.availability),
        reference_values=ctx.references,
        history=await load_history(session, user_id, begin),
        supplementary=ctx.supplementary,
    )
    out = generate(inp)
    if spec.kind == "gesundheit" and goal is None:
        out.warnings.insert(
            0,
            Verstoss("", "hinweis", "Kein aktives Ziel mit Datum: Plan ohne Wettkampf.", ""),
        )
    end = spec.race_date or (out.weeks[-1].start + timedelta(days=6) if out.weeks else begin)
    plan = await PlanRepository(session=session).create_coach_draft(
        user_id=user_id,
        title=f"{goal.title if goal else 'Training'} ab {begin:%d.%m.%Y}",
        start_date=begin,
        end_date=end,
        goal_date=spec.race_date,
        goal_id=goal.id if goal else None,
        plan_type=ctx.plan_type.id,
        plan_type_version=ctx.plan_type.head.version,
        parameters={**ctx.plan_type.parameters, **inp.parameters},
        detail_until=out.detail_until,
        phases=out.phases,
        blocks=out.blocks,
        timezone=ctx.timezone,
    )
    return plan, out, goal


# --- matching activities to plan blocks (coach spec 7.3) ---------------------------------


async def match_activities(session: AsyncSession, user_id: UUID, today: date) -> int:
    """Assigns finished activities to open blocks of the active plan; past days without
    one are skipped. Returns the number of changed blocks."""
    plan = await PlanRepository(session=session).get_active_for_user(user_id=user_id)
    if plan is None:
        return 0
    blocks = (
        (
            await session.execute(
                select(PlanBlock).where(
                    PlanBlock.plan_id == plan.id,
                    PlanBlock.user_id == user_id,
                    PlanBlock.status == "planned",
                    PlanBlock.day <= today,
                )
            )
        )
        .scalars()
        .all()
    )
    if not blocks:
        return 0
    first = min(b.day for b in blocks)
    taken = set(
        (
            await session.execute(
                select(PlanBlock.activity_id).where(
                    PlanBlock.user_id == user_id, PlanBlock.activity_id.is_not(None)
                )
            )
        ).scalars()
    )
    activities = (
        await session.execute(
            select(
                Activity.id,
                Activity.start_local,
                Activity.sport,
                Activity.sport_profile,
                Activity.duration_s,
            ).where(
                Activity.user_id == user_id,
                Activity.deleted_at.is_(None),
                Activity.start_local >= first,
            )
        )
    ).all()
    changed = 0
    for block in sorted(blocks, key=lambda b: b.day):
        candidates = [
            a
            for a in activities
            if a.id not in taken
            and a.start_local is not None
            and a.start_local.date() == block.day
            and _same_sport(block, a.sport, a.sport_profile)
        ]
        if candidates:
            planned = block.planned_duration_s or 0
            best = min(candidates, key=lambda a: abs((a.duration_s or 0) - planned))
            block.activity_id = best.id
            taken.add(best.id)
            done = planned == 0 or (best.duration_s or 0) >= PARTIAL_SHARE * planned
            block.status = "done" if done else "partial"
            changed += 1
        elif block.day < today:
            block.status = "skipped"
            changed += 1
    await session.flush()
    return changed


def _same_sport(block: PlanBlock, sport: str | None, profile: str) -> bool:
    if block.sport == "kraft":
        return sport in _STRENGTH_SPORTS
    return profile == "running"


# --- progress (coach spec 8.5) -------------------------------------------------------------


def _short(block: PlanBlock, kb: KnowledgeBase) -> str:
    entry = kb.entries.get(block.unit_id or "")
    title = entry.head.titel if entry else block.workout_type
    parts = [title]
    if block.planned_duration_s:
        parts.append(f"{round(block.planned_duration_s / 60)} min")
    if block.planned_distance_m:
        parts.append(f"{block.planned_distance_m / 1000:.1f} km")
    targets = _main_targets(block.steps or [])
    if targets:
        parts.append(targets)
    return ", ".join(parts)


def _main_targets(steps: list[dict[str, Any]]) -> str:
    for step in steps:
        inner = step.get("schritte")
        if inner:
            found = _main_targets(inner)
            if found:
                reps = step.get("repeat")
                return f"{reps}× {found}" if reps else found
        elif step.get("typ") == "belastung":
            bits = []
            if step.get("dauer_s") and step.get("tempo") not in ("E",):
                bits.append(f"{round(step['dauer_s'] / 60)}′")
            if step.get("pace_s_km"):
                fast, slow = step["pace_s_km"]
                bits.append(f"{format_pace(fast)}–{format_pace(slow)}/km")
            if step.get("hr_bpm"):
                bits.append(f"{step['hr_bpm'][0]}–{step['hr_bpm'][1]} bpm")
            return " ".join(bits)
    return ""


async def _actual(session: AsyncSession, activity_id: int) -> dict[str, Any]:
    stats = await session.get(ActivityStats, activity_id)
    steps = (
        (
            await session.execute(
                select(ActivityStepResult.hit).where(ActivityStepResult.activity_id == activity_id)
            )
        )
        .scalars()
        .all()
    )
    judged = [s for s in steps if s is not None]
    return {
        "activity_id": activity_id,
        "distance_km": round(stats.distance_m / 1000, 2) if stats and stats.distance_m else None,
        "dauer_min": round((stats.moving_s or stats.timer_s or 0) / 60) if stats else None,
        "hf_avg": stats.hr_avg if stats else None,
        "entkopplung_pct": stats.decoupling_pct if stats else None,
        "trefferquote": round(sum(judged) / len(judged), 2) if judged else None,
    }


async def progress(
    session: AsyncSession,
    user_id: UUID,
    *,
    today: date,
    scope: str,
    week: date | None = None,
) -> dict[str, Any]:
    repo = PlanRepository(session=session)
    plan = await repo.get_active_for_user(user_id=user_id)
    draft = plan is None
    if plan is None:
        plan = await repo.latest_draft(user_id=user_id)
    if plan is None or plan.plan_type is None:
        return {"plan": None}
    kb = get_knowledge()
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    phases = await repo.list_phases(user_id=user_id, plan_id=plan.id)
    references = await reference_values(session, user_id, today)
    current_phase = next((p for p in phases if p.start_date <= today <= p.end_date), None)
    head: dict[str, Any] = {
        "plan_id": str(plan.id),
        "titel": plan.title,
        "status": "Entwurf" if draft else "aktiv",
        "ziel_datum": plan.goal_date.isoformat() if plan.goal_date else None,
        "phase": current_phase.kind if current_phase else None,
        "bezugswerte": _reference_summary(references, today),
    }
    if scope == "heute":
        todays = [b for b in blocks if b.day == today]
        upcoming = [b for b in blocks if b.day > today and b.workout_type == "quality"]
        return {
            **head,
            "heute": [
                {"block_id": str(b.id), "einheit": _short(b, kb), "status": b.status}
                for b in todays
            ]
            or "Ruhetag",
            "naechste_qualitaet": (
                {"tag": upcoming[0].day.isoformat(), "einheit": _short(upcoming[0], kb)}
                if upcoming
                else None
            ),
        }
    if scope == "plan":
        history = await load_history(session, user_id, today)
        weeks = sorted({week_start(b.day) for b in blocks})
        return {
            **head,
            "phasen": [
                {
                    "art": p.kind,
                    "von": p.start_date.isoformat(),
                    "bis": p.end_date.isoformat(),
                    "umfang_km": [p.volume_min_km, p.volume_max_km],
                    "schwerpunkt": p.focus,
                }
                for p in phases
            ],
            "umfang_ist_km": {
                (today - timedelta(weeks=8 - i)).isoformat(): round(km, 1)
                for i, km in enumerate(history.weekly_km(today, 8))
            },
            "detail_wochen": [w.isoformat() for w in weeks],
        }
    monday = week or week_start(today)
    week_blocks = [b for b in blocks if week_start(b.day) == monday]
    rows = []
    for b in week_blocks:
        row: dict[str, Any] = {
            "block_id": str(b.id),
            "tag": b.day.isoformat(),
            "einheit": _short(b, kb),
            "status": b.status,
        }
        if b.activity_id is not None:
            row["ist"] = await _actual(session, b.activity_id)
        rows.append(row)
    planned_km = sum((b.planned_distance_m or 0) for b in week_blocks if b.sport == "laufen") / 1000
    actual_km = sum(
        (r["ist"]["distance_km"] or 0) for r in rows if "ist" in r and r["ist"]["distance_km"]
    )
    violations = await _week_violations(session, user_id, plan, week_blocks, monday, today)
    return {
        **head,
        "woche": monday.isoformat(),
        "einheiten": rows,
        "umfang_km": {"soll": round(planned_km, 1), "ist": round(actual_km, 1)},
        "leitplanken": [v.to_json() for v in violations] or "eingehalten",
    }


def _reference_summary(refs: ReferenceValues, today: date) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if refs.vdot is not None:
        age = (today - refs.vdot_measured_on).days if refs.vdot_measured_on else None
        out["vdot"] = {
            "wert": round(refs.vdot, 1),
            "alter_tage": age,
            "test_faellig": age is not None and age > REFERENCE_VALUE_STALE_DAYS,
        }
    else:
        out["vdot"] = "fehlt – Test einplanen"
    if refs.lthr_laufen is not None:
        out["lthr_laufen"] = round(refs.lthr_laufen)
    if refs.hf_max is not None:
        out["hf_max"] = {"wert": refs.hf_max, "geschaetzt": refs.hf_max_estimated}
    return out


async def _week_violations(
    session: AsyncSession,
    user_id: UUID,
    plan: Plan,
    blocks: list[PlanBlock],
    monday: date,
    today: date,
) -> list[Verstoss]:
    kb = get_knowledge()
    plan_type = kb.plan_types.get(plan.plan_type or "")
    if plan_type is None:
        return []
    drafts = [_as_draft(b, plan_type) for b in blocks]
    history = await load_history(session, user_id, monday)
    view = PlanView(
        drafts,
        [
            WeekPlan(
                monday,
                drafts[0].phase if drafts else "basis",
                sum((d.distance_m or 0) for d in drafts) / 1000,
            )
        ],
        history,
    )
    return [v for v in validate(view, plan_type) if v.art != "hinweis"]


def _as_draft(block: PlanBlock, plan_type: PlanType) -> BlockDraft:
    zones = _zone_seconds(block.steps or [])
    entry = plan_type.entries.get(block.unit_id or "")
    unit = entry.head.regel if entry else None
    main = (
        float(block.planned_distance_m or 0)
        if isinstance(unit, Einheit) and unit.klasse in ("long_run", "easy")
        else _main_distance(block.steps or [])
    )
    return BlockDraft(
        day=block.day,
        sport=block.sport or "laufen",
        unit_id=block.unit_id or "",
        unit_ref=entry.ref if entry else "",
        workout_type=block.workout_type,
        duration_s=float(block.planned_duration_s or 0),
        distance_m=float(block.planned_distance_m) if block.planned_distance_m else None,
        zone_s=zones,
        main_distance_m=main,
        steps=[],
        rule_refs=list(block.rule_refs or []),
        phase="basis",
        start_time=block.start_at.strftime("%H:%M") if block.start_at else None,
    )


_TEMPO_ZONE = {"E": "z1", "G": "z1", "M": "z2", "T": "z2", "I": "z3", "R": "z3"}


def _zone_seconds(steps: list[dict[str, Any]], factor: int = 1) -> dict[str, float]:
    out = {"z1": 0.0, "z2": 0.0, "z3": 0.0}
    for step in steps:
        if step.get("schritte"):
            inner = _zone_seconds(step["schritte"], factor * int(step.get("repeat") or 1))
            for key, value in inner.items():
                out[key] += value
        elif step.get("tempo"):
            out[_TEMPO_ZONE.get(step["tempo"], "z1")] += float(step.get("dauer_s") or 0) * factor
    return out


def _main_distance(steps: list[dict[str, Any]], factor: int = 1) -> float:
    total = 0.0
    for step in steps:
        if step.get("schritte"):
            total += _main_distance(step["schritte"], factor * int(step.get("repeat") or 1))
        elif step.get("typ") == "belastung" and step.get("tempo") not in (None, "E"):
            total += float(step.get("distanz_m") or 0) * factor
    return total


# --- reference values (coach spec 4.2, 8.6) ------------------------------------------------


@dataclass(frozen=True)
class ReferenceProposal:
    kind: str
    value: float
    measured_on: date
    source: str
    activity_id: int | None
    calculation: str
    ranges: dict[str, str]


async def compute_reference(
    session: AsyncSession,
    user_id: UUID,
    *,
    kind: str,
    value: float | None,
    activity_id: int | None,
    measured_on: date | None,
    source: str,
    today: date,
) -> ReferenceProposal:
    if activity_id is not None:
        value, measured_on, calculation = await _from_activity(session, user_id, kind, activity_id)
    elif value is not None:
        calculation = "manuell eingetragen"
    else:
        raise ValueError("value oder activity_id angeben")
    if value is None or value <= 0:
        raise ValueError("Bezugswert muss positiv sein")
    return ReferenceProposal(
        kind=kind,
        value=round(value, 2),
        measured_on=measured_on or today,
        source=source,
        activity_id=activity_id,
        calculation=calculation,
        ranges=_ranges(kind, value),
    )


async def _from_activity(
    session: AsyncSession, user_id: UUID, kind: str, activity_id: int
) -> tuple[float, date, str]:
    row = (
        await session.execute(
            select(
                Activity.start_local,
                ActivityStats.distance_m,
                ActivityStats.moving_s,
                ActivityStats.timer_s,
            )
            .join(ActivityStats, ActivityStats.activity_id == Activity.id)
            .where(Activity.id == activity_id, Activity.user_id == user_id)
        )
    ).one_or_none()
    if row is None or row.start_local is None:
        raise ValueError("Aktivität nicht gefunden oder noch nicht ausgewertet")
    day = row.start_local.date()
    seconds = float(row.moving_s or row.timer_s or 0)
    if kind == "vdot":
        test = _vdot_test()
        distance = float(row.distance_m or 0)
        if test.distanz_m and not test.distanz_m.min <= distance <= test.distanz_m.max:
            raise ValueError("VDOT nur aus Läufen über 3 bis 15 km (lauf.test.vdot)")
        vdot = vdot_from_race(distance, seconds)
        minutes, secs = divmod(round(seconds), 60)
        return (
            vdot,
            day,
            (
                f"{distance / 1000:.2f} km in {minutes // 60}:{minutes % 60:02d}:{secs:02d} "
                f"→ VDOT {vdot:.1f} (Daniels & Gilbert)"
            ),
        )
    if kind == "lthr_laufen":
        if seconds < 25 * 60:
            raise ValueError("Für die LTHR mindestens 25 Minuten Lauf nötig (30-min-Test)")
        lthr = await _last_minutes_hr(session, activity_id, seconds, 20 * 60)
        return lthr, day, f"Ø-HF der letzten 20 min: {lthr:.0f} bpm"
    raise ValueError(f"{kind} lässt sich noch nicht aus einer Aktivität berechnen")


def _vdot_test() -> Test:
    entry = get_knowledge().entries["lauf.test.vdot"]
    assert isinstance(entry.head.regel, Test)
    return entry.head.regel


async def _last_minutes_hr(
    session: AsyncSession, activity_id: int, total_s: float, window_s: float
) -> float:
    # km splits are the finest stored series with heart rate (stage 1 B.3)
    rows = (
        await session.execute(
            select(ActivitySplit.start_offset_s, ActivitySplit.timer_s, ActivitySplit.hr_avg)
            .where(ActivitySplit.activity_id == activity_id, ActivitySplit.kind == "distance")
            .order_by(ActivitySplit.idx)
        )
    ).all()
    start = total_s - window_s
    weighted = weight = 0.0
    for r in rows:
        if r.hr_avg is None or r.timer_s is None or r.start_offset_s is None:
            continue
        overlap = min(r.start_offset_s + r.timer_s, total_s) - max(r.start_offset_s, start)
        if overlap > 0:
            weighted += r.hr_avg * overlap
            weight += overlap
    if weight <= 0:
        raise ValueError("Keine Herzfrequenz in den letzten 20 Minuten")
    return weighted / weight


def _ranges(kind: str, value: float) -> dict[str, str]:
    if kind == "vdot":
        out = {}
        for name, lo, hi in (("E", 65, 74), ("M", 75, 84), ("T", 86, 89), ("I", 96, 100)):
            fast, slow = pace_s_per_km(value, hi), pace_s_per_km(value, lo)
            out[name] = f"{format_pace(fast)}–{format_pace(slow)}/km"
        out["HM"] = _clock(race_time_s(value, 21_097.5))
        out["Marathon"] = _clock(race_time_s(value, 42_195))
        return out
    if kind == "lthr_laufen":
        return {
            "Z1": f"< {round(value * 0.85)} bpm",
            "T": f"{round(value * 0.95)}–{round(value)} bpm",
        }
    return {}


def _clock(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes // 60}:{minutes % 60:02d}:{secs:02d}"


async def save_reference(session: AsyncSession, user_id: UUID, proposal: ReferenceProposal) -> None:
    await ReferenceValueRepository(session).add(
        user_id,
        kind=proposal.kind,
        value=proposal.value,
        measured_on=proposal.measured_on,
        source=proposal.source,
        activity_id=proposal.activity_id,
        note=proposal.calculation,
    )


async def brief_line(session: AsyncSession, user_id: UUID, today: date) -> str | None:
    """Coach line of the situation brief (coach spec 7.3); only with an active coach plan."""
    repo = PlanRepository(session=session)
    plan = await repo.get_active_for_user(user_id=user_id)
    if plan is None or plan.plan_type is None:
        return None
    phases = await repo.list_phases(user_id=user_id, plan_id=plan.id)
    current = next((p for p in phases if p.start_date <= today <= p.end_date), None)
    parts = [f"Coach: Plan „{plan.title}“"]
    if current is not None:
        week = (today - current.start_date).days // 7 + 1
        total = (current.end_date - current.start_date).days // 7 + 1
        parts.append(f"Phase {current.kind} (Woche {week}/{total})")
    kb = get_knowledge()
    todays = [b for b in await repo.list_blocks(user_id=user_id, plan_id=plan.id) if b.day == today]
    parts.append("heute: " + ("; ".join(_short(b, kb) for b in todays) if todays else "Ruhetag"))
    refs = await reference_values(session, user_id, today)
    if refs.vdot is None:
        parts.append("Test fällig: VDOT fehlt")
    elif (
        refs.vdot_measured_on and (today - refs.vdot_measured_on).days > REFERENCE_VALUE_STALE_DAYS
    ):
        parts.append(f"Test fällig: VDOT ({(today - refs.vdot_measured_on).days} Tage)")
    return ", ".join(parts)
