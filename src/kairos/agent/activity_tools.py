from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from kairos.activities.derive.best_efforts import BEST_EFFORT_DISTANCES
from kairos.activities.derive.common import (
    Prepared,
    elevation_gain_loss,
    interp,
    interpolate_time_at_distance,
    prepare,
    weighted_mean,
    weighted_median,
)
from kairos.activities.derive.stats import DECOUPLING_WARMUP_S, decoupling, efficiency
from kairos.activities.fit_archive import load_fit_messages
from kairos.activities.stream_repository import load_stream
from kairos.agent.format import (
    MINUS,
    cap_envelope,
    drop_last_row,
    fmt_date_short,
    fmt_datetime_local,
    fmt_diff,
    fmt_distance,
    fmt_duration,
    fmt_pace_100m,
    fmt_pace_km,
    fmt_percent,
    fmt_speed_kmh,
    table,
)
from kairos.db.models import (
    Activity,
    ActivityBestEffort,
    ActivitySplit,
    ActivityStats,
    ActivityStepResult,
    AppUser,
    SyncState,
)

SPORT_PROFILES = ("running", "cycling", "swimming", "hiking", "generic")
SEARCH_SORTS = ("newest", "oldest", "longest", "fastest")
SEARCH_MAX_TOKENS = 600
GET_MAX_TOKENS = 700
SEARCH_COLS = [
    "id", "datum", "name", "sport", "distanz", "dauer", "tempo", "hf_avg", "hm_auf", "trimp",
]

_DEFAULT_TZ = "Europe/Berlin"
_SEARCH_NAME_CHARS = 40
_GET_NAME_CHARS = 80
_SPORT_LABEL = {
    "running": "Laufen", "cycling": "Rad", "swimming": "Schwimmen", "hiking": "Wandern",
    "generic": "Sonstiges",
}
_NOUNS = {
    "running": ("Lauf", "Läufe"),
    "cycling": ("Radfahrt", "Radfahrten"),
    "swimming": ("Schwimmeinheit", "Schwimmeinheiten"),
    "hiking": ("Wanderung", "Wanderungen"),
    "generic": ("Aktivität", "Aktivitäten"),
}
_DISTANCE_SOURCE = {
    "gps": "GPS",
    "watch_estimate": "Uhr-Schätzung (Laufband/Indoor)",
    "pool": "Becken",
    "mixed": "gemischt (GPS lückenhaft)",
    "none": "keine",
}
_STEP_LABEL = {
    "warmup": "Einlaufen", "interval": "Intervalle", "recovery": "Trabpausen", "rest": "Pausen",
    "cooldown": "Auslaufen",
}
RUN_POWER_NOTE = "Handgelenk, eingeschränkt aussagekräftig"
SWIM_HR_NOTE = "Handgelenk-HF im Wasser eingeschränkt verlässlich"
# dropped one by one, in this order, when activity_get exceeds its cap
_GET_SHRINK_ORDER = ("effizienz", "splits", "technik", "schwimmen", "wandern", "belastung")


def _envelope(*args: Any, **kwargs: Any) -> dict[str, Any]:
    # tools.py imports this module for CORE_TOOLS
    from kairos.agent.tools import _envelope as envelope

    return envelope(*args, **kwargs)


def _finish(
    env: dict[str, Any], *, as_of: datetime | None, max_tokens: int, shrink: Any
) -> dict[str, Any]:
    env["meta"]["as_of"] = None if as_of is None else as_of.isoformat()
    return cap_envelope(env, max_tokens=max_tokens, shrink=shrink)


def _check_profile(sport_profile: str | None) -> None:
    if sport_profile is not None and sport_profile not in SPORT_PROFILES:
        raise ValueError(f"sport_profile muss eines von {', '.join(SPORT_PROFILES)} sein")


def _short(name: str | None, limit: int) -> str | None:
    if name is None or len(name) <= limit:
        return name
    return name[: limit - 1].rstrip() + "…"


