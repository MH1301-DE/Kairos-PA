"""Concrete GarminConnector — maps kind strings to garminconnect API calls."""

from __future__ import annotations

import hashlib
import importlib
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from kairos.connectors.garmin.normalize import normalize_payload
from kairos.connectors.types import (
    CanonicalRecord,
    JSONValue,
    RawFile,
    RawPayloadEnvelope,
    Window,
    WriteResult,
)


class GarminConnector:
    connector_id = "garmin"

    def __init__(self, garmin: Any, *, fit_download_pause_s: float = 0.0) -> None:
        # garmin is an authenticated garminconnect.Garmin instance
        self._garmin = garmin
        self._fit_download_pause_s = fit_download_pause_s

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id
        d0 = window.start.date().isoformat()
        d1 = window.end.date().isoformat()
        g = self._garmin
        files: tuple[RawFile, ...] = ()

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
            payload, files = self._fetch_activity_fits(d0, d1, window)
        else:
            raise ValueError(f"Unknown Garmin kind: {kind!r}")

        return RawPayloadEnvelope(window=window, payload=payload, files=files)

    def normalize(self, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
        return normalize_payload(kind=kind, payload=payload)

    def write_back(
        self, user_id: UUID, kind: str, records: Sequence[CanonicalRecord]
    ) -> WriteResult:
        del user_id, kind, records
        return WriteResult(written=0)

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_activity_fits(
        self, start: str, end: str, window: Window
    ) -> tuple[JSONValue, tuple[RawFile, ...]]:
        try:
            gc = importlib.import_module("garminconnect")
            dl_fmt = gc.Garmin.ActivityDownloadFormat.ORIGINAL
        except (ImportError, AttributeError):
            return {"activities": []}, ()

        activities = self._garmin.get_activities_by_date(start, end)
        manifest: list[JSONValue] = []
        files: list[RawFile] = []
        attempted = False
        for act in activities:
            activity_id = act.get("activityId")
            if activity_id is None:
                continue
            if attempted and self._fit_download_pause_s > 0:
                time.sleep(self._fit_download_pause_s)
            attempted = True
            try:
                zip_bytes: bytes = self._garmin.download_activity(activity_id, dl_fmt=dl_fmt)
            except Exception as exc:
                # one failed FIT must not abort the whole day window
                manifest.append({"activity_id": str(activity_id), "error": str(exc)})
                continue
            files.append(RawFile(
                kind="activity_fit_file",
                key=str(activity_id),
                window_start=_start_utc(act.get("startTimeGMT")) or window.start,
                content=zip_bytes,
                payload_format="fit_zip",
            ))
            manifest.append({
                "activity_id": str(activity_id),
                "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            })

        return {"activities": manifest}, tuple(files)


def _start_utc(value: object) -> datetime | None:
    # Garmin's startTimeGMT is "YYYY-MM-DD HH:MM:SS" in UTC
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
