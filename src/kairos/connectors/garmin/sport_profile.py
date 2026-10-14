from __future__ import annotations

import json
from functools import cache
from importlib.resources import files

_BY_TYPE_KEY: dict[str, str] = {
    **dict.fromkeys(
        ("running", "trail_running", "treadmill_running", "track_running"), "running"
    ),
    **dict.fromkeys(
        (
            "cycling",
            "road_biking",
            "mountain_biking",
            "gravel_cycling",
            "indoor_cycling",
            "virtual_ride",
        ),
        "cycling",
    ),
    **dict.fromkeys(("lap_swimming", "open_water_swimming"), "swimming"),
    **dict.fromkeys(("hiking", "mountaineering", "walking"), "hiking"),
}
_PARENT_FALLBACK = {"running", "cycling", "swimming"}


@cache
def _type_key_by_id() -> dict[int, str]:
    raw = files("kairos.connectors.garmin").joinpath("activity_types.json").read_text("utf-8")
    return {int(t["typeId"]): str(t["typeKey"]) for t in json.loads(raw)}


def sport_profile_for(type_key: str | None, parent_type_id: int | None) -> str:
    if type_key in _BY_TYPE_KEY:
        return _BY_TYPE_KEY[type_key]
    parent_key = _type_key_by_id().get(parent_type_id) if parent_type_id is not None else None
    if parent_key in _PARENT_FALLBACK:
        return _BY_TYPE_KEY[parent_key]
    return "generic"