def _int(value: float | None) -> int | None:
    return None if value is None else round(value)


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def _user_context(session: AsyncSession, user_id: UUID) -> tuple[str, datetime | None]:
    tz = (
        await session.execute(select(AppUser.home_timezone).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    as_of = (
        await session.execute(
            select(func.max(SyncState.last_success_at)).where(
                SyncState.user_id == user_id, SyncState.kind == "activity_list"
            )
        )
    ).scalar_one_or_none()
    return tz or _DEFAULT_TZ, as_of


def _distance_expr() -> ColumnElement[Any]:
    return func.coalesce(ActivityStats.distance_m, Activity.distance_m)


def _pick(st: ActivityStats | None, attr: str, fallback: Any = None) -> Any:
    value = None if st is None else getattr(st, attr)
    return fallback if value is None else value


def _tempo(profile: str, st: ActivityStats | None) -> str | None:
    if st is None:
        return None
    if profile in ("running", "hiking") and st.avg_pace_s_km:
        return fmt_pace_km(st.avg_pace_s_km)
    if profile == "cycling" and st.avg_speed_kmh:
        return fmt_speed_kmh(st.avg_speed_kmh)
    if profile == "swimming" and st.avg_pace_s_100m:
        return fmt_pace_100m(st.avg_pace_s_100m)
    return None


def _order_by(sort: str, sport_profile: str | None) -> list[Any]:
    newest = [Activity.start_at.desc().nulls_last(), Activity.id.desc()]
    if sort == "newest":
        return newest
    if sort == "oldest":
        return [Activity.start_at.asc().nulls_last(), Activity.id.asc()]
    if sort == "longest":
        return [_distance_expr().desc().nulls_last(), *newest]
    if sport_profile is None:
        raise ValueError("sort='fastest' verlangt sport_profile")
    if sport_profile in ("running", "hiking"):
        return [ActivityStats.avg_pace_s_km.asc().nulls_last(), *newest]
    if sport_profile == "swimming":
        return [ActivityStats.avg_pace_s_100m.asc().nulls_last(), *newest]
    if sport_profile == "cycling":
        return [ActivityStats.avg_speed_kmh.desc().nulls_last(), *newest]
    raise ValueError("sort='fastest' ist für sport_profile='generic' nicht möglich")


def _search_row(a: Activity, st: ActivityStats | None, tz: str) -> list[object]:
    distance = _pick(st, "distance_m", a.distance_m)
    duration = _pick(st, "timer_s", a.duration_s)
    return [
        a.id,
        None if a.start_at is None else fmt_date_short(a.start_at, tz),
        _short(a.name, _SEARCH_NAME_CHARS),
        _SPORT_LABEL[a.sport_profile],
        fmt_distance(distance) if distance else None,
        fmt_duration(duration) if duration else None,
        _tempo(a.sport_profile, st),
        _pick(st, "hr_avg", a.avg_hr),
        _int(_pick(st, "elev_gain_m", a.elevation_gain_m)),
        _int(_pick(st, "trimp_edwards")),
    ]


def _search_summary(
    count: int, total_m: float | None, shown: int, sport_profile: str | None, start: date, end: date
) -> str:
    singular, plural = _NOUNS[sport_profile or "generic"]
    begin = f"{start:%d.%m.}" if start.year == end.year else f"{start:%d.%m.%Y}"
    span = f"zwischen {begin} und {end:%d.%m.%Y}"
    if count == 0:
        return f"Keine {plural} {span}."
    text = f"{count} {singular if count == 1 else plural} {span}"
    if total_m:
        text += f", zusammen {fmt_distance(total_m)}"
    text += "."
    if shown < count:
        text += f" Gezeigt: {shown}."
    return text


async def activity_search_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    from_date: str | None = None,
    to_date: str | None = None,
    sport_profile: str | None = None,
    name_contains: str | None = None,
    min_distance_km: float | None = None,
    max_distance_km: float | None = None,
    sort: str = "newest",
    limit: int = 10,
) -> dict[str, Any]:
    _check_profile(sport_profile)
    if sort not in SEARCH_SORTS:
        raise ValueError(f"sort muss eines von {', '.join(SEARCH_SORTS)} sein")
    order = _order_by(sort, sport_profile)
    limit = max(1, min(int(limit), 20))
    tz, as_of = await _user_context(session, user_id)
    today = datetime.now(ZoneInfo(tz)).date()
    end = date.fromisoformat(to_date) if to_date else today
    start = date.fromisoformat(from_date) if from_date else today - timedelta(days=30)
    if start > end:
        raise ValueError("from_date liegt nach to_date")

    local_day = _local_day(tz)
    distance = _distance_expr()
    conds: list[ColumnElement[bool]] = [
        Activity.user_id == user_id,
        Activity.deleted_at.is_(None),
        local_day >= start,
        local_day <= end,
    ]
    if sport_profile is not None:
        conds.append(Activity.sport_profile == sport_profile)
    if name_contains:
        conds.append(Activity.name.icontains(name_contains, autoescape=True))
    if min_distance_km is not None:
        conds.append(distance >= min_distance_km * 1000)
    if max_distance_km is not None:
        conds.append(distance <= max_distance_km * 1000)

    joined = select(Activity, ActivityStats).outerjoin(
        ActivityStats, ActivityStats.activity_id == Activity.id
    )
    rows = (await session.execute(joined.where(*conds).order_by(*order).limit(limit))).all()
    count, total = (
        await session.execute(
            select(func.count(Activity.id), func.sum(distance))
            .select_from(Activity)
            .outerjoin(ActivityStats, ActivityStats.activity_id == Activity.id)
            .where(*conds)
        )
    ).one()

    data = table(SEARCH_COLS, [_search_row(a, st, tz) for a, st in rows])
    env = _envelope(
        _search_summary(int(count), total, len(rows), sport_profile, start, end),
        data,
        next_hint="Details: activity_get(activity_id=…)",
    )
    return _finish(env, as_of=as_of, max_tokens=SEARCH_MAX_TOKENS, shrink=drop_last_row)


def _shrink_get(env: dict[str, Any]) -> dict[str, Any] | None:
    data = env["data"]
    for key in _GET_SHRINK_ORDER:
        if key in data:
            del data[key]
            return env
    zones = data.get("herzfrequenz", {})
    if "zonen" in zones:
        del zones["zonen"]
        return env
    return None


def _split_label(profile: str, idx: int | None, pace_s: float | None) -> str | None:
    if idx is None or not pace_s:
        return None
    if profile == "cycling":
        return f"5-km-Abschnitt {idx} · {fmt_speed_kmh(3600 / pace_s)}"
    if profile == "swimming":
        return f"Abschnitt {idx} · {fmt_pace_100m(pace_s)}"
    return f"km {idx} · {fmt_pace_km(pace_s)}"


def _tempo_block(profile: str, st: ActivityStats | None) -> dict[str, Any] | None:
    if st is None or profile == "generic":
        return None
    fastest = _split_label(profile, st.fastest_split_idx, st.fastest_split_pace_s)
    slowest = _split_label(profile, st.slowest_split_idx, st.slowest_split_pace_s)
    cv = None if st.pace_cv_pct is None else f"CV {fmt_percent(st.pace_cv_pct)}"
    if profile == "cycling":
        moving = st.sport_metrics.get("avg_moving_speed_kmh")
        return _compact({
            "avg_kmh": fmt_speed_kmh(st.avg_speed_kmh) if st.avg_speed_kmh else None,
            "max_kmh": fmt_speed_kmh(st.max_speed_kmh) if st.max_speed_kmh else None,
            "avg_bewegt_kmh": fmt_speed_kmh(moving) if moving else None,
            "schnellster_abschnitt": fastest,
            "langsamster_abschnitt": slowest,
            "gleichmaessigkeit": cv,
        })
    if profile == "swimming":
        return _compact({
            "pace": fmt_pace_100m(st.avg_pace_s_100m) if st.avg_pace_s_100m else None,
            "schnellster_abschnitt": fastest,
            "langsamster_abschnitt": slowest,
            "gleichmaessigkeit": cv,
        })
    return _compact({
        "pace": fmt_pace_km(st.avg_pace_s_km) if st.avg_pace_s_km else None,
        "pace_bewegt": (
            fmt_pace_km(st.avg_moving_pace_s_km) if st.avg_moving_pace_s_km else None
        ),
        "schnellster_km": fastest,
        "langsamster_km": slowest,
        "gleichmaessigkeit": cv,
    })


def _umfang(profile: str, a: Activity, st: ActivityStats | None) -> dict[str, Any]:
    distance = _pick(st, "distance_m", a.distance_m)
    timer = _pick(st, "timer_s", a.duration_s)
    elapsed = _pick(st, "elapsed_s")
    umfang: dict[str, Any] = {
        "distanz": fmt_distance(distance) if distance else None,
        "zeit": fmt_duration(timer) if timer else None,
        "zeit_inkl_pausen": fmt_duration(elapsed) if elapsed else None,
    }
    if profile != "swimming":
        gain = _pick(st, "elev_gain_m", a.elevation_gain_m)
        loss = _pick(st, "elev_loss_m")
        low, high = _pick(st, "alt_min_m"), _pick(st, "alt_max_m")
        umfang["hm_auf"] = None if gain is None else f"{round(gain)} m"
        umfang["hm_ab"] = None if loss is None else f"{round(loss)} m"
        if low is not None and high is not None:
            umfang["hoehe"] = f"{round(low)}–{round(high)} m"
        if profile == "hiking" and high is not None:
            umfang["max_hoehe"] = f"{round(high)} m"
    return _compact(umfang)


def _herzfrequenz(profile: str, a: Activity, st: ActivityStats | None) -> dict[str, Any]:
    zones = _pick(st, "hr_zone_s")
    hr = _compact({
        "avg": _pick(st, "hr_avg", a.avg_hr),
        "median": _pick(st, "hr_median"),
        "min": _pick(st, "hr_min"),
        "max": _pick(st, "hr_max", a.max_hr),
        "zonen": None if not zones else {k: fmt_duration(v) for k, v in sorted(zones.items())},
    })
    if profile == "swimming" and hr:
        hr["hinweis"] = SWIM_HR_NOTE
    return hr


def _technik(profile: str, st: ActivityStats | None) -> dict[str, Any] | None:
    if st is None or profile not in ("running", "cycling"):
        return None
    unit = "spm" if profile == "running" else "rpm"
    power = None
    if st.power_avg_w is not None:
        power = f"{round(st.power_avg_w)} W"
        if profile == "running":
            power += f" ({RUN_POWER_NOTE})"
    normalized = st.sport_metrics.get("normalized_power_w") if profile == "cycling" else None
    return _compact({
        "kadenz": None if st.cadence_avg is None else f"{round(st.cadence_avg)} {unit}",
        "leistung": power,
        "normalized_power": None if normalized is None else f"{round(normalized)} W",
    }) or None


def _sport_block(profile: str, st: ActivityStats | None) -> tuple[str, dict[str, Any]] | None:
    metrics = {} if st is None else st.sport_metrics
    if profile == "swimming":
        pool, swolf, rest = (
            metrics.get("pool_length_m"), metrics.get("avg_swolf"), metrics.get("rest_s")
        )
        block = _compact({
            "beckenlaenge": None if pool is None else f"{round(pool)} m",
            "bahnen": metrics.get("active_lengths"),
            "swolf": _int(swolf),
            "pausenzeit": None if rest is None else fmt_duration(rest),
        })
        return ("schwimmen", block) if block else None
    if profile == "hiking":
        up, down = metrics.get("ascent_rate_m_h"), metrics.get("descent_rate_m_h")
        block = _compact({
            "steigrate": None if up is None else f"{round(up)} Hm/h",
            "abstiegsrate": None if down is None else f"{round(down)} Hm/h",
        })
        return ("wandern", block) if block else None
    return None


async def _split_counts(session: AsyncSession, activity_id: int) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ActivitySplit.kind, func.count())
            .where(ActivitySplit.activity_id == activity_id)
            .group_by(ActivitySplit.kind)
        )
    ).all()
    return {kind: int(n) for kind, n in rows}


def _splits_block(profile: str, counts: dict[str, int]) -> dict[str, int] | None:
    key = {"cycling": "abschnitte_5km", "swimming": "abschnitte_100m", "generic": None}.get(
        profile, "km"
    )
    block = {} if key is None else {key: counts.get("distance", 0)}
    block["runden"] = counts.get("lap", 0)
    return {k: v for k, v in block.items() if v} or None


