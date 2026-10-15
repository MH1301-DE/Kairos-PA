"""V1–V7 (spec §12.3): compare the derived activity tables with Garmin's own values.

Usage: .venv/bin/python scripts/validate_activity_derivations.py --user-id <uuid> --out <file.md>
Read-only: SELECTs on the derived tables, the activity_list archive and the FIT archive.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import math
import statistics
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive import best_efforts as be
from kairos.activities.derive.common import (
    Prepared,
    _rolling_median,
    elevation_gain_loss,
    interp,
    pause_intervals,
    prepare,
)
from kairos.activities.fit_archive import load_fit_messages
from kairos.activities.stream_repository import load_stream
from kairos.db.models import Activity
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory

# Garmin PRs as of 2026-10-07 (spec §12.3, typeId 3 and 4)
PR_S = {"5k": 1325.4, "10k": 2710.2}
V7_CORE = (272, 402, 250)
MIN_LAP_S = 5.0

Row = dict[str, Any]


def tol(reference: float) -> float:
    return max(2.0, 0.01 * reference)


def fmt(v: float | None, nd: int = 1) -> str:
    return "–" if v is None else f"{v:.{nd}f}"


def pct(n: int, d: int) -> str:
    return "–" if d == 0 else f"{n}/{d} = {100.0 * n / d:.1f} %"


def yes(ok: bool) -> str:
    return "ja" if ok else "nein"


def num(v: object) -> float | None:
    return None if isinstance(v, bool) or not isinstance(v, int | float) else float(v)


def offset(value: object, start_at: datetime) -> float | None:
    if not isinstance(value, datetime):
        return None
    ts = value if value.tzinfo else value.replace(tzinfo=UTC)
    return (ts - start_at).total_seconds()


@dataclass
class Fit:
    prep: Prepared | None
    start_at: datetime | None
    laps: list[Row]
    workout_steps: list[Row]
    is_workout: bool
    total_ascent: float | None
    raw_alt: list[float | None]
    pauses: list[tuple[float, float]]
    jumps: int

    def lap_window(self, lap: Row) -> tuple[float, float] | None:
        a = None if self.start_at is None else offset(lap.get("start_time"), self.start_at)
        elapsed = num(lap.get("total_elapsed_time"))
        return None if a is None or elapsed is None else (a, a + elapsed)

    def stops_in(self, a: float, b: float) -> int:
        return sum(1 for s, _ in self.pauses if a <= s < b)


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)

    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        cells = [h.replace("|", "\\|") for h in header]
        self.add("| " + " | ".join(cells) + " |", "|" + "---|" * len(header))
        self.add(*("| " + " | ".join(r) + " |" for r in rows))
        self.add("")


async def garmin_items(session: AsyncSession) -> dict[str, Row]:
    rows = await session.execute(
        text(
            "SELECT payload_gzip FROM raw_payload WHERE connector = 'garmin' "
            "AND kind = 'activity_list' AND payload_gzip IS NOT NULL ORDER BY fetched_at, id"
        )
    )
    items: dict[str, Row] = {}
    for (blob,) in rows.all():
        data = json.loads(gzip.decompress(blob))
        if isinstance(data, list):
            # later fetches win: they carry Garmin-side edits
            items.update({str(it["activityId"]): it for it in data if "activityId" in it})
    return items


async def table_rows(session: AsyncSession, table: str, uid: uuid.UUID) -> list[Row]:
    result = await session.execute(
        text(f"SELECT * FROM {table} WHERE user_id = :u"), {"u": str(uid)}
    )
    return [dict(r._mapping) for r in result.all()]


def count_jumps(prep: Prepared) -> int:
    pts = [(t, d) for t, d in zip(prep.t, prep.distance, strict=True) if d is not None]
    return sum(
        1
        for (t0, d0), (t1, d1) in zip(pts, pts[1:], strict=False)
        if d1 > d0 and (t1 <= t0 or (d1 - d0) / (t1 - t0) > be.BEST_EFFORT_MAX_STEP_SPEED_MPS)
    )


async def load_fit(session: AsyncSession, activity: Activity) -> Fit:
    stream = await load_stream(session, activity_id=activity.id)
    loaded = await load_fit_messages(session, activity=activity)
    msgs: dict[str, Any] = loaded[0] if loaded is not None else {}

    def m(key: str) -> list[Row]:
        return list(msgs.get(key) or [])

    sessions = m("session_mesgs")
    ascent = num(sessions[0].get("total_ascent")) if sessions else None
    events = m("event_mesgs")
    prep = pauses = None
    if stream is not None:
        prep = prepare(stream, sport_profile=activity.sport_profile, events=events)
        pauses = pause_intervals(prep.t, prep.distance, events, start_at=stream.start_at)
    return Fit(
        prep=prep,
        start_at=None if stream is None else stream.start_at,
        laps=m("lap_mesgs"),
        workout_steps=m("workout_step_mesgs"),
        is_workout=bool(m("workout_mesgs")),
        total_ascent=ascent,
        raw_alt=[] if stream is None else list(stream.channels.get("altitude_m") or []),
        pauses=pauses or [],
        jumps=0 if prep is None else count_jumps(prep),
    )


def v1(rep: Report, runs: Sequence[Activity], fits: Mapping[int, Fit], splits: list[Row]) -> None:
    by_act: dict[int, dict[int, Row]] = {}
    for s in splits:
        if s["kind"] == "distance" and not s["is_partial"]:
            by_act.setdefault(s["activity_id"], {})[s["idx"]] = s
    pairs: list[tuple[int, int, float, float, Fit, Row]] = []
    for a in runs:
        fit = fits[a.id]
        # leading 1 km auto-laps start at the km marks of our splits
        for i, lap in enumerate(fit.laps, start=1):
            dist = num(lap.get("total_distance"))
            if lap.get("lap_trigger") != "distance" or dist is None or abs(dist - 1000) > 0.5:
                break
            ours = by_act.get(a.id, {}).get(i)
            watch = num(lap.get("total_timer_time"))
            if ours is None or watch is None or ours["timer_s"] is None:
                break
            pairs.append((a.id, i, float(ours["timer_s"]), watch, fit, lap))
    devs = [abs(p[2] - p[3]) for p in pairs]
    ok = sum(1 for d in devs if d <= 1.0)
    rep.add("## V1 Km-Splits gegen Uhr-Runden", "")
    rep.table(
        [
            "Läufe",
            "Splits",
            "Quote |Δt| ≤ 1 s",
            "Kriterium",
            "erfüllt",
            "max |Δt| s",
            "Median |Δt| s",
        ],
        [
            [
                str(len({p[0] for p in pairs})),
                str(len(pairs)),
                pct(ok, len(pairs)),
                "≥ 95 %",
                yes(bool(pairs) and ok / len(pairs) >= 0.95),
                fmt(max(devs, default=None), 3),
                fmt(statistics.median(devs) if devs else None, 3),
            ]
        ],
    )
    out = []
    for aid, km, mine, watch, fit, lap in pairs:
        if abs(mine - watch) <= 1.0:
            continue
        win = fit.lap_window(lap)
        stops = 0 if win is None else fit.stops_in(*win)
        garmin_pause = (num(lap.get("total_elapsed_time")) or watch) - watch
        # where the stream distance stands when the watch closes the 1000 m lap
        end_d = (
            None
            if win is None or fit.prep is None
            else interp(fit.prep.t, fit.prep.distance, win[1])
        )
        start_d = (
            None
            if win is None or fit.prep is None
            else interp(fit.prep.t, fit.prep.distance, win[0])
        )
        out.append(
            [
                str(aid),
                str(km),
                fmt(mine, 2),
                fmt(watch, 2),
                fmt(mine - watch, 2),
                str(stops),
                fmt(garmin_pause, 2),
                fmt(start_d, 2),
                fmt(end_d, 2),
            ]
        )
    rep.add(f"Ausreißer ({len(out)}):", "")
    if out:
        rep.table(
            [
                "Aktivität",
                "km",
                "Split s",
                "Runde s",
                "Δ s",
                "Timer-Stopps in der Runde",
                "Pause laut Runde s",
                "Stream-Distanz bei Rundenstart m",
                "Stream-Distanz bei Rundenende m",
            ],
            out,
        )


def effort(
    prep: Prepared, source: str, target: float, *, elapsed: bool, jump_filter: bool
) -> float | None:
    p = replace(prep, timer_t=list(prep.t)) if elapsed else prep
    limit = be.BEST_EFFORT_MAX_STEP_SPEED_MPS if jump_filter else math.inf
    # 1 km is no stored key: same function with one target distance
    with (
        patch.dict(be.BEST_EFFORT_DISTANCES, {"x": target}, clear=True),
        patch.object(be, "BEST_EFFORT_MAX_STEP_SPEED_MPS", limit),
    ):
        rows = be.best_efforts(p, sport_profile="running", distance_source=source)
    return rows[0].duration_s if rows else None


def v2(
    rep: Report,
    runs: Sequence[Activity],
    fits: Mapping[int, Fit],
    efforts: list[Row],
    items: Mapping[str, Row],
    stats: Mapping[int, Row],
) -> None:
    stored = {(e["activity_id"], e["distance_key"]): float(e["duration_s"]) for e in efforts}
    rep.add("## V2 Best Effort 5 km / 1 km gegen fastestSplit", "")
    summary: list[list[str]] = []
    details: list[list[str]] = []
    skipped: list[list[str]] = []
    for key, target, gkey in (
        ("5k", 5000.0, "fastestSplit_5000"),
        ("1k", 1000.0, "fastestSplit_1000"),
    ):
        n = strict = elapsed_ok = all_ok = 0
        for a in runs:
            garmin = num(items[a.external_id].get(gkey))
            fit = fits[a.id]
            source = stats.get(a.id, {}).get("distance_source") or "none"
            if garmin is None:
                continue
            if source != "gps" or fit.prep is None:
                skipped.append(
                    [str(a.id), key, fmt(garmin), f"distance_source={source} (B.4: nur gps)"]
                )
                continue
            prep = fit.prep
            if key == "5k":
                mine = stored.get((a.id, key))
            else:
                mine = effort(prep, source, target, elapsed=False, jump_filter=True)
            n += 1
            if mine is not None and abs(mine - garmin) <= tol(garmin):
                strict += 1
                elapsed_ok += 1
                all_ok += 1
                continue
            el = effort(prep, source, target, elapsed=True, jump_filter=True)
            el_raw = effort(prep, source, target, elapsed=True, jump_filter=False)
            cause = "ungeklärt"
            if el is not None and abs(el - garmin) <= tol(garmin):
                elapsed_ok += 1
                all_ok += 1
                cause = "Timer-Stopp im Fenster; Garmin misst Gesamtzeit"
            elif el_raw is not None and abs(el_raw - garmin) <= tol(garmin):
                all_ok += 1
                cause = (
                    f"Sprungfilter verwirft die schnellen Fenster ({fit.jumps} Schritte > 8,5 m/s)"
                )
            details.append(
                [
                    str(a.id),
                    key,
                    fmt(mine),
                    fmt(garmin),
                    fmt(None if mine is None else mine - garmin),
                    fmt(el),
                    fmt(el_raw),
                    cause,
                ]
            )
        summary.append(
            [
                key,
                str(n),
                pct(strict, n),
                pct(elapsed_ok, n),
                pct(all_ok, n),
                "≥ 90 %",
                yes(bool(n) and strict / n >= 0.9),
            ]
        )
    rep.table(
        [
            "Distanz",
            "Läufe",
            "Quote strikt",
            "+ Gesamtzeit wie Garmin",
            "+ ohne Sprungfilter",
            "Kriterium",
            "erfüllt (strikt)",
        ],
        summary,
    )
    rep.add(
        f"Ausreißer ({len(details)}), Toleranz max(2 s, 1 %); „–“ bei Kairos = kein Fenster ohne "
        "Schritt > 8,5 m/s:",
        "",
    )
    if details:
        rep.table(
            [
                "Aktivität",
                "Distanz",
                "Kairos s (Timer)",
                "Garmin s",
                "Δ s",
                "Kairos s (Gesamtzeit)",
                "Kairos s (Gesamtzeit, ohne Sprungfilter)",
                "Ursache",
            ],
            details,
        )
    rep.add(f"Nicht verglichen ({len(skipped)}):", "")
    if skipped:
        rep.table(["Aktivität", "Distanz", "Garmin s", "Grund"], skipped)


def pr_text(item: Row, by_ext: Mapping[str, int]) -> str:
    ext = str(item["activityId"])
    return f"ja: activityId {ext} = Aktivität {by_ext.get(ext)}"


def v3(rep: Report, efforts: list[Row], items: Mapping[str, Row], acts: Sequence[Activity]) -> None:
    rep.add("## V3 Bestwert der Historie gegen Garmin-PR", "")
    by_ext = {a.external_id: a.id for a in acts}
    rows: list[list[str]] = []
    for key, gkey in (("5k", "fastestSplit_5000"), ("10k", "fastestSplit_10000")):
        pr = PR_S[key]
        cand = [e for e in efforts if e["distance_key"] == key]
        best = min(cand, key=lambda e: e["duration_s"]) if cand else None
        pr_item = next(
            (
                it
                for it in items.values()
                if (v := num(it.get(gkey))) is not None and abs(v - pr) < 0.1
            ),
            None,
        )
        mine = None if best is None else float(best["duration_s"])
        in_archive = pr_item is not None
        rows.append(
            [
                key,
                fmt(pr),
                "nein" if pr_item is None else pr_text(pr_item, by_ext),
                fmt(mine),
                "–" if best is None else str(best["activity_id"]),
                fmt(None if mine is None else mine - pr, 2),
                yes(mine is not None and abs(mine - pr) <= tol(pr)) if in_archive else "n. a.",
            ]
        )
    rep.table(
        [
            "Distanz",
            "Garmin-PR s",
            "PR-Aktivität im Archiv",
            "Kairos-Bestwert s",
            "Kairos-Aktivität",
            "Δ s",
            "erfüllt (≤ max(2 s, 1 %))",
        ],
        rows,
    )


def step_rule_gain(alt: Sequence[float | None], hysteresis_m: float = 2.0) -> float:
    # elevation rule up to 2026-10-15: reference reset at every 2 m step
    gain = 0.0
    ref: float | None = None
    for v in alt:
        if v is None:
            continue
        if ref is None or abs(v - ref) >= hysteresis_m:
            gain += 0.0 if ref is None else max(v - ref, 0.0)
            ref = v
    return gain


def v4(
    rep: Report,
    acts: Sequence[Activity],
    fits: Mapping[int, Fit],
    stats: Mapping[int, Row],
    items: Mapping[str, Row],
) -> None:
    rep.add("## V4 Σ Hm↑ gegen elevationGain", "")
    pop: list[tuple[Activity, float, Fit]] = []
    for a in acts:
        garmin = num(items[a.external_id].get("elevationGain"))
        fit = fits[a.id]
        if garmin is not None and any(v is not None for v in fit.raw_alt):
            pop.append((a, garmin, fit))

    def stored(a: Activity, fit: Fit) -> float:
        return float(stats[a.id]["elev_gain_m"] or 0.0)

    def med(window: int, hyst: float) -> Callable[[Activity, Fit], float]:
        return lambda a, fit: elevation_gain_loss(_rolling_median(fit.raw_alt, window), hyst)[0]

    variants: list[tuple[str, Callable[[Activity, Fit], float]]] = [
        ("B.1 gespeichert: Median 5, Hysterese 2 m (Extremwerte, ab 2026-10-15)", stored),
        (
            "B.1 bis 2026-10-15: Median 5, 2-m-Stufen",
            lambda a, fit: step_rule_gain(_rolling_median(fit.raw_alt, 5)),
        ),
        ("Median 5, Hysterese 1 m", med(5, 1.0)),
        ("Median 5, Hysterese 3 m", med(5, 3.0)),
        ("Median 3, Hysterese 2 m", med(3, 2.0)),
        ("ohne Median, Hysterese 2 m", med(1, 2.0)),
        ("ohne Median, Hysterese 3 m", med(1, 3.0)),
    ]

    def hit(mine: float, garmin: float, floor: float = 0.0) -> bool:
        return abs(mine - garmin) <= max(0.1 * garmin, floor)

    rows: list[list[str]] = []
    for name, fn in variants:
        values = [(fn(a, fit), g) for a, g, fit in pop]
        hits = sum(hit(m, g, 0.5) for m, g in values)
        hits2 = sum(hit(m, g, 2.0) for m, g in values)
        ratios = [m / g for m, g in values if g > 0]
        rows.append(
            [
                name,
                pct(hits, len(pop)),
                pct(hits2, len(pop)),
                fmt(100 * statistics.median(ratios)),
                yes(bool(pop) and hits / len(pop) >= 0.9),
            ]
        )
    same = sum(
        1 for _, g, fit in pop if fit.total_ascent is not None and abs(fit.total_ascent - g) < 0.5
    )
    rep.add(
        f"Population: {len(pop)} Aktivitäten mit Höhenkanal und elevationGain. "
        f"Garmins elevationGain = FIT `session.total_ascent` bei {pct(same, len(pop))}. "
        "Toleranz ±10 % (bei elevationGain 0: ±0,5 m).",
        "",
    )
    rep.table(
        [
            "Variante",
            "Quote ±10 %",
            "Quote max(±10 %, ±2 m)",
            "Median Kairos/Garmin %",
            "erfüllt (≥ 90 %)",
        ],
        rows,
    )
    by_profile: dict[str, list[bool]] = {}
    for a, g, fit in pop:
        by_profile.setdefault(a.sport_profile, []).append(hit(stored(a, fit), g, 0.5))
    rep.table(
        ["Profil", "Quote ±10 % (gespeichert)"],
        [[p, pct(sum(v), len(v))] for p, v in sorted(by_profile.items())],
    )
    out = []
    for a, garmin, fit in pop:
        mine = stored(a, fit)
        if not hit(mine, garmin, 0.5):
            dev = None if garmin == 0 else 100 * (mine - garmin) / garmin
            out.append(
                [
                    str(a.id),
                    a.sport or a.sport_profile,
                    fmt(garmin),
                    fmt(mine),
                    fmt(mine - garmin),
                    fmt(dev, 0),
                ]
            )
    small = sum(1 for r in out if float(r[2]) < 20)
    rep.add(f"Ausreißer gespeichert ({len(out)}; davon {small} mit elevationGain < 20 m):", "")
    if out:
        rep.table(["Aktivität", "Sportart", "Garmin m", "Kairos m", "Δ m", "Δ %"], out)


def v5(
    rep: Report, runs: Sequence[Activity], stats: Mapping[int, Row], items: Mapping[str, Row]
) -> None:
    rep.add("## V5 Ø-Kadenz gegen averageRunningCadenceInStepsPerMinute", "")
    pairs = [
        (a, mine, g)
        for a in runs
        if (g := num(items[a.external_id].get("averageRunningCadenceInStepsPerMinute"))) is not None
        and (mine := num(stats.get(a.id, {}).get("cadence_avg"))) is not None
    ]
    ok = sum(1 for _, m, g in pairs if abs(m - g) <= 2.0)
    rep.table(
        ["Läufe", "Quote |Δ| ≤ 2 spm", "Kriterium", "erfüllt", "max |Δ| spm"],
        [
            [
                str(len(pairs)),
                pct(ok, len(pairs)),
                "±2 spm je Lauf",
                yes(bool(pairs) and ok == len(pairs)),
                fmt(max((abs(m - g) for _, m, g in pairs), default=None), 2),
            ]
        ],
    )
    out = [
        [str(a.id), fmt(m, 2), fmt(g, 2), fmt(m - g, 2)] for a, m, g in pairs if abs(m - g) > 2.0
    ]
    rep.add(f"Ausreißer ({len(out)})", "")
    if out:
        rep.table(["Aktivität", "Kairos spm", "Garmin spm", "Δ"], out)


def v6(rep: Report, acts: Sequence[Activity], stats: Mapping[int, Row]) -> None:
    rep.add("## V6 Ø-HF gegen activity.avg_hr", "")
    pairs = [
        (a, int(mine), a.avg_hr)
        for a in acts
        if a.avg_hr is not None and (mine := stats.get(a.id, {}).get("hr_avg")) is not None
    ]
    ok = sum(1 for _, m, g in pairs if abs(m - g) <= 1)
    exact = sum(1 for _, m, g in pairs if m == g)
    rep.table(
        ["Aktivitäten mit HF", "Quote |Δ| ≤ 1 bpm", "davon exakt", "Kriterium", "erfüllt"],
        [
            [
                str(len(pairs)),
                pct(ok, len(pairs)),
                str(exact),
                "±1 bpm je Aktivität",
                yes(bool(pairs) and ok == len(pairs)),
            ]
        ],
    )
    out = [
        [str(a.id), a.sport_profile, str(m), str(g), str(m - g)]
        for a, m, g in pairs
        if abs(m - g) > 1
    ]
    rep.add(f"Ausreißer ({len(out)})", "")
    if out:
        rep.table(["Aktivität", "Profil", "Kairos bpm", "Garmin bpm", "Δ"], out)


def planned_sequence(steps: Sequence[Row]) -> list[int]:
    by_idx = {s["message_index"]: s for s in steps if isinstance(s.get("message_index"), int)}
    out: list[int] = []
    passes: dict[int, int] = {}
    pc = 0
    while pc in by_idx and len(out) < 10_000:
        s = by_idx[pc]
        if s.get("duration_type") != "repeat_until_steps_cmplt":
            out.append(pc)
            pc += 1
            continue
        back = s.get("duration_step")
        reps = s.get("repeat_steps") or s.get("target_value")
        passes[pc] = passes.get(pc, 0) + 1
        if isinstance(back, int) and isinstance(reps, int) and passes[pc] < reps:
            # inner repeat counters restart with each outer pass
            for k in list(passes):
                if back <= k < pc:
                    passes[k] = 0
            pc = back
        else:
            passes[pc] = 0
            pc += 1
    return out


@dataclass
class LapGroup:
    index: int
    timer_s: float = 0.0
    pause_s: float = 0.0
    laps: int = 0


def lap_groups(laps: Sequence[Row]) -> list[LapGroup]:
    groups: list[LapGroup] = []
    for lap in laps:
        idx = lap.get("wkt_step_index")
        elapsed = num(lap.get("total_elapsed_time")) or 0.0
        if not isinstance(idx, int) or elapsed < MIN_LAP_S:
            continue
        timer = num(lap.get("total_timer_time"))
        timer = elapsed if timer is None else timer
        if not groups or groups[-1].index != idx:
            groups.append(LapGroup(idx))
        g = groups[-1]
        g.timer_s += timer
        g.pause_s += elapsed - timer
        g.laps += 1
    return groups


def skipped_steps(planned: Sequence[int], done: Sequence[int]) -> tuple[list[int], bool]:
    skipped: list[int] = []
    j = 0
    for k, p in enumerate(planned):
        if j < len(done) and done[j] == p:
            j += 1
        else:
            skipped.append(k)
    return skipped, j == len(done)


def v7(rep: Report, runs: Sequence[Activity], fits: Mapping[int, Fit], steps: list[Row]) -> None:
    rep.add("## V7 Soll/Ist pro Workout-Schritt", "")
    by_act: dict[int, list[Row]] = {}
    for r in steps:
        by_act.setdefault(r["activity_id"], []).append(r)
    workouts = [a.id for a in runs if fits[a.id].is_workout]
    rows: list[list[str]] = []
    notes: list[list[str]] = []
    core_ok = True
    n_ok = 0
    for aid in workouts:
        fit = fits[aid]
        planned = planned_sequence(fit.workout_steps)
        groups = lap_groups(fit.laps)
        ours = sorted(by_act.get(aid, []), key=lambda r: r["exec_idx"])
        skipped, in_order = skipped_steps(planned, [g.index for g in groups])
        same_steps = [r["wkt_step_index"] for r in ours] == [g.index for g in groups]
        devs = [
            abs(float(r["timer_s"]) - g.timer_s) if r["timer_s"] is not None else math.inf
            for r, g in zip(ours, groups, strict=False)
        ]
        ok = in_order and same_steps and all(d <= 1.0 for d in devs)
        n_ok += ok
        if aid in V7_CORE:
            core_ok = core_ok and ok
        intens = {s.get("message_index"): s.get("intensity") for s in fit.workout_steps}
        rows.append(
            [
                f"**{aid}**" if aid in V7_CORE else str(aid),
                str(len(planned)),
                str(len(groups)),
                str(len(ours)),
                ", ".join(f"#{k + 1} {intens.get(planned[k])}" for k in skipped) or "–",
                yes(len(ours) == len(planned)),
                fmt(max(devs, default=None), 2),
                yes(ok),
            ]
        )
        for r, g, d in zip(ours, groups, devs, strict=False):
            if d > 1.0:
                notes.append(
                    [
                        str(aid),
                        str(r["exec_idx"]),
                        fmt(r["timer_s"], 2),
                        fmt(g.timer_s, 2),
                        str(g.laps),
                        fmt(g.pause_s, 2),
                    ]
                )
    rep.add(
        f"Kernstichprobe {', '.join(map(str, V7_CORE))}: "
        f"{'erfüllt' if core_ok else 'nicht erfüllt'}. "
        f"Alle Workout-Läufe: {pct(n_ok, len(workouts))}. Runden < 5 s und die Schlussrunde ohne "
        "Schrittindex zählen nicht (B.6).",
        "",
    )
    rep.table(
        [
            "Aktivität",
            "geplant (Schritte × Wdh.)",
            "gelaufen (Runden)",
            "Kairos-Zeilen",
            "übersprungen (Ausführung, Typ)",
            "= Schritte × Wdh. (strikt)",
            "max |Δ Dauer| s",
            "erfüllt (gelaufene, ±1 s)",
        ],
        rows,
    )
    if notes:
        rep.add("Ausführungen mit Abweichung > 1 s:", "")
        rep.table(
            [
                "Aktivität",
                "Ausführung",
                "Kairos s",
                "Σ Runden s",
                "Runden",
                "Pause in den Runden s",
            ],
            notes,
        )


async def run(uid: uuid.UUID, out_path: str) -> None:
    async with async_session_factory() as session:
        install_rls_listener(session, uid)
        items = await garmin_items(session)
        acts = list(
            (
                await session.execute(
                    select(Activity)
                    .where(Activity.user_id == uid, Activity.deleted_at.is_(None))
                    .order_by(Activity.id)
                )
            ).scalars()
        )
        stats = {r["activity_id"]: r for r in await table_rows(session, "activity_stats", uid)}
        splits = await table_rows(session, "activity_split", uid)
        efforts = await table_rows(session, "activity_best_effort", uid)
        steps = await table_rows(session, "activity_step_result", uid)
        fits = {a.id: await load_fit(session, a) for a in acts}
        # keep loaded attributes; this session only read
        session.expunge_all()

    runs = [a for a in acts if a.sport_profile == "running"]
    rep = Report()
    rep.add(
        f"Aktivitäten {len(acts)}, davon Läufe {len(runs)}; Garmin-Listeneinträge {len(items)}. "
        f"Zeilen: activity_stats {len(stats)}, activity_split {len(splits)}, "
        f"activity_best_effort {len(efforts)}, activity_step_result {len(steps)}.",
        "",
    )
    v1(rep, runs, fits, splits)
    v2(rep, runs, fits, efforts, items, stats)
    v3(rep, efforts, items, acts)
    v4(rep, acts, fits, stats, items)
    v5(rep, runs, stats, items)
    v6(rep, acts, stats)
    v7(rep, runs, fits, steps)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep.lines) + "\n")
    print(f"wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=uuid.UUID, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.user_id, args.out))


if __name__ == "__main__":
    main()
