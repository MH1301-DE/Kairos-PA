from __future__ import annotations

import pytest

from kairos.connectors.garmin.sport_profile import sport_profile_for


@pytest.mark.parametrize(
    ("type_key", "expected"),
    [
        ("running", "running"),
        ("treadmill_running", "running"),
        ("cycling", "cycling"),
        ("hiking", "hiking"),
        ("lap_swimming", "swimming"),
        ("strength_training", "generic"),
        ("hiit", "generic"),
        ("breathwork", "generic"),
        ("resort_skiing", "generic"),
    ],
)
def test_real_type_keys_map_without_parent_fallback(type_key: str, expected: str) -> None:
    assert sport_profile_for(type_key, None) == expected


def test_unknown_key_with_running_parent_falls_back_to_running() -> None:
    assert sport_profile_for("some_new_run_variant", 1) == "running"


def test_unknown_key_with_unrelated_or_missing_parent_is_generic() -> None:
    assert sport_profile_for("some_new_thing", 17) == "generic"
    assert sport_profile_for("some_new_thing", None) == "generic"
    assert sport_profile_for(None, None) == "generic"