def _step_groups(steps: Sequence[ActivityStepResult], *, with_pace: bool = False) -> str:
    rated = [s for s in steps if s.hit is not None]
    parts: list[str] = []
    for step_type in dict.fromkeys(s.step_type for s in rated):
        group = [s for s in rated if s.step_type == step_type]
        hits = sum(1 for s in group if s.hit)
        where = "HF-Bereich" if all(s.target_type == "hr_range" for s in group) else "Zielbereich"
        label = _STEP_LABEL.get(step_type, step_type)
        part = f"{label} {hits}/{len(group)} im {where}"
        timer = sum(s.timer_s or 0.0 for s in group)
        dist = sum(s.distance_m or 0.0 for s in group)
        if with_pace and all(s.target_type == "pace" for s in group) and timer and dist:
            part += f" (Ø {fmt_pace_km(timer / dist * 1000)})"
        parts.append(part)
    return ", ".join(parts) if parts else "keine bewertbaren Schritte"


def _workout_block(name: str | None, steps: Sequence[ActivityStepResult]) -> dict[str, Any]:
    rated = [s for s in steps if s.hit is not None]
    return {
        "name": name or "Workout",
        "bewertet": len(rated),
        "getroffen": sum(1 for s in rated if s.hit),
        "kurz": _step_groups(steps),
    }


def _next_hint(profile: str, activity_id: int, has_workout: bool) -> str:
    call = f"activity_splits(activity_id={activity_id}"
    if has_workout:
        return f'Workout-Schritte: {call}, kind="steps")'
    if profile == "generic":
        return f'Runden: {call}, kind="lap")'
    label = {"cycling": "5-km-Abschnitte", "swimming": "100-m-Abschnitte"}.get(
        profile, "Kilometerwerte"
    )
    return f"{label}: {call})"


def _get_summary(
    profile: str, a: Activity, st: ActivityStats | None, tz: str, data: dict[str, Any]
) -> str:
    noun = _NOUNS[profile][0]
    day = "" if a.start_at is None else " " + fmt_datetime_local(a.start_at, tz).rsplit(" ", 1)[0]
    umfang, tempo = data["umfang"], data.get("tempo") or {}
    avg = tempo.get("avg_kmh") or tempo.get("pace")
    body = []
    if umfang.get("distanz") and umfang.get("zeit"):
        body.append(
            f"{umfang['distanz']} in {umfang['zeit']}" + (f" (Ø {avg})" if avg else "")
        )
    elif umfang.get("zeit"):
        body.append(umfang["zeit"])
    hr_avg = data["herzfrequenz"].get("avg")
    if hr_avg is not None:
        body.append(f"Ø-HF {hr_avg}")
    if st is not None and profile in ("running", "hiking"):
        if st.fastest_split_idx is not None and st.fastest_split_pace_s:
            body.append(
                f"schnellster km {st.fastest_split_idx} ({fmt_pace_km(st.fastest_split_pace_s)})"
            )
        if st.slowest_split_idx is not None and st.slowest_split_pace_s:
            body.append(
                f"langsamster km {st.slowest_split_idx} ({fmt_pace_km(st.slowest_split_pace_s)})"
            )
    text = f"{noun}{day}: " + ", ".join(body) + "." if body else f"{noun}{day}."
    workout = data.get("workout")
    if workout:
        text += (
            f" Workout „{workout['name']}“: {workout['getroffen']}/{workout['bewertet']} "
            "Schritte im Ziel."
        )
    return text


async def activity_get_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    activity_id: int | None = None,
    sport_profile: str | None = None,
) -> dict[str, Any]:
    _check_profile(sport_profile)
    tz, as_of = await _user_context(session, user_id)
    stmt = (
        select(Activity, ActivityStats)
        .outerjoin(ActivityStats, ActivityStats.activity_id == Activity.id)
        .where(Activity.user_id == user_id, Activity.deleted_at.is_(None))
    )
    if activity_id is not None:
        stmt = stmt.where(Activity.id == activity_id)
    else:
        if sport_profile is not None:
            stmt = stmt.where(Activity.sport_profile == sport_profile)
        stmt = stmt.order_by(Activity.start_at.desc().nulls_last(), Activity.id.desc()).limit(1)
    row = (await session.execute(stmt)).first()
    if row is None:
        what = f"activity_id={activity_id}" if activity_id is not None else (
            f"sport_profile={sport_profile}" if sport_profile else "eigene Aktivitäten"
        )
        raise ValueError(f"Aktivität nicht gefunden ({what})")
    a, st = row._tuple()
    profile = a.sport_profile

    steps = (
        await session.execute(
            select(ActivityStepResult)
            .where(ActivityStepResult.activity_id == a.id)
            .order_by(ActivityStepResult.exec_idx)
        )
    ).scalars().all()
    source = _pick(st, "distance_source")
    data: dict[str, Any] = {
        "aktivitaet": _compact({
            "id": a.id,
            "name": _short(a.name, _GET_NAME_CHARS),
            "sport": f"{_SPORT_LABEL[profile]} ({profile})",
            "start": None if a.start_at is None else fmt_datetime_local(a.start_at, tz),
            "distanzquelle": None if source is None else _DISTANCE_SOURCE.get(source, source),
        }),
        "umfang": _umfang(profile, a, st),
    }
    tempo = _tempo_block(profile, st)
    if tempo:
        data["tempo"] = tempo
    data["herzfrequenz"] = _herzfrequenz(profile, a, st)
    technik = _technik(profile, st)
    if technik:
        data["technik"] = technik
    sport_block = _sport_block(profile, st)
    if sport_block:
        data[sport_block[0]] = sport_block[1]
    belastung = _compact({
        "trimp_edwards": _int(_pick(st, "trimp_edwards")),
        "garmin_training_load": _int(a.garmin_training_load),
        "garmin_vo2max": _int(a.garmin_vo2max),
    })
    if belastung:
        data["belastung"] = belastung
    if st is not None and profile in ("running", "cycling"):
        data["effizienz"] = {
            "entkopplung": (
                None if st.decoupling_pct is None else fmt_percent(st.decoupling_pct)
            ),
            "hinweis": st.decoupling_note,
        }
    splits = _splits_block(profile, await _split_counts(session, a.id))
    if splits:
        data["splits"] = splits
    data["workout"] = _workout_block(a.name, steps) if steps else None

    coverage = []
    for label, attr in (("HF", "hr_coverage_pct"), ("GPS", "gps_coverage_pct")):
        value = _pick(st, attr)
        if value is not None and not (label == "GPS" and profile == "swimming"):
            coverage.append(f"{label} {round(value)} %")
    env = _envelope(
        _get_summary(profile, a, st, tz, data),
        data,
        coverage=", ".join(coverage) or None,
        quality=_pick(st, "quality", "partial"),
        next_hint=_next_hint(profile, a.id, bool(steps)),
    )
    return _finish(env, as_of=as_of, max_tokens=GET_MAX_TOKENS, shrink=_shrink_get)


