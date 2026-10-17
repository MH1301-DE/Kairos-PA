"""Concrete GarminConnector — maps kind strings to garminconnect API calls."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from kairos.connectors.garmin.fit_decoder import decode_fit_zip, records_to_json
from kairos.connectors.garmin.normalize import normalize_payload
from kairos.connectors.types import (
    CanonicalRecord,
    JSONValue,
    RawPayloadEnvelope,
    Window,
    WriteResult,
)


class GarminConnector:
    connector_id = "garmin"

    def __init__(self, garmin: Any) -> None:
        # garmin is an authenticated garminconnect.Garmin instance
        self._garmin = garmin

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id
        d0 = window.start.date().isoformat()
        d1 = window.end.date().isoformat()
        g = self._garmin

        if kind == "hr_intraday":
            payload: JSONValue = g.get_heart_rates(d0)
        elif kind == "sleep":
            payload = g.get_sleep_data(d0)
        elif kind == "stress":
            payload = g.get_all_day_stress(d0)
        elif kind == "body_battery":
            payload = g.get_body_battery(d0, d1)
        elif kind == "hrv":
            payload = g.get_hrv_data(d0)
        elif kind == "respiration":
            payload = g.get_respiration_data(d0)
        elif kind == "spo2":
            # get_pulse_ox_data was renamed to get_spo2_data in garminconnect >= 0.3.x
            payload = g.get_spo2_data(d0)
        elif kind == "daily_summary":
            payload = g.get_stats(d0)
        elif kind == "activity_list":
            payload = g.get_activities_by_date(d0, d1)
        elif kind == "activity_fit":
            payload = self._fetch_activity_fits(d0, d1)
        else:
            raise ValueError(f"Unknown Garmin kind: {kind!r}")

        return RawPayloadEnvelope(window=window, payload=payload)

    def normalize(self, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
        return normalize_payload(kind=kind, payload=payload)

    def write_back(
        self, user_id: UUID, kind: str, records: Sequence[CanonicalRecord]
    ) -> WriteResult:
        del user_id, kind, records
        return WriteResult(written=0)

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_activity_fits(self, start: str, end: str) -> JSONValue:
        try:
            gc = importlib.import_module("garminconnect")
            dl_fmt = gc.Garmin.ActivityDownloadFormat.ORIGINAL
        except (ImportError, AttributeError):
            return {"activities": []}

        activities = self._garmin.get_activities_by_date(start, end)
        result: list[JSONValue] = []
        for act in activities:
            activity_id = act.get("activityId")
            if activity_id is None:
                continue
            try:
                zip_bytes: bytes = self._garmin.download_activity(activity_id, dl_fmt=dl_fmt)
                messages = decode_fit_zip(zip_bytes)
                result.append({
                    "activity_id": str(activity_id),
                    "records": cast(JSONValue, records_to_json(messages.get("record_mesgs", []))),
                    "sessions": cast(JSONValue, records_to_json(messages.get("session_mesgs", []))),
                    "laps": cast(JSONValue, records_to_json(messages.get("lap_mesgs", []))),
                })
            except Exception as exc:
                # one failed FIT must not abort the whole day window
                result.append({"activity_id": str(activity_id), "error": str(exc)})

        return {"activities": result}
