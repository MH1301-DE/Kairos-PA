from __future__ import annotations

import inspect

import pytest
from garminconnect import Garmin

# Garmin methods the activities & workouts spec (AP 0, step 1) builds on, with the
# parameter names its services will pass -- a rename in a garminconnect upgrade
# should fail here, not against the live account.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "upload_running_workout": ("workout",),
    "upload_cycling_workout": ("workout",),
    "get_workouts": ("start", "limit"),
    "get_workout_by_id": ("workout_id",),
    "update_workout": ("workout_id", "workout_json"),
    "delete_workout": ("workout_id",),
    "schedule_workout": ("workout_id", "date_str"),
    "unschedule_workout": ("scheduled_workout_id",),
    "get_scheduled_workouts": ("year", "month"),
    "get_scheduled_workout_by_id": ("scheduled_workout_id",),
    "get_activity_types": (),
    "set_activity_name": ("activity_id", "title"),
    "delete_activity": ("activity_id",),
}


@pytest.mark.parametrize(("name", "params"), sorted(_REQUIRED.items()))
def test_garminconnect_has_workout_method(name: str, params: tuple[str, ...]) -> None:
    method = getattr(Garmin, name, None)
    assert method is not None, f"garminconnect.Garmin.{name} is missing"
    signature = list(inspect.signature(method).parameters)
    assert signature[1:] == list(params)
