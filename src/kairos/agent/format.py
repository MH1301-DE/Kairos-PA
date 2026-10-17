from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

MINUS = "\u2212"
CHARS_PER_TOKEN = 3.7
_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _de(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _clock(seconds: float) -> str:
    total = round(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_distance(m: float) -> str:
    if round(m) < 1000:
        return f"{round(m)} m"
    return f"{_de(m / 1000, 2)} km"


def fmt_duration(s: float) -> str:
    return _clock(s)


def fmt_pace_km(s_per_km: float) -> str:
    return f"{_clock(s_per_km)} /km"


def fmt_pace_100m(s_per_100m: float) -> str:
    return f"{_clock(s_per_100m)} /100 m"


def fmt_speed_kmh(kmh: float) -> str:
    return f"{_de(kmh, 1)} km/h"


def fmt_percent(value: float, decimals: int = 1) -> str:
    return f"{_de(value, decimals)} %"


def fmt_datetime_local(dt: datetime, tz: str) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    return f"{_WEEKDAYS[local.weekday()]} {local:%d.%m.%Y %H:%M}"


def fmt_date_short(dt: datetime, tz: str) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    return f"{_WEEKDAYS[local.weekday()]} {local:%d.%m. %H:%M}"


def fmt_diff(value: float, kind: Literal["pace", "duration", "distance", "int"]) -> str:
    if kind == "pace":
        body, rounded = _clock(abs(value)) + " /km", float(round(value))
    elif kind == "duration":
        body, rounded = _clock(abs(value)), float(round(value))
    elif kind == "distance":
        body = fmt_distance(abs(value))
        rounded = round(value / 1000, 2) if abs(value) >= 1000 else float(round(value))
    else:
        body, rounded = str(abs(round(value))), float(round(value))
    if rounded == 0:
        return body
    return f"{'+' if value > 0 else MINUS}{body}"


def table(cols: list[str], rows: list[list[object]]) -> dict[str, object]:
    return {"cols": cols, "rows": rows}


def drop_last_row(env: dict[str, Any]) -> dict[str, Any] | None:
    data = env.get("data")
    if not isinstance(data, dict) or not data.get("rows"):
        return None
    rows = data["rows"]
    data["rows"] = rows[:-1]
    env["meta"]["row_count"] = len(rows) - 1
    return env


def _tokens(env: dict[str, Any]) -> float:
    return len(json.dumps(env, ensure_ascii=False)) / CHARS_PER_TOKEN


def cap_envelope(
    env: dict[str, Any],
    *,
    max_tokens: int,
    shrink: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    while _tokens(env) > max_tokens:
        smaller = shrink(env)
        if smaller is None:
            break
        env = smaller
        env["meta"]["truncated"] = True
    return env
