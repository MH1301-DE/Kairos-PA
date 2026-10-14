from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

_SEMICIRCLE_FACTOR = 180.0 / 2_147_483_648


def _semicircle_to_deg(val: int | float) -> float:
    # garmin-fit-sdk returns raw semicircle integers for GPS fields
    if abs(val) > 360:
        return val * _SEMICIRCLE_FACTOR
    return float(val)


@dataclass(frozen=True)
class ChannelSpec:
    code: str
    unit: str
    storage: Literal["v4", "v8"]


STREAM_CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec("hr", "bpm", "v4"),
    ChannelSpec("cadence", "rpm", "v4"),
    ChannelSpec("speed_mps", "m/s", "v4"),
    ChannelSpec("distance_m", "m", "v4"),
    ChannelSpec("altitude_m", "m", "v4"),
    ChannelSpec("power_w", "W", "v4"),
    ChannelSpec("lat_deg", "deg", "v8"),
    ChannelSpec("lng_deg", "deg", "v8"),
    ChannelSpec("temp_c", "degC", "v4"),
)


@dataclass(frozen=True)
class StreamSet:
    start_at: datetime
    t_offset_s: list[int]
    channels: dict[str, list[float | None]]
    source: Literal["fit_zip", "fit_json"]


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _first(rec: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = _num(rec.get(key))
        if value is not None:
            return value
    return None


def _channel_values(rec: Mapping[str, object]) -> dict[str, float | None]:
    cadence = _num(rec.get("cadence"))
    if cadence is not None:
        cadence += _num(rec.get("fractional_cadence")) or 0.0
    lat = _num(rec.get("position_lat"))
    lng = _num(rec.get("position_long"))
    return {
        "hr": _num(rec.get("heart_rate")),
        "cadence": cadence,
        "speed_mps": _first(rec, "enhanced_speed", "speed"),
        "distance_m": _num(rec.get("distance")),
        "altitude_m": _first(rec, "enhanced_altitude", "altitude"),
        "power_w": _num(rec.get("power")),
        "lat_deg": None if lat is None else _semicircle_to_deg(lat),
        "lng_deg": None if lng is None else _semicircle_to_deg(lng),
        "temp_c": _num(rec.get("temperature")),
    }


def build_streams(
    records: Sequence[Mapping[str, object]],
    *,
    source: Literal["fit_zip", "fit_json"],
) -> StreamSet | None:
    start: datetime | None = None
    offsets: list[int] = []
    rows: list[dict[str, float | None]] = []
    for rec in records:
        ts = _timestamp(rec.get("timestamp"))
        if ts is None:
            continue
        if start is None:
            start = ts
        offset = int((ts - start).total_seconds())
        # duplicate or out-of-order second: first record wins
        if offsets and offset <= offsets[-1]:
            continue
        offsets.append(offset)
        rows.append(_channel_values(rec))
    if start is None:
        return None
    channels: dict[str, list[float | None]] = {}
    for spec in STREAM_CHANNELS:
        values = [row[spec.code] for row in rows]
        if any(v is not None for v in values):
            channels[spec.code] = values
    return StreamSet(start_at=start, t_offset_s=offsets, channels=channels, source=source)
