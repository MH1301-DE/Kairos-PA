from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from garminconnect import Garmin

from kairos.connectors.garmin.connector import GarminConnector
from kairos.connectors.types import Window
from kairos.routers.sync import _ALL_KINDS


def _window() -> Window:
    return Window(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC))


@pytest.mark.parametrize("kind", [k for k in _ALL_KINDS if k != "activity_fit"])
def test_fetch_calls_a_real_garminconnect_method(kind: str) -> None:
    # create_autospec raises AttributeError at call time if connector.py calls a
    # method that doesn't exist on the real garminconnect.Garmin class -- this is
    # exactly how spo2 broke (get_pulse_ox_data was renamed to get_spo2_data in
    # garminconnect >= 0.3.x) and only surfaced against a live backfill, not any
    # prior test. Catches renames/removals without needing a live account.
    garmin = create_autospec(Garmin, instance=True)
    connector = GarminConnector(garmin)

    connector.fetch(user_id=uuid4(), kind=kind, window=_window())


def test_activity_fit_fetch_calls_real_methods() -> None:
    garmin = create_autospec(Garmin, instance=True)
    garmin.get_activities_by_date.return_value = []

    connector = GarminConnector(garmin)
    envelope = connector.fetch(user_id=uuid4(), kind="activity_fit", window=_window())

    assert envelope.payload == {"activities": []}
