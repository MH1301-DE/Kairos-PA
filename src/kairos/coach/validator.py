"""Checks a plan against the rules of its plan type (coach spec 6.5).

Pure function, no database. Guard rails (``art: leitplanke``) produce blocking violations;
the generator resolves them by shortening, ``plan_adjust`` refuses them unless the user
overrides with a reason (S3).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from kairos.coach.knowledge import Entry, PlanType
from kairos.coach.model import BlockDraft, TrainingHistory, Verstoss, WeekPlan, week_start
from kairos.coach.rules import (
    AbstandMin,
    AnteilMax,
    AnteilMin,
    Einheit,
    Haeufigkeit,
    ObergrenzeAbsolut,
    ObergrenzeRelativ,
    Rhythmus,
    Taper,
    ZuwachsMax,
)

# a week needs this many runs before its intensity split says anything
MIN_RUNS_FOR_SHARE = 3
_TOLERANCE_M = 50.0


@dataclass(frozen=True)
class PlanView:
    blocks: Sequence[BlockDraft]
    weeks: Sequence[WeekPlan]
    history: TrainingHistory


def validate(view: PlanView, plan_type: PlanType) -> list[Verstoss]:
    out: list[Verstoss] = []
    for entry in plan_type.rule_entries():
        out.extend(check_entry(entry, view))
    return out


def check_entry(entry: Entry, view: PlanView) -> list[Verstoss]:
    regel = entry.head.regel
    if isinstance(regel, AnteilMin | AnteilMax):
        return _share(entry, regel, view)
    if isinstance(regel, ObergrenzeRelativ):
        return _single_run(entry, regel, view)
    if isinstance(regel, ObergrenzeAbsolut):
        return _absolute(entry, regel, view)
    if isinstance(regel, ZuwachsMax):
        return _weekly_increase(entry, regel, view)
    if isinstance(regel, Rhythmus):
        return _deload(entry, regel, view)
    if isinstance(regel, Haeufigkeit):
        return _frequency(entry, regel, view)
    if isinstance(regel, Einheit):
        return _unit_limits(entry, regel, view)
    if isinstance(regel, AbstandMin):
        return _spacing(entry, regel, view)
    if isinstance(regel, Taper):
        return _taper(entry, regel, view)
    return []


def _v(entry: Entry, detail: str, **kw: object) -> Verstoss:
    art = "leitplanke" if entry.head.art == "leitplanke" else "regel"
    return Verstoss(
        rule_ref=entry.ref,
        art=art,
        message=entry.user_text,
        detail=detail,
        evidenz=entry.head.evidenz,
        **kw,  # type: ignore[arg-type]
    )


def _runs(blocks: Iterable[BlockDraft]) -> list[BlockDraft]:
    return sorted((b for b in blocks if b.is_run and b.distance_m), key=lambda b: b.day)


def _by_week(blocks: Iterable[BlockDraft]) -> dict[date, list[BlockDraft]]:
    weeks: dict[date, list[BlockDraft]] = defaultdict(list)
    for block in blocks:
        weeks[week_start(block.day)].append(block)
    return dict(sorted(weeks.items()))


def _share(entry: Entry, regel: AnteilMin | AnteilMax, view: PlanView) -> list[Verstoss]:
    zone = regel.groesse.split(".", 1)[1]
    out = []
    for monday, blocks in _by_week(_runs(view.blocks)).items():
        if len(blocks) < MIN_RUNS_FOR_SHARE:
            continue
        total = sum(sum(b.zone_s.values()) for b in blocks)
        if total <= 0:
            continue
        share = sum(b.zone_s.get(zone, 0.0) for b in blocks) / total
        bad = share < regel.wert if isinstance(regel, AnteilMin) else share > regel.wert
        if bad:
            out.append(
                _v(
                    entry,
                    f"Woche ab {monday:%d.%m.}: {zone.upper()}-Anteil {share:.0%}, "
                    f"Grenze {regel.wert:.0%}",
                    ist=round(share, 3),
                    grenze=regel.wert,
                    week=monday,
                )
            )
    return out


def _single_run(entry: Entry, regel: ObergrenzeRelativ, view: PlanView) -> list[Verstoss]:
    out = []
    planned = _runs(view.blocks)
    for block in planned:
        start = block.day - timedelta(days=regel.bezug.fenster_tage)
        earlier = [b.distance_m or 0.0 for b in planned if start <= b.day < block.day]
        reference = max([view.history.longest_run_m(block.day, regel.bezug.fenster_tage), *earlier])
        # after a break there is no reference; the generator then starts from short runs
        if reference <= 0:
            continue
        limit = reference * regel.faktor
        distance = block.distance_m or 0.0
        if distance > limit + _TOLERANCE_M:
            out.append(
                _v(
                    entry,
                    f"{block.day:%d.%m.}: {distance / 1000:.1f} km, längster Lauf der "
                    f"letzten {regel.bezug.fenster_tage} Tage {reference / 1000:.1f} km, "
                    f"Grenze {limit / 1000:.1f} km",
                    ist=round(distance / 1000, 2),
                    grenze=round(limit / 1000, 2),
                    day=block.day,
                )
            )
    return out


def _absolute(entry: Entry, regel: ObergrenzeAbsolut, view: PlanView) -> list[Verstoss]:
    if regel.groesse != "lauf.dauer_s":
        return []
    return [
        _v(
            entry,
            f"{b.day:%d.%m.}: {b.duration_s / 60:.0f} min",
            ist=b.duration_s,
            grenze=regel.wert,
            day=b.day,
        )
        for b in _runs(view.blocks)
        if b.duration_s > regel.wert + 60
    ]


def _week_volumes(view: PlanView, n: int) -> list[tuple[date, float, bool, bool]]:
    """(monday, km, deload, from_plan) for n history weeks plus all plan weeks."""
    if not view.weeks:
        return []
    first = view.weeks[0].start
    history = view.history.weekly_km(first, n)
    detail = {
        m: sum((b.distance_m or 0.0) for b in bs) / 1000
        for m, bs in _by_week(_runs(view.blocks)).items()
    }
    rows = [(first - timedelta(weeks=n - i), km, False, False) for i, km in enumerate(history)]
    rows += [
        (w.start, detail.get(w.start, w.volume_km), w.deload or w.taper, True) for w in view.weeks
    ]
    return rows


def _weekly_increase(entry: Entry, regel: ZuwachsMax, view: PlanView) -> list[Verstoss]:
    n = regel.n if regel.vergleich == "schnitt_n_wochen" else 1
    rows = _week_volumes(view, n)
    out = []
    for i, (monday, km, reduced, from_plan) in enumerate(rows):
        if not from_plan or reduced:
            continue
        # deload and taper weeks do not lower the base (knowledge entry "Wann nicht")
        base_weeks = [r[1] for r in rows[:i] if not r[2] and r[1] > 0][-n:]
        if len(base_weeks) < n:
            continue
        base = sum(base_weeks) / len(base_weeks)
        if km > base * regel.faktor + 0.5:
            out.append(
                _v(
                    entry,
                    f"Woche ab {monday:%d.%m.}: {km:.1f} km, Schnitt davor {base:.1f} km",
                    ist=round(km, 1),
                    grenze=round(base * regel.faktor, 1),
                    week=monday,
                )
            )
    return out


def _deload(entry: Entry, regel: Rhythmus, view: PlanView) -> list[Verstoss]:
    out = []
    streak = 0
    for week in view.weeks:
        if week.taper or week.deload:
            streak = 0
            continue
        streak += 1
        if streak >= regel.zyklus:
            out.append(
                _v(
                    entry,
                    f"Woche ab {week.start:%d.%m.}: {streak} Belastungswochen ohne Entlastung",
                    week=week.start,
                )
            )
            streak = 0
    return out


def _frequency(entry: Entry, regel: Haeufigkeit, view: PlanView) -> list[Verstoss]:
    out = []
    for monday, blocks in _by_week(view.blocks).items():
        phases = {b.phase for b in blocks}
        if regel.phasen and not phases & set(regel.phasen):
            continue
        count = sum(1 for b in blocks if b.unit_id in regel.einheiten)
        if count > regel.max or count < regel.min:
            out.append(
                _v(
                    entry,
                    f"Woche ab {monday:%d.%m.}: {count} Einheiten",
                    ist=count,
                    grenze=regel.max,
                    week=monday,
                )
            )
    return out


def _unit_limits(entry: Entry, regel: Einheit, view: PlanView) -> list[Verstoss]:
    out = []
    weekly = {
        m: sum((b.distance_m or 0.0) for b in bs) for m, bs in _by_week(_runs(view.blocks)).items()
    }
    for block in view.blocks:
        if block.unit_id != entry.id:
            continue
        if regel.dauer_s is not None and block.duration_s > regel.dauer_s.max + 60:
            out.append(
                _v(
                    entry,
                    f"{block.day:%d.%m.}: {block.duration_s / 60:.0f} min, höchstens "
                    f"{regel.dauer_s.max / 60:.0f} min",
                    ist=block.duration_s,
                    grenze=regel.dauer_s.max,
                    day=block.day,
                )
            )
        if regel.anteil_max_woche is not None:
            week_m = weekly.get(week_start(block.day), 0.0)
            limit = regel.anteil_max_woche * week_m
            if week_m > 0 and block.main_distance_m > limit + _TOLERANCE_M:
                out.append(
                    _v(
                        entry,
                        f"{block.day:%d.%m.}: {block.main_distance_m / 1000:.1f} km von "
                        f"{week_m / 1000:.1f} km Wochenumfang",
                        ist=round(block.main_distance_m),
                        grenze=round(limit),
                        day=block.day,
                    )
                )
    return out


def _spacing(entry: Entry, regel: AbstandMin, view: PlanView) -> list[Verstoss]:
    out = []
    by_day: dict[date, list[BlockDraft]] = defaultdict(list)
    for block in view.blocks:
        by_day[block.day].append(block)
    for day, blocks in by_day.items():
        firsts = [b for b in blocks if b.unit_id in regel.von]
        seconds = [b for b in blocks if b.unit_id in regel.zu]
        for a in firsts:
            for b in seconds:
                if _gap_hours(a, b) < regel.stunden:
                    out.append(
                        _v(
                            entry,
                            f"{day:%d.%m.}: {a.unit_id} und {b.unit_id} am selben Tag",
                            day=day,
                        )
                    )
    return out


def _gap_hours(a: BlockDraft, b: BlockDraft) -> float:
    # without planned times two sessions on one day count as back to back
    if not a.start_time or not b.start_time:
        return 0.0
    first, second = sorted((a, b), key=lambda x: _minutes(x.start_time or "00:00"))
    end_first = _minutes(first.start_time or "00:00") + first.duration_s / 60
    return (_minutes(second.start_time or "00:00") - end_first) / 60


def _minutes(hhmm: str) -> int:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return hours * 60 + minutes


def _taper(entry: Entry, regel: Taper, view: PlanView) -> list[Verstoss]:
    taper = [w for w in view.weeks if w.taper]
    before = [w.volume_km for w in view.weeks if not w.taper and not w.deload]
    if not taper or not before:
        return []
    base = sum(before[-3:]) / len(before[-3:])
    if base <= 0:
        return []
    change = sum(w.volume_km for w in taper) / len(taper) / base - 1
    if change < regel.umfang_aenderung.min - 0.02 or change > regel.umfang_aenderung.max + 0.02:
        return [
            _v(
                entry,
                f"Taper: Umfang im Schnitt {change:+.0%} gegenüber den Wochen davor",
                ist=round(change, 3),
                grenze=regel.umfang_aenderung.max,
                week=taper[0].start,
            )
        ]
    return []
