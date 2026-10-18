"""Deterministic plan generator (coach spec 6.2-6.4).

Pure function without database or network access: phases with weekly volumes up to the
goal, single sessions for the next ``detail_wochen`` weeks. Every number comes from the
knowledge base or the user's data; the LLM only explains (S2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from kairos.coach.knowledge import Entry, PlanType
from kairos.coach.model import (
    RUN_SPORT,
    BlockDraft,
    DayAvailability,
    GoalSpec,
    PhaseDraft,
    PlanOutput,
    ReferenceValues,
    StepDraft,
    TrainingHistory,
    Verstoss,
    WeekPlan,
    week_start,
)
from kairos.coach.rules import Einheit, ObergrenzeRelativ, Schritt, Taper, Zonen
from kairos.coach.validator import PlanView, validate
from kairos.coach.zones import ZoneTable, build_zone_table

MIN_PLAN_WEEKS = 4
NO_HISTORY_START_KM = 10.0
WEEKLY_GROWTH = 1.08
# share of the available running time a peak week may use
PEAK_CAPACITY_SHARE = 0.85
# without any run in the last 30 days the single-run guard rail has no reference
NO_REFERENCE_LONGEST_M = 10_000.0
MIN_LONG_RUN_M = 5_000.0
EASY_MIN_S = 1_800.0
STRENGTH_S = 2_700.0
REFERENCE_STALE_DAYS = 84
LONG_RUN_SHARE = 0.35
MARATHON_PACE_SHARE = 0.15
Z1_TARGET = 0.75
# s/km when no VDOT exists yet (plan starts with a test)
_FALLBACK_PACE = {"E": 390.0, "M": 345.0, "T": 320.0, "I": 300.0, "R": 285.0, "G": 600.0}
_KLASSE_TO_WORKOUT_TYPE = {
    "long_run": "long_run",
    "quality": "quality",
    "easy": "easy",
    "strength": "strength",
    "test": "test",
}


@dataclass(frozen=True)
class PlanInput:
    plan_type: PlanType
    parameters: Mapping[str, Any]
    goal: GoalSpec
    start: date
    availability: Mapping[int, DayAvailability]
    reference_values: ReferenceValues
    history: TrainingHistory
    supplementary: tuple[str, ...] = ()


def generate(inp: PlanInput) -> PlanOutput:
    params = {**inp.plan_type.parameters, **dict(inp.parameters)}
    zones = _zone_table(inp)
    warnings: list[Verstoss] = []
    explain: list[str] = []
    weeks = _weeks(inp, params, zones, warnings, explain)
    phases = _phases(inp, weeks)

    detail_count = int(params.get("detail_wochen", 2))
    blocks: list[BlockDraft] = []
    for week in weeks[:detail_count]:
        blocks += _week_blocks(inp, params, zones, week, blocks, warnings)

    violations = validate(PlanView(blocks, weeks, inp.history), inp.plan_type)
    for violation in violations:
        if violation.blocking:
            # generator already sizes against guard rails; a leftover removes the session
            blocks = [b for b in blocks if b.day != violation.day or b.workout_type == "rest"]
            warnings.append(
                replace(violation, art="hinweis", detail=f"entfernt: {violation.detail}")
            )
        else:
            warnings.append(violation)

    detail_until = (
        weeks[min(detail_count, len(weeks)) - 1].start + timedelta(days=6) if weeks else None
    )
    return PlanOutput(phases, weeks, blocks, warnings, explain, detail_until)


# --- zones ------------------------------------------------------------------------------


def _zone_table(inp: PlanInput) -> ZoneTable:
    by_unit: dict[str, Zonen] = {}
    for ref in inp.plan_type.head.zonen:
        regel = inp.plan_type.entries[ref].head.regel
        if isinstance(regel, Zonen):
            by_unit[regel.einheit] = regel
    refs = inp.reference_values
    return build_zone_table(
        vdot=refs.vdot,
        lthr=refs.lthr_laufen,
        hr_max=refs.hf_max,
        pace_zones=by_unit["prozent_vo2max"],
        lthr_zones=by_unit.get("prozent_lthr"),
        hrmax_zones=by_unit.get("prozent_hfmax"),
    )


def _pace(zones: ZoneTable, tempo: str | None) -> float:
    if tempo is None:
        return _FALLBACK_PACE["E"]
    return zones.pace(tempo) or _FALLBACK_PACE.get(tempo, _FALLBACK_PACE["E"])


# --- weeks and phases ---------------------------------------------------------------------


def _taper_days(params: Mapping[str, Any], goal: GoalSpec) -> int:
    table = params.get("taper_tage") or {}
    distance = goal.distance_m or 0.0
    if distance >= 40_000:
        return int(table.get("marathon", 21))
    if distance >= 20_000:
        return int(table.get("halbmarathon", 10))
    return int(table.get("kurz", 8))


def _phase_kinds(
    inp: PlanInput, params: Mapping[str, Any], warnings: list[Verstoss], explain: list[str]
) -> list[str]:
    first = week_start(inp.start)
    detail = int(params.get("detail_wochen", 2))
    goal = inp.goal
    if goal.kind != "wettkampf" or goal.race_date is None or goal.race_date < inp.start:
        # no race: one continuous phase with a weekly rhythm instead of periodisation
        explain.append("Kein Wettkampfziel: durchgehende Phase mit Wochenrhythmus.")
        return ["basis"] * max(detail + 6, 8)

    total = (week_start(goal.race_date) - first).days // 7 + 1
    taper_weeks = min(total, max(1, round(_taper_days(params, goal) / 7)))
    if total < MIN_PLAN_WEEKS:
        warnings.append(_hint(f"Nur {total} Woche(n) bis zum Ziel: nur Taper und Erhaltung."))
        return ["taper"] * total

    build = total - taper_weeks
    defs = inp.plan_type.phases().phasen
    alloc = [min(max(round(d.anteil * build), d.min_wochen), d.max_wochen) for d in defs]
    # too little time: shorten the base first, then the build phase (spec 6.3)
    order = list(range(len(defs)))
    while sum(alloc) > build:
        for i in order:
            if alloc[i] > 0 and sum(alloc) > build:
                alloc[i] -= 1
                break
    while sum(alloc) < build:
        grown = False
        for i in order:
            if alloc[i] < defs[i].max_wochen and sum(alloc) < build:
                alloc[i] += 1
                grown = True
        if not grown:
            alloc[0] += build - sum(alloc)
    if any(a < d.min_wochen for a, d in zip(alloc, defs, strict=True)):
        warnings.append(_hint("Zeit bis zum Ziel knapp: Basis bzw. Aufbau sind gekürzt."))
    kinds: list[str] = [d.art for d, a in zip(defs, alloc, strict=True) for _ in range(a)]
    explain.append(
        f"Phasen nach {inp.plan_type.entries[inp.plan_type.head.phasen].ref}: "
        + ", ".join(f"{d.art} {a} Wo." for d, a in zip(defs, alloc, strict=True) if a)
        + f", taper {taper_weeks} Wo."
    )
    return kinds + ["taper"] * taper_weeks


def _weeks(
    inp: PlanInput,
    params: Mapping[str, Any],
    zones: ZoneTable,
    warnings: list[Verstoss],
    explain: list[str],
) -> list[WeekPlan]:
    kinds = _phase_kinds(inp, params, warnings, explain)
    first = week_start(inp.start)
    history_weeks = inp.history.weekly_km(first, 4)
    active = [km for km in history_weeks if km > 0]
    start_km = sum(active) / len(active) if active else NO_HISTORY_START_KM
    if not active:
        warnings.append(_hint("Keine Laufdaten der letzten 4 Wochen: Start mit 10 km pro Woche."))
    else:
        explain.append(f"Startumfang {start_km:.0f} km/Woche aus dem Schnitt der letzten 4 Wochen.")

    minutes = sum(d.max_min for d in inp.availability.values())
    capacity_km = minutes * 60 / _pace(zones, "E") * PEAK_CAPACITY_SHARE
    zyklus = int(params.get("entlastung_zyklus", 4))
    deload_change = float(params.get("entlastung_umfang", -0.30))

    base = [km for km in inp.history.weekly_km(first, 3)]
    last_build = start_km
    peak = 0.0
    build_count = 0
    taper_total = kinds.count("taper")
    taper_index = 0
    out: list[WeekPlan] = []
    for i, kind in enumerate(kinds):
        monday = first + timedelta(weeks=i)
        if kind == "taper":
            # a plan that is all taper reduces from what the user can run now
            peak = peak or min(start_km, capacity_km)
            change = -0.45 if taper_total == 1 else -0.30 - 0.30 * taper_index / (taper_total - 1)
            taper_index += 1
            out.append(WeekPlan(monday, kind, round(peak * (1 + change), 1), taper=True))
            continue
        build_count += 1
        if build_count % zyklus == 0:
            out.append(
                WeekPlan(monday, kind, round(last_build * (1 + deload_change), 1), deload=True)
            )
            continue
        recent = [km for km in base if km > 0][-3:]
        cap_growth = (
            sum(recent) / len(recent) * 1.10 * 0.99 if recent else last_build * WEEKLY_GROWTH
        )
        volume = min(last_build * WEEKLY_GROWTH, cap_growth, capacity_km)
        volume = max(volume, min(start_km, capacity_km) * 0.5)
        last_build = volume
        peak = max(peak, volume)
        base.append(volume)
        out.append(WeekPlan(monday, kind, round(volume, 1)))
    return out


def _phases(inp: PlanInput, weeks: Sequence[WeekPlan]) -> list[PhaseDraft]:
    defs = {d.art: d for d in inp.plan_type.phases().phasen}
    phase_ref = inp.plan_type.entries[inp.plan_type.head.phasen].ref
    taper_ref = next(
        (e.ref for e in inp.plan_type.rule_entries() if isinstance(e.head.regel, Taper)), None
    )
    out: list[PhaseDraft] = []
    i = 0
    while i < len(weeks):
        j = i
        while j + 1 < len(weeks) and weeks[j + 1].phase == weeks[i].phase:
            j += 1
        kind = weeks[i].phase
        volumes = [w.volume_km for w in weeks[i : j + 1]]
        focus = defs[kind].schwerpunkt if kind in defs else "Umfang senken, Intensität halten"
        refs = (phase_ref,) if kind != "taper" or taper_ref is None else (phase_ref, taper_ref)
        out.append(
            PhaseDraft(
                kind=kind,
                start=weeks[i].start,
                end=weeks[j].start + timedelta(days=6),
                focus=focus,
                volume_min_km=min(volumes),
                volume_max_km=max(volumes),
                rule_refs=refs,
            )
        )
        i = j + 1
    return out


# --- single sessions ----------------------------------------------------------------------


def _week_blocks(
    inp: PlanInput,
    params: Mapping[str, Any],
    zones: ZoneTable,
    week: WeekPlan,
    prior: Sequence[BlockDraft],
    warnings: list[Verstoss],
) -> list[BlockDraft]:
    days = [week.start + timedelta(days=i) for i in range(7)]
    days = [d for d in days if d >= inp.start]
    avail = {
        d: inp.availability[d.weekday()] for d in days if inp.availability[d.weekday()].max_min > 0
    }
    if not avail:
        warnings.append(
            _hint(f"Woche ab {week.start:%d.%m.}: keine verfügbaren Tage.", week=week.start)
        )
        return []
    race_week = (
        inp.goal.race_date is not None
        and week.start <= inp.goal.race_date <= week.start + timedelta(days=6)
    )
    volume_m = week.volume_km * 1000
    units = inp.plan_type.units()

    long_day = None if race_week else max(avail, key=lambda d: (avail[d].max_min, d))
    quality_units = _quality_units(inp, params, week, prior)
    candidates = [
        d for d in avail if avail[d].quality and d != long_day and d - timedelta(days=1) != long_day
    ]
    test_day = None
    if quality_units and quality_units[0] == "lauf.einheit.test-10km" and candidates:
        # a test needs the most time of all quality sessions
        test_day = max(candidates, key=lambda d: (avail[d].max_min, -d.toordinal()))
        candidates = [d for d in candidates if abs((d - test_day).days) >= 2]
    quality_days = _pick_spaced(
        candidates,
        len(quality_units) - (1 if test_day else 0),
        avoid=[long_day] if long_day else [],
    )
    if test_day is not None:
        quality_days = [test_day, *quality_days]
    if len(quality_days) < len(quality_units):
        warnings.append(
            _hint(
                f"Woche ab {week.start:%d.%m.}: nur {len(quality_days)} von {len(quality_units)} "
                "Qualitätseinheiten passen in die Tage mit „Qualität möglich“ (48 h Abstand).",
                week=week.start,
            )
        )
        quality_units = quality_units[: len(quality_days)]
    hard_days = [*quality_days, *([long_day] if long_day else [])]

    strength_days: list[date] = []
    if "kraft" in inp.supplementary and "kraft.schwere-last" in units:
        per_phase = params.get("kraft_pro_woche") or {}
        wanted = int(per_phase.get(week.phase, 0))
        strength_candidates = [
            d
            for d in avail
            if d not in hard_days
            and d + timedelta(days=1) not in hard_days
            and avail[d].max_min * 60 >= STRENGTH_S
        ]
        strength_days = _pick_spaced(strength_candidates, wanted, avoid=[])

    rest_needed = int(params.get("ruhetage_min", 1))
    free_days = [d for d in days if d not in avail]
    easy_candidates = [d for d in avail if d not in hard_days]
    while len(free_days) < rest_needed and easy_candidates:
        # keep the least available plain day free
        spare = min(
            (d for d in easy_candidates if d not in strength_days),
            key=lambda d: (avail[d].max_min, -d.toordinal()),
            default=None,
        )
        if spare is None:
            break
        easy_candidates.remove(spare)
        free_days.append(spare)

    blocks: list[BlockDraft] = []
    planned = list(prior)

    def guard(day: date) -> float:
        reference = max(
            [inp.history.longest_run_m(day, 30)]
            + [
                b.distance_m or 0.0
                for b in planned
                if b.is_run and day - timedelta(days=30) <= b.day < day
            ]
        )
        return _single_run_factor(inp.plan_type) * (
            reference or NO_REFERENCE_LONGEST_M / _single_run_factor(inp.plan_type)
        )

    def add(block: BlockDraft | None) -> None:
        if block is not None:
            blocks.append(block)
            planned.append(block)

    for day, unit_id in zip(quality_days, quality_units, strict=False):
        add(
            _quality_block(
                inp, zones, units[unit_id], day, avail[day], volume_m, week, guard(day), warnings
            )
        )

    if long_day is not None:
        easy_pace = _pace(zones, "E")
        lr_entry = units["lauf.einheit.long-run"]
        lr = lr_entry.head.regel
        assert isinstance(lr, Einheit)
        max_s = min(lr.dauer_s.max if lr.dauer_s else 9000.0, avail[long_day].max_min * 60)
        distance = min(LONG_RUN_SHARE * volume_m, max_s / easy_pace * 1000, guard(long_day))
        if distance >= MIN_LONG_RUN_M:
            add(_continuous_block(inp, zones, lr_entry, long_day, avail[long_day], distance, week))
        else:
            easy_candidates.append(long_day)

    for day in strength_days:
        add(_strength_block(inp, zones, units["kraft.schwere-last"], day, avail[day], week))

    run_m = sum(b.distance_m or 0.0 for b in blocks if b.is_run)
    remaining = volume_m - run_m
    easy_days = sorted(d for d in easy_candidates if d not in free_days and d not in quality_days)
    easy_entry = units["lauf.einheit.locker"]
    easy_pace = _pace(zones, "E")
    min_m = EASY_MIN_S / easy_pace * 1000
    while easy_days and remaining / len(easy_days) < min_m:
        easy_days.pop(min(range(len(easy_days)), key=lambda k: avail[easy_days[k]].max_min))
    for day in easy_days:
        left = len(easy_days) - easy_days.index(day)
        strength_s = sum(b.duration_s for b in blocks if b.day == day and not b.is_run)
        day_s = avail[day].max_min * 60 - strength_s
        if day_s < EASY_MIN_S:
            continue
        distance = min(
            remaining / left, day_s / easy_pace * 1000, 5400 / easy_pace * 1000, guard(day)
        )
        if distance < min_m:
            continue
        add(_continuous_block(inp, zones, easy_entry, day, avail[day], distance, week))
        remaining -= distance

    _hold_z1_share(blocks, zones, week, warnings)
    return sorted(blocks, key=lambda b: (b.day, b.workout_type != "strength"))


def _single_run_factor(plan_type: PlanType) -> float:
    for entry in plan_type.rule_entries():
        regel = entry.head.regel
        if isinstance(regel, ObergrenzeRelativ) and regel.groesse == "lauf.distanz_m":
            return regel.faktor
    return 1.10


def _quality_units(
    inp: PlanInput, params: Mapping[str, Any], week: WeekPlan, prior: Sequence[BlockDraft]
) -> list[str]:
    count = int(params.get("qualitaet_pro_woche", 2))
    if week.phase == "taper":
        count = 1
    defs = {d.art: d for d in inp.plan_type.phases().phasen}
    # the taper keeps one short threshold session
    pool = list(defs[week.phase].qualitaet) if week.phase in defs else ["lauf.einheit.schwelle"]
    if inp.goal.distance_m is not None and inp.goal.distance_m < 20_000:
        pool = [u for u in pool if u != "lauf.einheit.marathontempo"] or pool
    # rotate through the pool week by week, so a single slot does not repeat one unit
    offset = (week.start.toordinal() // 7) % len(pool)
    chosen = [pool[(offset + i) % len(pool)] for i in range(count)]
    refs = inp.reference_values
    stale = refs.vdot is None or (
        refs.vdot_measured_on is not None
        and (week.start - refs.vdot_measured_on).days > REFERENCE_STALE_DAYS
    )
    already = any(b.unit_id == "lauf.einheit.test-10km" for b in prior)
    if (
        stale
        and not already
        and week.phase != "taper"
        and "lauf.einheit.test-10km" in inp.plan_type.head.einheiten
    ):
        chosen = ["lauf.einheit.test-10km", *chosen[: max(count - 1, 0)]]
    if refs.vdot is None:
        # without VDOT there are no paces for quality work yet
        chosen = [u for u in chosen if u == "lauf.einheit.test-10km"]
    return chosen


def _pick_spaced(candidates: Sequence[date], count: int, avoid: Sequence[date]) -> list[date]:
    picked: list[date] = []
    preferred = sorted(
        candidates,
        key=lambda d: (any(abs((d - a).days) <= 1 for a in avoid if a), d),
    )
    for day in preferred:
        if len(picked) >= count:
            break
        if all(abs((day - p).days) >= 2 for p in picked):
            picked.append(day)
    return sorted(picked)


def _materialize(
    steps: Sequence[Schritt], zones: ZoneTable, variable_m: float | None
) -> list[StepDraft]:
    out: list[StepDraft] = []
    for step in steps:
        if step.typ == "wiederholung":
            out.append(
                StepDraft(
                    typ=step.typ,
                    tempo=None,
                    duration_s=None,
                    distance_m=None,
                    repeat=step.wiederholungen,
                    steps=_materialize(step.schritte or [], zones, None),
                    note=step.notiz,
                )
            )
            continue
        pace = _pace(zones, step.tempo)
        if step.variabel:
            distance = variable_m or 0.0
            duration = distance / 1000 * pace
        elif step.distanz_m is not None:
            distance = step.distanz_m
            duration = distance / 1000 * pace
        else:
            duration = step.dauer_s or 0.0
            distance = duration / pace * 1000 if step.tempo else 0.0
        target = zones.targets.get(step.tempo or "")
        out.append(
            StepDraft(
                typ=step.typ,
                tempo=step.tempo,
                duration_s=duration,
                distance_m=distance if step.tempo else None,
                pace=target.pace if target else None,
                hr=target.hr if target else None,
                note=step.notiz,
            )
        )
    return out


@dataclass
class _Totals:
    duration_s: float = 0.0
    distance_m: float = 0.0
    main_m: float = 0.0


def _totals(
    steps: Sequence[StepDraft], zones: ZoneTable, main_tempo: str | None
) -> tuple[_Totals, dict[str, float]]:
    totals = _Totals()
    zone_s = {"z1": 0.0, "z2": 0.0, "z3": 0.0}

    def walk(items: Sequence[StepDraft], factor: int) -> None:
        for s in items:
            if s.steps:
                walk(s.steps, factor * (s.repeat or 1))
                continue
            totals.duration_s += (s.duration_s or 0.0) * factor
            totals.distance_m += (s.distance_m or 0.0) * factor
            if s.tempo:
                zone_s[zones.zone3(s.tempo)] += (s.duration_s or 0.0) * factor
            if main_tempo is not None and s.tempo == main_tempo and s.typ == "belastung":
                totals.main_m += (s.distance_m or 0.0) * factor

    walk(steps, 1)
    return totals, zone_s


def _main_tempo(unit: Einheit) -> str | None:
    def find(steps: Sequence[Schritt]) -> str | None:
        for s in steps:
            if s.typ == "wiederholung":
                hit = find(s.schritte or [])
                if hit:
                    return hit
            elif s.typ == "belastung":
                return s.tempo
        return None

    return find(unit.struktur)


def _block(
    entry: Entry,
    unit: Einheit,
    day: date,
    availability: DayAvailability,
    steps: list[StepDraft],
    zones: ZoneTable,
    week: WeekPlan,
    phase_ref: str,
) -> BlockDraft:
    main_tempo = _main_tempo(unit)
    totals, zone_s = _totals(steps, zones, main_tempo)
    is_run = unit.sport == RUN_SPORT
    main = totals.distance_m if unit.klasse in ("long_run", "easy") else totals.main_m
    return BlockDraft(
        day=day,
        sport=unit.sport,
        unit_id=entry.id,
        unit_ref=entry.ref,
        workout_type=_KLASSE_TO_WORKOUT_TYPE[unit.klasse],
        duration_s=round(totals.duration_s),
        distance_m=round(totals.distance_m) if is_run else None,
        zone_s=zone_s if is_run else {"z1": 0.0, "z2": 0.0, "z3": 0.0},
        main_distance_m=main,
        steps=steps,
        rule_refs=[entry.ref, phase_ref],
        phase=week.phase,
        start_time=availability.time,
    )


def _phase_ref(inp: PlanInput) -> str:
    return inp.plan_type.entries[inp.plan_type.head.phasen].ref


def _continuous_block(
    inp: PlanInput,
    zones: ZoneTable,
    entry: Entry,
    day: date,
    availability: DayAvailability,
    distance_m: float,
    week: WeekPlan,
) -> BlockDraft:
    unit = entry.head.regel
    assert isinstance(unit, Einheit)
    steps = _materialize(unit.struktur, zones, distance_m)
    return _block(entry, unit, day, availability, steps, zones, week, _phase_ref(inp))


def _strength_block(
    inp: PlanInput,
    zones: ZoneTable,
    entry: Entry,
    day: date,
    availability: DayAvailability,
    week: WeekPlan,
) -> BlockDraft:
    unit = entry.head.regel
    assert isinstance(unit, Einheit)
    steps = _materialize(unit.struktur, zones, None)
    return _block(entry, unit, day, availability, steps, zones, week, _phase_ref(inp))


def _quality_block(
    inp: PlanInput,
    zones: ZoneTable,
    entry: Entry,
    day: date,
    availability: DayAvailability,
    volume_m: float,
    week: WeekPlan,
    guard_m: float,
    warnings: list[Verstoss],
) -> BlockDraft | None:
    unit = entry.head.regel
    assert isinstance(unit, Einheit)
    limit_m = (unit.anteil_max_woche or 1.0) * volume_m
    day_s = availability.max_min * 60
    variable_m = None
    if any(s.variabel for s in unit.struktur):
        main_pace = _pace(zones, _main_tempo(unit))
        variable_m = min(MARATHON_PACE_SHARE * volume_m, limit_m)
        fixed_s = sum(s.dauer_s or 0.0 for s in unit.struktur if not s.variabel)
        variable_m = min(variable_m, max(day_s - fixed_s, 0.0) / main_pace * 1000)
    template = list(unit.struktur)
    steps = _materialize(template, zones, variable_m)
    block = _block(entry, unit, day, availability, steps, zones, week, _phase_ref(inp))
    group = next((s for s in steps if s.steps), None)
    # shrink the repeat group until the unit fits its weekly share, the day and the guard rail
    while (
        group is not None
        and (group.repeat or 1) > 1
        and (
            block.main_distance_m > limit_m
            or block.duration_s > day_s
            or (block.distance_m or 0) > guard_m
        )
    ):
        group.repeat = (group.repeat or 1) - 1
        block = _block(entry, unit, day, availability, steps, zones, week, _phase_ref(inp))
    if unit.klasse != "test" and (block.main_distance_m > limit_m + 50 or block.duration_s > day_s):
        warnings.append(
            _hint(
                f"{day:%d.%m.}: {entry.head.titel} passt nicht in den Wochenumfang bzw. den Tag "
                "und entfällt.",
                day=day,
            )
        )
        return None
    if unit.klasse == "test" and block.duration_s > day_s:
        warnings.append(_hint(f"{day:%d.%m.}: zu wenig Zeit für den Test.", day=day))
        return None
    if (block.distance_m or 0) > guard_m + 50:
        # the single-run guard rail stays; a leftover violation drops the session (spec 6.4)
        warnings.append(
            _hint(
                f"{day:%d.%m.}: {entry.head.titel} wäre länger als 110 % des längsten Laufs der "
                "letzten 30 Tage und entfällt.",
                day=day,
            )
        )
        return None
    return block


def _hold_z1_share(
    blocks: list[BlockDraft], zones: ZoneTable, week: WeekPlan, warnings: list[Verstoss]
) -> None:
    runs = [b for b in blocks if b.is_run]
    if len(runs) < 3:
        return

    def share() -> float:
        total = sum(sum(b.zone_s.values()) for b in runs)
        return sum(b.zone_s["z1"] for b in runs) / total if total else 1.0

    while share() < Z1_TARGET:
        candidates = [
            b
            for b in runs
            if b.workout_type == "quality" and any(s.steps and (s.repeat or 1) > 1 for s in b.steps)
        ]
        if not candidates:
            warnings.append(
                _hint(f"Woche ab {week.start:%d.%m.}: Z1-Anteil knapp.", week=week.start)
            )
            return
        target = max(candidates, key=lambda b: b.zone_s["z2"] + b.zone_s["z3"])
        group = next(s for s in target.steps if s.steps and (s.repeat or 1) > 1)
        group.repeat = (group.repeat or 1) - 1
        unit_steps = target.steps
        totals, zone_s = _totals(unit_steps, zones, _main_tempo_from_steps(unit_steps))
        target.duration_s = round(totals.duration_s)
        target.distance_m = round(totals.distance_m)
        target.zone_s = zone_s
        target.main_distance_m = totals.main_m


def _main_tempo_from_steps(steps: Sequence[StepDraft]) -> str | None:
    for s in steps:
        if s.steps:
            hit = _main_tempo_from_steps(s.steps)
            if hit:
                return hit
        elif s.typ == "belastung":
            return s.tempo
    return None


def _hint(text: str, *, day: date | None = None, week: date | None = None) -> Verstoss:
    return Verstoss(rule_ref="", art="hinweis", message=text, detail=text, day=day, week=week)