SPLITS_MAX_TOKENS = 1200
ANALYZE_MAX_TOKENS = 800
SPLIT_KINDS = ("distance", "lap", "steps")
ANALYZE_OPERATIONS = ("segment", "compare", "hr_drift", "curve")
CURVE_METRICS = ("hf", "pace", "hoehe", "kadenz", "leistung")
_MAX_SPLIT_ROWS = 50
_BLOCK_SIZE = 5
_UNIT_LABEL = {"running": "1 km", "hiking": "1 km", "cycling": "5 km", "swimming": "100 m"}
_BLOCK_UNIT_LABEL = {"running": "5 km", "hiking": "5 km", "cycling": "25 km", "swimming": "500 m"}
_DISTANCE_COLS = {
    "running": [
        "km", "pace", "kum_zeit", "hm_auf", "hm_ab", "hf_min", "hf_med", "hf_max", "kadenz",
        "leistung",
    ],
    "hiking": [
        "km", "pace", "kum_zeit", "hm_auf", "hm_ab", "steigrate", "hf_min", "hf_med", "hf_max",
    ],
    "cycling": [
        "abschnitt", "kmh", "kum_zeit", "hm_auf", "hm_ab", "hf_min", "hf_med", "hf_max",
        "kadenz", "leistung",
    ],
    "swimming": ["m", "pace_100m", "kum_zeit", "bahnen", "swolf", "hf_med"],
}
_LAP_COLS = [
    "runde", "typ", "schritt", "distanz", "zeit", "tempo", "hf_min", "hf_med", "hf_max",
    "hm_auf", "hm_ab",
]
_STEP_COLS = ["nr", "schritt", "wdh", "ziel", "ist", "dauer", "distanz", "hf_med", "getroffen"]
_SEGMENT_COLS = [
    "bereich", "distanz", "dauer", "tempo", "hm_auf", "hm_ab", "hf_min", "hf_med", "hf_max",
    "kadenz", "leistung",
]
_SPLIT_NOUN = {
    "running": "Kilometer-Splits", "hiking": "Kilometer-Splits", "cycling": "5-km-Abschnitte",
    "swimming": "100-m-Abschnitte",
}
_LAP_INTENSITY = {
    "warmup": "Aufwärmen", "active": "Intervall", "interval": "Intervall",
    "recovery": "Erholung", "rest": "Pause", "cooldown": "Auslaufen",
}
_LAP_TRIGGER = {
    "distance": "Auto-Runde (Distanz)", "time": "Auto-Runde (Zeit)",
    "position_lap": "Auto-Runde (Ort)", "manual": "manuell", "session_end": "Ende",
}
_STEP_SINGULAR = {
    "warmup": "Einlaufen", "interval": "Intervall", "recovery": "Erholung", "rest": "Pause",
    "cooldown": "Auslaufen",
}
_TEMPO_COL = {"running": "pace", "hiking": "pace", "cycling": "kmh", "swimming": "pace_100m"}
_CURVE_LABEL = {
    "hf": "Herzfrequenz", "pace": "Pace", "hoehe": "Höhe", "kadenz": "Kadenz",
    "leistung": "Leistung",
}
_DRIFT_PROFILES = frozenset({"running", "cycling"})

_Shrink = Callable[[dict[str, Any]], dict[str, Any] | None]


