from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"

# typeKeys that occur in the operator's real activity history (2026-10-07)
_REAL_TYPE_KEYS = {
    "running": "all",
    "treadmill_running": "running",
    "hiking": "all",
    "lap_swimming": "swimming",
    "cycling": "all",
    "strength_training": "fitness_equipment",
    "hiit": "fitness_equipment",
    "breathwork": "other",
    "resort_skiing": "winter_sports",
}


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _executable_steps(workout: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(steps: list[dict[str, Any]]) -> None:
        for s in steps:
            if s["type"] == "RepeatGroupDTO":
                walk(s["workoutSteps"])
            else:
                out.append(s)

    walk(workout["workoutSegments"][0]["workoutSteps"])
    return out


def test_custom_ranges_are_sibling_values_in_raw_units() -> None:
    steps = _executable_steps(_load("workout_running_threshold.json"))
    hr = next(s for s in steps if s["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone")
    pace = next(s for s in steps if s["targetType"]["workoutTargetTypeKey"] == "pace.zone")
    # bpm range, not a watch zone
    assert hr["zoneNumber"] is None
    assert (hr["targetValueOne"], hr["targetValueTwo"]) == (100.0, 150.0)
    # pace in m/s; Garmin keeps the order it was sent in
    assert 3.0 < pace["targetValueTwo"] < pace["targetValueOne"] < 4.0


def test_zone_targets_round_trip_via_zone_number() -> None:
    run = _executable_steps(_load("workout_running_roundtrip.json"))
    bike = _executable_steps(_load("workout_cycling_roundtrip.json"))
    assert (run[0]["zoneNumber"], run[0]["targetValueOne"]) == (2, None)
    assert run[0]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert bike[0]["zoneNumber"] == 2
    assert bike[0]["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert run[-1]["endCondition"]["conditionTypeKey"] == "lap.button"
    assert run[-1]["endConditionValue"] is None
    assert [s["targetType"]["workoutTargetTypeKey"] for s in bike[1:]] == [
        "power.zone",
        "speed.zone",
        "cadence",
    ]


def test_update_keeps_id_and_targets() -> None:
    before = _load("workout_running_roundtrip.json")
    after = _load("workout_running_after_update.json")
    assert after["workoutId"] == before["workoutId"]
    assert after["workoutSegments"][0]["workoutSteps"][1]["numberOfIterations"] == 4
    hr_range = _executable_steps(after)[-2]
    assert (hr_range["targetValueOne"], hr_range["targetValueTwo"]) == (130.0, 145.0)


def test_schedule_id_comes_from_the_schedule_response() -> None:
    response = _load("schedule_workout_response.json")
    assert isinstance(response["workoutScheduleId"], int)
    assert response["calendarDate"] == "2026-12-30"


def test_month_calendar_mixes_item_types() -> None:
    items = _load("scheduled_workouts_month.json")["calendarItems"]
    workouts = [i for i in items if i["itemType"] == "workout"]
    coach = [i for i in items if i["itemType"] == "fbtAdaptiveWorkout"]
    # own workouts carry schedule id + workoutId and only a date, no time of day
    assert all(i["id"] and i["workoutId"] and i["startTimestampLocal"] is None for i in workouts)
    # Garmin Coach items have no workoutId -- not part of the workout library
    assert coach and all(i["workoutId"] is None and i["trainingPlanId"] for i in coach)


def test_real_type_keys_resolve_to_their_parent() -> None:
    types = _load("activity_types.json")
    by_key = {t["typeKey"]: t for t in types}
    by_id = {t["typeId"]: t["typeKey"] for t in types}
    for key, parent in _REAL_TYPE_KEYS.items():
        assert by_id[by_key[key]["parentTypeId"]] == parent
