from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from kairos.agent.format import (
    cap_envelope,
    drop_last_row,
    fmt_date_short,
    fmt_datetime_local,
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
    span = f"zwischen {start:%d.%m.} und {end:%d.%m.%Y}"
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

    # spec A.8: the activity's own local start date
    local_day = cast(
        func.coalesce(Activity.start_local, func.timezone(tz, Activity.start_at)), Date
    )
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


def _workout_block(name: str | None, steps: Sequence[ActivityStepResult]) -> dict[str, Any]:
    rated = [s for s in steps if s.hit is not None]
    parts: list[str] = []
    for step_type in dict.fromkeys(s.step_type for s in rated):
        group = [s for s in rated if s.step_type == step_type]
        hits = sum(1 for s in group if s.hit)
        where = "HF-Bereich" if all(s.target_type == "hr_range" for s in group) else "Zielbereich"
        label = _STEP_LABEL.get(step_type, step_type)
        parts.append(f"{label} {hits}/{len(group)} im {where}")
    return {
        "name": name or "Workout",
        "bewertet": len(rated),
        "getroffen": sum(1 for s in rated if s.hit),
        "kurz": ", ".join(parts) if parts else "keine bewertbaren Schritte",
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