def _dec(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _num_label(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _signed(value: float, decimals: int, unit: str = "") -> str:
    rounded = round(value, decimals)
    body = f"{_dec(abs(rounded), decimals)}{unit}"
    if rounded == 0:
        return body
    return f"{'+' if rounded > 0 else MINUS}{body}"


def _no_shrink(env: dict[str, Any]) -> dict[str, Any] | None:
    del env
    return None


def _cadence_unit(profile: str) -> str:
    return "spm" if profile == "running" else "rpm"


def _tempo_with_unit(profile: str, distance: float | None, timer: float | None) -> str | None:
    if not distance or not timer or distance <= 0 or timer <= 0:
        return None
    if profile in ("running", "hiking"):
        return fmt_pace_km(timer / distance * 1000)
    if profile == "cycling":
        return fmt_speed_kmh(distance / timer * 3.6)
    if profile == "swimming":
        return fmt_pace_100m(timer / distance * 100)
    return None


def _tempo_bare(profile: str, distance: float | None, timer: float | None) -> str | None:
    text = _tempo_with_unit(profile, distance, timer)
    if text is None:
        return None
    for unit in (" /km", " /100 m", " km/h"):
        text = text.removesuffix(unit)
    return text


def _project(
    cols: list[str], rows: list[dict[str, Any]]
) -> tuple[list[str], list[list[object]]]:
    # spec C.3: columns without any value are left out
    kept = [c for i, c in enumerate(cols) if i == 0 or any(r.get(c) is not None for r in rows)]
    return kept, [[r.get(c) for c in kept] for r in rows]


async def _load_activity(
    session: AsyncSession, user_id: UUID, activity_id: int
) -> tuple[Activity, ActivityStats | None]:
    row = (
        await session.execute(
            select(Activity, ActivityStats)
            .outerjoin(ActivityStats, ActivityStats.activity_id == Activity.id)
            .where(
                Activity.user_id == user_id,
                Activity.id == activity_id,
                Activity.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise ValueError(f"Aktivität nicht gefunden (activity_id={activity_id})")
    a, st = row._tuple()
    return a, st


async def _load_steps(session: AsyncSession, activity_id: int) -> list[ActivityStepResult]:
    return list(
        (
            await session.execute(
                select(ActivityStepResult)
                .where(ActivityStepResult.activity_id == activity_id)
                .order_by(ActivityStepResult.exec_idx)
            )
        ).scalars()
    )


class _Span:
    def __init__(self, splits: Sequence[ActivitySplit]) -> None:
        self.first, self.last = splits[0].idx, splits[-1].idx
        self.is_partial = any(s.is_partial for s in splits)

        def total(attr: str) -> float | None:
            values = [getattr(s, attr) for s in splits]
            return None if any(v is None for v in values) else float(sum(values))

        def some(attr: str) -> list[float]:
            return [float(v) for s in splits if (v := getattr(s, attr)) is not None]

        def by_time(attr: str) -> float | None:
            pairs = [(v, s.timer_s or 0.0) for s in splits if (v := getattr(s, attr)) is not None]
            weight = sum(w for _, w in pairs)
            return sum(v * w for v, w in pairs) / weight if weight > 0 else None

        self.distance_m, self.timer_s = total("distance_m"), total("timer_s")
        gains, losses = some("elev_gain_m"), some("elev_loss_m")
        self.gain = sum(gains) if gains else None
        self.loss = sum(losses) if losses else None
        hr_min, hr_med, hr_max = some("hr_min"), some("hr_median"), some("hr_max")
        self.hr_min = round(min(hr_min)) if hr_min else None
        self.hr_med = round(statistics.median(hr_med)) if hr_med else None
        self.hr_max = round(max(hr_max)) if hr_max else None
        self.cadence, self.power = by_time("cadence_avg"), by_time("power_avg_w")
        lengths, swolf = some("swim_lengths"), some("swolf")
        self.lengths = int(sum(lengths)) if lengths else None
        self.swolf = statistics.fmean(swolf) if swolf else None


def _spans(splits: Sequence[ActivitySplit], grouped: bool) -> list[_Span]:
    if not grouped:
        return [_Span([s]) for s in splits]
    return [_Span(splits[i : i + _BLOCK_SIZE]) for i in range(0, len(splits), _BLOCK_SIZE)]


def _common_cells(sp: _Span) -> dict[str, Any]:
    return {
        "hm_auf": _int(sp.gain),
        "hm_ab": _int(sp.loss),
        "hf_min": sp.hr_min,
        "hf_med": sp.hr_med,
        "hf_max": sp.hr_max,
        "kadenz": _int(sp.cadence),
        "leistung": _int(sp.power),
    }


def _distance_row(
    profile: str, sp: _Span, *, cum_s: float | None, start_m: float | None, end_m: float | None
) -> dict[str, Any]:
    if profile == "swimming" and end_m is not None:
        label = str(round(end_m))
        if sp.first != sp.last and start_m is not None:
            label = f"{round(start_m)}–{label}"
    else:
        label = str(sp.first) if sp.first == sp.last else f"{sp.first}–{sp.last}"
    if sp.is_partial and sp.first == sp.last and sp.distance_m is not None:
        label += f" ({fmt_distance(sp.distance_m)})"
    climb = round(sp.gain / sp.timer_s * 3600) if sp.gain is not None and sp.timer_s else None
    return {
        _DISTANCE_COLS[profile][0]: label,
        _TEMPO_COL[profile]: _tempo_bare(profile, sp.distance_m, sp.timer_s),
        "kum_zeit": None if cum_s is None else fmt_duration(cum_s),
        "steigrate": climb,
        "bahnen": sp.lengths,
        "swolf": _int(sp.swolf),
        **_common_cells(sp),
    }


def _lap_type(lap: ActivitySplit) -> str:
    if lap.wkt_step_index is not None and lap.lap_intensity in _LAP_INTENSITY:
        return _LAP_INTENSITY[lap.lap_intensity]
    return _LAP_TRIGGER.get(lap.lap_trigger or "", "Runde")


def _lap_row(profile: str, lap: ActivitySplit) -> dict[str, Any]:
    return {
        "runde": str(lap.idx),
        "typ": _lap_type(lap),
        # FIT message_index is 0-based
        "schritt": None if lap.wkt_step_index is None else lap.wkt_step_index + 1,
        "distanz": None if lap.distance_m is None else fmt_distance(lap.distance_m),
        "zeit": None if lap.timer_s is None else fmt_duration(lap.timer_s),
        "tempo": _tempo_with_unit(profile, lap.distance_m, lap.timer_s),
        **_common_cells(_Span([lap])),
    }


def _range_text(low: float, high: float, unit: str, fmt: Callable[[float], str]) -> str:
    return f"{fmt(low)}–{fmt(high)} {unit}"


def _whole(value: float) -> str:
    return str(round(value))


def _step_target(profile: str, s: ActivityStepResult) -> str | None:
    low, high = s.target_low, s.target_high
    if s.target_type in (None, "none"):
        return None
    if low is None or high is None:
        return "HF-Bereich (Ziel unbekannt)" if s.target_type == "hr_range" else "unklar"
    if s.target_type == "pace":
        # stored as speed in m/s: the upper speed is the faster pace
        return _range_text(1000 / high, 1000 / low, "/km", fmt_duration)
    if s.target_type == "speed":
        return _range_text(low * 3.6, high * 3.6, "km/h", lambda v: _dec(v, 1))
    if s.target_type == "hr_range":
        return _range_text(low, high, "bpm", _whole)
    if s.target_type == "cadence":
        return _range_text(low, high, _cadence_unit(profile), _whole)
    if s.target_type == "power":
        return _range_text(low, high, "W", _whole)
    return None


def _step_actual(profile: str, s: ActivityStepResult) -> str | None:
    if s.target_type == "hr_range":
        pct = s.hr_in_target_pct
        return None if pct is None else f"{round(pct)} % im Bereich"
    if s.target_type == "pace":
        return None if s.avg_pace_s_km is None else fmt_pace_km(s.avg_pace_s_km)
    if s.target_type == "speed":
        return _tempo_with_unit("cycling", s.distance_m, s.timer_s)
    if s.target_type == "cadence":
        cadence = _int(s.avg_cadence)
        return None if cadence is None else f"{cadence} {_cadence_unit(profile)}"
    if s.target_type == "power":
        power = _int(s.avg_power_w)
        return None if power is None else f"{power} W"
    return None


def _repeat_totals(steps: Sequence[ActivityStepResult]) -> list[int | None]:
    # planned repeat counts are not stored: the last pass of each repeated run stands in
    totals: list[int | None] = [None] * len(steps)
    i = 0
    while i < len(steps):
        if steps[i].repeat_iteration is None:
            i += 1
            continue
        j = i
        while j < len(steps) and steps[j].repeat_iteration is not None:
            j += 1
        top = max(s.repeat_iteration or 0 for s in steps[i:j])
        totals[i:j] = [top] * (j - i)
        i = j
    return totals


def _step_rows(profile: str, steps: Sequence[ActivityStepResult]) -> list[dict[str, Any]]:
    rows = []
    for s, total in zip(steps, _repeat_totals(steps), strict=True):
        rows.append({
            "nr": str(s.exec_idx),
            "schritt": s.step_note or _STEP_SINGULAR.get(s.step_type, s.step_type),
            "wdh": None if s.repeat_iteration is None else f"{s.repeat_iteration}/{total}",
            "ziel": _step_target(profile, s),
            "ist": _step_actual(profile, s),
            "dauer": None if s.timer_s is None else fmt_duration(s.timer_s),
            "distanz": None if s.distance_m is None else fmt_distance(s.distance_m),
            # the step table only keeps the time-weighted mean
            "hf_med": _int(s.avg_hr),
            "getroffen": "–" if s.hit is None else ("ja" if s.hit else "nein"),
        })
    return rows


def _row_shrinker(call: str, last_idx: list[int]) -> _Shrink:
    def shrink(env: dict[str, Any]) -> dict[str, Any] | None:
        rows = env["data"]["rows"]
        if len(rows) <= 1:
            return None
        rows.pop()
        env["meta"]["row_count"] = len(rows)
        env["meta"]["next"] = f"weitere Zeilen: {call}, from_idx={last_idx[len(rows) - 1] + 1})"
        return env

    return shrink


def _extremes_text(profile: str, st: ActivityStats | None) -> str:
    if st is None or st.fastest_split_idx is None or not st.fastest_split_pace_s:
        return ""
    what = "km" if profile in ("running", "hiking") else "Abschnitt"

    def fmt(pace_s: float) -> str:
        if profile == "cycling":
            return fmt_speed_kmh(3600 / pace_s)
        return fmt_pace_100m(pace_s) if profile == "swimming" else fmt_pace_km(pace_s)

    text = f" Schnellster {what} {st.fastest_split_idx} ({fmt(st.fastest_split_pace_s)})"
    if st.slowest_split_idx is not None and st.slowest_split_pace_s:
        text += f", langsamster {what} {st.slowest_split_idx} ({fmt(st.slowest_split_pace_s)})"
    return text + "."


async def activity_splits_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    activity_id: int,
    kind: str = "distance",
    from_idx: int | None = None,
    to_idx: int | None = None,
) -> dict[str, Any]:
    if kind not in SPLIT_KINDS:
        raise ValueError(f"kind muss eines von {', '.join(SPLIT_KINDS)} sein")
    if from_idx is not None and to_idx is not None and from_idx > to_idx:
        raise ValueError("from_idx liegt nach to_idx")
    _, as_of = await _user_context(session, user_id)
    a, st = await _load_activity(session, user_id, activity_id)
    profile = a.sport_profile
    steps = await _load_steps(session, a.id)
    call = f'activity_splits(activity_id={a.id}, kind="{kind}"'
    ranged = from_idx is not None or to_idx is not None
    lo, hi = from_idx or 1, to_idx or 10_000
    quality = _pick(st, "quality", "partial")

    if kind == "steps":
        if not steps:
            raise ValueError(f"Aktivität {a.id} ist kein Workout, kind='steps' nicht verfügbar")
        shown_steps = [s for s in steps if lo <= s.exec_idx <= hi]
        cols, rows = _project(_STEP_COLS, _step_rows(profile, shown_steps))
        summary = f"Workout „{a.name or 'Workout'}“: {_step_groups(steps, with_pace=True)}."
        env = _envelope(summary, table(cols, rows), quality=quality)
        shrink = _row_shrinker(call, [s.exec_idx for s in shown_steps])
        return _finish(env, as_of=as_of, max_tokens=SPLITS_MAX_TOKENS, shrink=shrink)

    if kind == "distance" and profile not in _DISTANCE_COLS:
        raise ValueError(
            f"Für sport_profile={profile} gibt es keine Distanz-Splits, nur kind='lap'"
        )
    splits = list(
        (
            await session.execute(
                select(ActivitySplit)
                .where(ActivitySplit.activity_id == a.id, ActivitySplit.kind == kind)
                .order_by(ActivitySplit.idx)
            )
        ).scalars()
    )
    shown = [s for s in splits if lo <= s.idx <= hi]
    grouped = not ranged and len(shown) > _MAX_SPLIT_ROWS
    spans = _spans(shown, grouped)

    data: dict[str, Any]
    if kind == "lap":
        cols, rows = _project(_LAP_COLS, [_lap_row(profile, s) for s in shown])
        summary = f"{len(splits)} Runden." if splits else "Keine Runden aufgezeichnet."
        data = table(cols, rows)
    else:
        # running totals over all splits, so a range keeps the true kum_zeit
        cum: dict[int, tuple[float | None, float | None]] = {}
        acc_t: float | None = 0.0
        acc_m: float | None = 0.0
        for s in splits:
            acc_t = None if acc_t is None or s.timer_s is None else acc_t + s.timer_s
            acc_m = None if acc_m is None or s.distance_m is None else acc_m + s.distance_m
            cum[s.idx] = (acc_t, acc_m)
        row_dicts = []
        for sp in spans:
            first_end = cum[sp.first][1]
            first_dist = next(s.distance_m for s in shown if s.idx == sp.first)
            start_m = None if first_end is None or first_dist is None else first_end - first_dist
            row_dicts.append(
                _distance_row(
                    profile, sp, cum_s=cum[sp.last][0], start_m=start_m, end_m=cum[sp.last][1]
                )
            )
        cols, rows = _project(_DISTANCE_COLS[profile], row_dicts)
        noun = _SPLIT_NOUN[profile]
        summary = (
            f"{len(splits)} {noun}." + _extremes_text(profile, st)
            if splits
            else f"Keine {noun} (ohne Sekundendaten oder Distanz)."
        )
        unit = _BLOCK_UNIT_LABEL[profile] if grouped else _UNIT_LABEL[profile]
        data = {"unit": unit, **table(cols, rows)}
    if grouped:
        summary += f" Zusammengefasst in {len(spans)} Blöcken à {_BLOCK_SIZE}."
    elif ranged:
        summary += f" Gezeigt: {len(shown)} Zeilen ab {lo}."
    if steps:
        summary += (
            f" Als Workout gelaufen: Soll/Ist mit activity_splits(activity_id={a.id}, "
            'kind="steps").'
        )
    single = f"Einzelwerte: {call}, from_idx=1, to_idx={_MAX_SPLIT_ROWS})"
    env = _envelope(
        summary, data, quality=quality, truncated=grouped, next_hint=single if grouped else None
    )
    shrink = _row_shrinker(call, [sp.last for sp in spans])
    return _finish(env, as_of=as_of, max_tokens=SPLITS_MAX_TOKENS, shrink=shrink)


async def _prepared(session: AsyncSession, a: Activity) -> Prepared:
    stream = await load_stream(session, activity_id=a.id)
    if stream is None or len(stream.t_offset_s) < 2:
        raise ValueError(f"Keine Sekundendaten für Aktivität {a.id}, Analyse nicht möglich")
    loaded = await load_fit_messages(session, activity=a)
    events = list((loaded[0] if loaded is not None else {}).get("event_mesgs") or [])
    return prepare(stream, sport_profile=a.sport_profile, events=events)


def _window(prep: Prepared, ta: float, tb: float) -> tuple[list[int], list[float]]:
    idx = [i for i, tt in enumerate(prep.timer_t) if ta <= tt < tb]
    return idx, [prep.weights[i] for i in idx]


def _window_values(prep: Prepared, ta: float, tb: float) -> dict[str, Any]:
    idx, weights = _window(prep, ta, tb)
    hr = [prep.hr[i] for i in idx]
    active = [v for v, w in zip(hr, weights, strict=True) if v is not None and w > 0]
    da, db = interp(prep.timer_t, prep.distance, ta), interp(prep.timer_t, prep.distance, tb)
    alt = [prep.altitude_smooth[i] for i in idx]
    gain, loss = elevation_gain_loss(alt)
    has_alt = any(v is not None for v in alt)
    return {
        "distance": None if da is None or db is None else db - da,
        "timer": tb - ta,
        "hr_avg": _int(weighted_mean(hr, weights)),
        "hr_min": round(min(active)) if active else None,
        "hr_med": _int(weighted_median(hr, weights)),
        "hr_max": round(max(active)) if active else None,
        "gain": gain if has_alt else None,
        "loss": loss if has_alt else None,
        "cadence": _int(weighted_mean([prep.cadence_spm_or_rpm[i] for i in idx], weights)),
        "power": _int(weighted_mean([prep.power[i] for i in idx], weights)),
    }


def _segment_bounds(
    prep: Prepared,
    from_km: float | None,
    to_km: float | None,
    from_min: float | None,
    to_min: float | None,
) -> tuple[float, float, str]:
    by_km = from_km is not None or to_km is not None
    by_min = from_min is not None or to_min is not None
    if by_km == by_min:
        raise ValueError(
            "segment braucht einen Bereich in km oder Minuten (from_km/to_km oder "
            "from_min/to_min), nicht beides"
        )
    end_t = prep.timer_t[-1]
    if by_km:
        total = max((d for d in prep.distance if d is not None), default=None)
        if not total:
            raise ValueError("Ohne Distanzdaten sind nur Bereiche in Minuten möglich")
        a_km = from_km or 0.0
        b_km = min(to_km if to_km is not None else total / 1000, total / 1000)
        if a_km < 0 or b_km <= a_km:
            raise ValueError(f"Ungültiger km-Bereich (Distanz {fmt_distance(total)})")
        ta = (
            0.0
            if a_km == 0
            else interpolate_time_at_distance(prep.timer_t, prep.distance, a_km * 1000)
        )
        tb = interpolate_time_at_distance(prep.timer_t, prep.distance, b_km * 1000)
        if ta is None or tb is None:
            raise ValueError("km-Bereich liegt außerhalb der aufgezeichneten Distanz")
        return ta, tb, f"km {_dec(a_km, 2)}–{_dec(b_km, 2)}"
    a_min = from_min or 0.0
    b_min = min(to_min if to_min is not None else end_t / 60, end_t / 60)
    if a_min < 0 or b_min <= a_min:
        raise ValueError(f"Ungültiger Minutenbereich (Dauer {fmt_duration(end_t)})")
    return a_min * 60, b_min * 60, f"min {_num_label(a_min)}–{_num_label(round(b_min, 1))}"


async def _segment(
    session: AsyncSession,
    a: Activity,
    *,
    from_km: float | None,
    to_km: float | None,
    from_min: float | None,
    to_min: float | None,
) -> tuple[str, dict[str, Any]]:
    prep = await _prepared(session, a)
    ta, tb, label = _segment_bounds(prep, from_km, to_km, from_min, to_min)
    profile = a.sport_profile
    v = _window_values(prep, ta, tb)
    tempo = _tempo_with_unit(profile, v["distance"], v["timer"])
    tempo_col = _TEMPO_COL.get(profile, "tempo")
    row = {
        "bereich": label,
        "distanz": None if v["distance"] is None else fmt_distance(v["distance"]),
        "dauer": fmt_duration(v["timer"]),
        tempo_col: tempo,
        "hm_auf": _int(v["gain"]),
        "hm_ab": _int(v["loss"]),
        "hf_min": v["hr_min"],
        "hf_med": v["hr_med"],
        "hf_max": v["hr_max"],
        "kadenz": v["cadence"],
        "leistung": v["power"],
    }
    seg_cols = [tempo_col if c == "tempo" else c for c in _SEGMENT_COLS]
    cols, rows = _project(seg_cols, [row])
    head = row["dauer"] if row["distanz"] is None else f"{row['distanz']} in {row['dauer']}"
    parts = [head + (f" (Ø {tempo})" if tempo else "")]
    if v["hr_avg"] is not None:
        parts.append(f"Ø-HF {v['hr_avg']}")
    return f"Abschnitt {label}: " + ", ".join(parts) + ".", table(cols, rows)


def _compare_values(a: Activity, st: ActivityStats | None) -> dict[str, float | None]:
    distance = _pick(st, "distance_m", a.distance_m)
    timer = _pick(st, "timer_s", a.duration_s)
    hr_avg = _pick(st, "hr_avg", a.avg_hr)
    speed = distance / timer if distance and timer else None
    return {
        "distance": distance,
        "timer": timer,
        "hr_avg": hr_avg,
        "hr_max": _pick(st, "hr_max", a.max_hr),
        "cadence": _pick(st, "cadence_avg"),
        "power": _pick(st, "power_avg_w"),
        "gain": _pick(st, "elev_gain_m", a.elevation_gain_m),
        # spec C.4: metres per heartbeat = speed in m/min over mean HR
        "efficiency": speed * 60 / hr_avg if speed and hr_avg else None,
    }


def _tempo_value(profile: str, v: dict[str, float | None]) -> float | None:
    distance, timer = v["distance"], v["timer"]
    if not distance or not timer or profile == "generic":
        return None
    if profile == "cycling":
        return distance / timer * 3.6
    return timer / distance * (100 if profile == "swimming" else 1000)


def _compare_row(
    name: str,
    va: float | None,
    vb: float | None,
    fmt: Callable[[float], str],
    diff: Callable[[float], str],
) -> list[object] | None:
    if va is None and vb is None:
        return None
    return [
        name,
        None if va is None else fmt(va),
        None if vb is None else fmt(vb),
        None if va is None or vb is None else diff(va - vb),
    ]


def _compare_rows(
    profile: str, va: dict[str, float | None], vb: dict[str, float | None]
) -> list[list[object]]:
    unit = _cadence_unit(profile)
    if profile == "cycling":
        tempo: tuple[str, Callable[[float], str], Callable[[float], str]] = (
            "kmh", fmt_speed_kmh, lambda d: _signed(d, 1, " km/h")
        )
    elif profile == "swimming":
        tempo = ("pace_100m", fmt_pace_100m, lambda d: fmt_diff(d, "duration") + " /100 m")
    else:
        tempo = ("pace", fmt_pace_km, lambda d: fmt_diff(d, "pace"))

    def diff_int(d: float) -> str:
        return fmt_diff(d, "int")

    candidates = [
        _compare_row(
            "distanz", va["distance"], vb["distance"], fmt_distance,
            lambda d: fmt_diff(d, "distance"),
        ),
        _compare_row(tempo[0], _tempo_value(profile, va), _tempo_value(profile, vb), *tempo[1:]),
        _compare_row(
            "zeit", va["timer"], vb["timer"], fmt_duration, lambda d: fmt_diff(d, "duration")
        ),
        _compare_row("hf_avg", va["hr_avg"], vb["hr_avg"], _whole, diff_int),
        _compare_row("hf_max", va["hr_max"], vb["hr_max"], _whole, diff_int),
        _compare_row(
            "kadenz", va["cadence"], vb["cadence"], lambda v: f"{round(v)} {unit}",
            lambda d: _signed(d, 0, f" {unit}"),
        ),
        _compare_row(
            "leistung", va["power"], vb["power"], lambda v: f"{round(v)} W",
            lambda d: _signed(d, 0, " W"),
        ),
    ]
    if profile != "swimming":
        candidates += [
            _compare_row(
                "hm_auf", va["gain"], vb["gain"], lambda v: f"{round(v)} m",
                lambda d: _signed(d, 0, " m"),
            ),
            _compare_row(
                "effizienz", va["efficiency"], vb["efficiency"],
                lambda v: f"{_dec(v, 2)} m/Herzschlag", lambda d: _signed(d, 2),
            ),
        ]
    return [r for r in candidates if r is not None]


def _label(a: Activity, tz: str) -> tuple[str, str]:
    name = _short(a.name, 30) or _NOUNS[a.sport_profile][0]
    day = "" if a.start_at is None else a.start_at.astimezone(ZoneInfo(tz)).strftime("%d.%m.")
    return name, day


def _compare_summary(
    profile: str,
    names: tuple[tuple[str, str], tuple[str, str]],
    va: dict[str, float | None],
    vb: dict[str, float | None],
) -> str:
    head, other = (f"„{n}“ ({d})" if d else f"„{n}“" for n, d in names)
    ta, tb = _tempo_value(profile, va), _tempo_value(profile, vb)
    if ta is None or tb is None:
        text = f"{head} im Vergleich zu {other}"
    else:
        diff = ta - tb
        if profile == "cycling":
            amount, faster, zero = fmt_speed_kmh(abs(diff)), diff > 0, round(diff, 1) == 0
        else:
            fmt = fmt_pace_100m if profile == "swimming" else fmt_pace_km
            amount, faster, zero = fmt(abs(diff)), diff < 0, round(diff) == 0
        if zero:
            text = f"{head} war gleich schnell wie {other}"
        else:
            text = f"{head} war {amount} {'schneller' if faster else 'langsamer'} als {other}"
    ha, hb = va["hr_avg"], vb["hr_avg"]
    if ha is not None and hb is not None:
        d = round(ha - hb)
        text += (
            ", bei gleicher Ø-HF"
            if d == 0
            else f", bei {abs(d)} Schlägen {'höherer' if d > 0 else 'niedrigerer'} Ø-HF"
        )
    text += "."
    ea, eb = va["efficiency"], vb["efficiency"]
    if ea is not None and eb is not None and profile != "swimming":
        text += f" Effizienz {_dec(ea, 2)} vs. {_dec(eb, 2)} m pro Herzschlag."
    da, db = va["distance"], vb["distance"]
    if da and db and max(da, db) / min(da, db) > 1.5:
        text += (
            f" Hinweis: Distanzen stark unterschiedlich ({fmt_distance(da)} vs. "
            f"{fmt_distance(db)}), Vergleich nur eingeschränkt aussagekräftig."
        )
    return text


async def _compare(
    session: AsyncSession,
    *,
    user_id: UUID,
    tz: str,
    a: Activity,
    st: ActivityStats | None,
    other_activity_id: int | None,
) -> tuple[str, dict[str, Any]]:
    if other_activity_id is None:
        raise ValueError("compare braucht other_activity_id")
    b, sb = await _load_activity(session, user_id, other_activity_id)
    profile = a.sport_profile
    if b.sport_profile != profile:
        raise ValueError(f"compare nur bei gleichem Sportprofil ({profile} vs. {b.sport_profile})")
    va, vb = _compare_values(a, st), _compare_values(b, sb)
    names = (_label(a, tz), _label(b, tz))
    cols = [
        "kennzahl",
        *(f"{key}: {' '.join(p for p in (day, name) if p)}" for key, (name, day) in
          zip(("a", "b"), names, strict=True)),
        f"differenz a{MINUS}b",
    ]
    return _compare_summary(profile, names, va, vb), table(cols, _compare_rows(profile, va, vb))


def _drift_class(pct: float) -> str:
    if pct < 5:
        return "stabil (< 5 %)"
    if pct <= 10:
        return "moderat (5–10 %)"
    return "deutlich (> 10 %)"


async def _hr_drift(
    session: AsyncSession, a: Activity, st: ActivityStats | None
) -> tuple[str, dict[str, Any]]:
    profile = a.sport_profile
    note: str | None = "Entkopplung nur für Laufen und Rad anwendbar"
    value: float | None = None
    if profile in _DRIFT_PROFILES:
        prep = await _prepared(session, a)
        value, note = decoupling(prep, profile, None if st is None else st.pace_cv_pct)
    if value is None:
        reason = note or "nicht berechenbar"
        return (
            f"Entkopplung nicht berechenbar: {reason}.",
            {"entkopplung": None, "hinweis": reason},
        )
    end = prep.timer_t[-1]
    mid = DECOUPLING_WARMUP_S + (end - DECOUPLING_WARMUP_S) / 2
    use_power = profile == "cycling" and any(p is not None for p in prep.power)
    tempo_col = "kmh" if profile == "cycling" else "pace"
    cols = ["haelfte", "zeitraum", tempo_col, "hf_avg", "effizienz"]
    if use_power:
        cols.insert(3, "leistung")
    rows: list[dict[str, Any]] = []
    for half, (ta, tb) in enumerate(((DECOUPLING_WARMUP_S, mid), (mid, end)), start=1):
        v = _window_values(prep, ta, tb)
        ef, _ = efficiency(prep, ta, tb, use_power=use_power)
        if ef is None:
            ef_text = None
        elif use_power:
            ef_text = f"{_dec(ef, 2)} W/Schlag"
        else:
            ef_text = f"{_dec(ef * 60, 2)} m/Herzschlag"
        rows.append({
            "haelfte": str(half),
            "zeitraum": f"{fmt_duration(ta)}–{fmt_duration(tb)}",
            tempo_col: _tempo_with_unit(profile, v["distance"], v["timer"]),
            "leistung": None if v["power"] is None else f"{v['power']} W",
            "hf_avg": v["hr_avg"],
            "effizienz": ef_text,
        })
    klass = _drift_class(value)
    data = {
        "haelften": table(cols, [[r.get(c) for c in cols] for r in rows]),
        "entkopplung": fmt_percent(value),
        "einordnung": klass,
        "hinweis": "erste 10 min als Aufwärmphase ausgenommen; Einordnung nach Faustregel",
    }
    summary = (
        f"Aerobe Entkopplung {fmt_percent(value)}, {klass}. Effizienz 1. Hälfte "
        f"{rows[0]['effizienz']}, 2. Hälfte {rows[1]['effizienz']}."
    )
    return summary, data


def _curve_value(prep: Prepared, metric: str, ta: float, tb: float) -> float | None:
    if metric == "pace":
        # spec B.1: pace from distance and time, never averaged speed samples
        da = interp(prep.timer_t, prep.distance, ta)
        db = interp(prep.timer_t, prep.distance, tb)
        if da is None or db is None or db - da <= 0:
            return None
        return round((tb - ta) / (db - da) * 1000)
    source = {
        "hf": prep.hr,
        "hoehe": prep.altitude_smooth,
        "kadenz": prep.cadence_spm_or_rpm,
        "leistung": prep.power,
    }[metric]
    idx, weights = _window(prep, ta, tb)
    value = weighted_mean([source[i] for i in idx], weights)
    if value is None:
        return None
    return round(value, 1) if metric == "hoehe" else round(value)


async def _curve(
    session: AsyncSession, a: Activity, metric: str | None, points: int | None
) -> tuple[str, dict[str, Any]]:
    metric = metric or "hf"
    if metric not in CURVE_METRICS:
        raise ValueError(f"metric muss eines von {', '.join(CURVE_METRICS)} sein")
    n = max(10, min(int(points or 60), 60))
    prep = await _prepared(session, a)
    end = prep.timer_t[-1]
    width = end / n
    xs = [round((k + 0.5) * width / 60, 1) for k in range(n)]
    ys = [_curve_value(prep, metric, k * width, (k + 1) * width) for k in range(n)]
    values = [y for y in ys if y is not None]
    if not values:
        raise ValueError(f"Keine Daten für metric={metric} in Aktivität {a.id}")
    unit = {
        "hf": "bpm", "pace": "s/km", "hoehe": "m", "kadenz": _cadence_unit(a.sport_profile),
        "leistung": "W",
    }[metric]
    data: dict[str, Any] = {"metric": metric, "x_unit": "min", "y_unit": unit, "x": xs, "y": ys}
    if metric == "pace":
        data["y_format"] = "pace"
        span = f"{fmt_duration(min(values))}–{fmt_pace_km(max(values))}"
    else:
        span = f"{_num_label(min(values))}–{_num_label(max(values))} {unit}"
    summary = (
        f"Verlauf {_CURVE_LABEL[metric]} über {fmt_duration(end)}: {n} Punkte, Mittelwert je "
        f"{_dec(width / 60, 1)} min, Spanne {span}."
    )
    return summary, data


async def activity_analyze_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    activity_id: int,
    operation: str,
    other_activity_id: int | None = None,
    from_km: float | None = None,
    to_km: float | None = None,
    from_min: float | None = None,
    to_min: float | None = None,
    metric: str | None = None,
    points: int | None = None,
) -> dict[str, Any]:
    if operation not in ANALYZE_OPERATIONS:
        raise ValueError(f"operation muss eines von {', '.join(ANALYZE_OPERATIONS)} sein")
    tz, as_of = await _user_context(session, user_id)
    a, st = await _load_activity(session, user_id, activity_id)
    shrink: _Shrink = drop_last_row
    if operation == "segment":
        summary, data = await _segment(
            session, a, from_km=from_km, to_km=to_km, from_min=from_min, to_min=to_min
        )
    elif operation == "compare":
        summary, data = await _compare(
            session, user_id=user_id, tz=tz, a=a, st=st, other_activity_id=other_activity_id
        )
    elif operation == "hr_drift":
        summary, data = await _hr_drift(session, a, st)
        shrink = _no_shrink
    else:
        summary, data = await _curve(session, a, metric, points)
        shrink = _no_shrink
    env = _envelope(summary, data, quality=_pick(st, "quality", "partial"))
    return _finish(env, as_of=as_of, max_tokens=ANALYZE_MAX_TOKENS, shrink=shrink)


BEST_EFFORTS_MAX_TOKENS = 500
BEST_EFFORT_KEYS = tuple(BEST_EFFORT_DISTANCES)
BEST_EFFORT_PERIODS = ("all", "ytd", "12m", "90d", "custom")
BEST_EFFORT_COLS = ["distanz", "zeit", "pace", "datum", "aktivitaet", "abschnitt", "qualitaet"]
_EFFORT_LABEL = {
    "800m": "800 m", "1500m": "1.500 m", "3000m": "3.000 m", "5k": "5 km", "10k": "10 km",
    "hm": "HM", "m": "M", "50k": "50 km", "100k": "100 km",
}
_EFFORT_REACH = {
    "800m": "800 m", "1500m": "1,5 km", "3000m": "3 km", "5k": "5 km", "10k": "10 km",
    "hm": "21,1 km", "m": "42,2 km", "50k": "50 km", "100k": "100 km",
}


def _today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def _period_window(
    period: str, tz: str, from_date: str | None, to_date: str | None
) -> tuple[date | None, date | None, str]:
    today = _today(tz)
    if period == "all":
        return None, None, "gesamt"
    if period == "ytd":
        return date(today.year, 1, 1), today, str(today.year)
    if period == "12m":
        return today - timedelta(days=365), today, "letzte 12 Monate"
    if period == "90d":
        return today - timedelta(days=90), today, "letzte 90 Tage"
    if not from_date or not to_date:
        raise ValueError("period='custom' verlangt from_date und to_date")
    start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if start > end:
        raise ValueError("from_date liegt nach to_date")
    return start, end, f"{start:%d.%m.%Y}–{end:%d.%m.%Y}"


def _local_day(tz: str) -> ColumnElement[Any]:
    # spec A.8: the activity's own local start date
    return cast(func.coalesce(Activity.start_local, func.timezone(tz, Activity.start_at)), Date)


async def best_efforts_handler(
    session: AsyncSession,
    *,
    user_id: UUID,
    distances: Sequence[str] | None = None,
    period: str = "all",
    from_date: str | None = None,
    to_date: str | None = None,
    top_n: int = 1,
) -> dict[str, Any]:
    keys = list(dict.fromkeys(distances or BEST_EFFORT_KEYS))
    unknown = [k for k in keys if k not in BEST_EFFORT_DISTANCES]
    if unknown:
        raise ValueError(f"distances unbekannt: {', '.join(unknown)}")
    if period not in BEST_EFFORT_PERIODS:
        raise ValueError(f"period muss eines von {', '.join(BEST_EFFORT_PERIODS)} sein")
    top_n = max(1, min(int(top_n), 5))
    tz, as_of = await _user_context(session, user_id)
    start, end, period_label = _period_window(period, tz, from_date, to_date)

    conds: list[ColumnElement[bool]] = [
        Activity.user_id == user_id,
        Activity.deleted_at.is_(None),
        ActivityBestEffort.distance_key.in_(keys),
    ]
    if start is not None and end is not None:
        conds += [_local_day(tz) >= start, _local_day(tz) <= end]
    found = (
        await session.execute(
            select(ActivityBestEffort, Activity)
            .join(Activity, Activity.id == ActivityBestEffort.activity_id)
            .where(*conds)
            .order_by(ActivityBestEffort.duration_s, Activity.start_at)
        )
    ).all()
    by_key: dict[str, list[tuple[ActivityBestEffort, Activity]]] = {k: [] for k in keys}
    for effort, a in found:
        if len(by_key[effort.distance_key]) < top_n:
            by_key[effort.distance_key].append((effort, a))

    rows: list[list[object]] = []
    best: list[str] = []
    missing: list[str] = []
    for key in keys:
        label = _EFFORT_LABEL[key]
        if not by_key[key]:
            reason = f"kein GPS-Lauf ≥ {_EFFORT_REACH[key]} im Zeitraum"
            rows.append([label, "—", "—", "—", "—", "—", reason])
            missing.append(label)
            continue
        for rank, (effort, a) in enumerate(by_key[key], start=1):
            day = (
                "—" if a.start_at is None
                else fmt_datetime_local(a.start_at, tz).rsplit(" ", 1)[0]
            )
            name = _short(a.name, 30)
            section_end = effort.start_km + effort.distance_m / 1000
            row: list[object] = [
                label,
                fmt_duration(effort.duration_s),
                fmt_pace_km(effort.duration_s / effort.distance_m * 1000),
                day,
                f"#{a.id} {name}" if name else f"#{a.id}",
                f"km {_dec(effort.start_km, 1)}–{_dec(section_end, 1)}",
                effort.quality,
            ]
            rows.append([rank, *row] if top_n > 1 else row)
            if rank == 1:
                flag = ", eingeschränkt" if effort.quality == "partial" else ""
                best.append(f"{label} {row[1]} ({str(day)[3:]}{flag})")
    cols = ["rang", *BEST_EFFORT_COLS] if top_n > 1 else BEST_EFFORT_COLS
    if top_n > 1:
        # rank column stays empty on placeholder rows
        rows = [r if len(r) == len(cols) else ["–", *r] for r in rows]
    summary = f"Bestzeiten {period_label}: " + (" · ".join(best) if best else "keine")
    summary += "."
    if missing:
        summary += f" {', '.join(missing)}: kein GPS-Lauf dieser Länge."
    env = _envelope(
        summary, table(cols, rows), next_hint="Abschnitt ansehen: activity_get(activity_id=…)"
    )
    return _finish(env, as_of=as_of, max_tokens=BEST_EFFORTS_MAX_TOKENS, shrink=drop_last_row)
