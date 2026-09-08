from __future__ import annotations

from datetime import UTC, datetime

from kairos.connectors.types import CanonicalRecord, JSONValue


def normalize_payload(*, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
    if kind == "hr_intraday":
        return _normalize_hr_intraday(payload)
    if kind == "sleep":
        return _normalize_sleep(payload)
    if kind == "stress":
        return _normalize_stress(payload)
    if kind == "body_battery":
        return _normalize_body_battery(payload)
    if kind == "hrv":
        return _normalize_hrv(payload)
    if kind == "respiration":
        return _normalize_respiration(payload)
    if kind == "spo2":
        return _normalize_spo2(payload)
    if kind == "daily_summary":
        return _normalize_daily_summary(payload)
    if kind == "activity_list":
        return _normalize_activity_list(payload)
    if kind == "activity_fit":
        return _normalize_activity_fit(payload)
    return []


# ── Wellness ──────────────────────────────────────────────────────────────────

_HR_MIN_PLAUSIBLE = 25.0
_HR_MAX_PLAUSIBLE = 230.0


def _normalize_hr_intraday(payload: JSONValue) -> list[CanonicalRecord]:
    # get_heart_rates -> {"heartRateValues": [[ts_ms, value], ...], ...}
    # NOT a list of {"timestamp": ..., "value": ...} dicts -- verified against a
    # real archived Garmin response; the dict shape never matched the live API
    # and silently dropped every reading (raw_payload had data, wellness_sample
    # stayed empty across a full 450-day backfill).
    if not isinstance(payload, dict):
        return []
    heart_rate_values = payload.get("heartRateValues")
    if not isinstance(heart_rate_values, list):
        return []
    records: list[CanonicalRecord] = []
    for item in heart_rate_values:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts_ms, value_raw = item[0], item[1]
        if not isinstance(ts_ms, int | float) or not isinstance(value_raw, int | float):
            continue
        occurred_at = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        quality = "ok" if _HR_MIN_PLAUSIBLE <= float(value_raw) <= _HR_MAX_PLAUSIBLE else "suspect"
        records.append(
            CanonicalRecord(
                record_type="wellness_sample",
                external_id=f"hr:{occurred_at.isoformat()}",
                occurred_at=occurred_at,
                data={"metric": "hr", "value": float(value_raw), "quality": quality},
            )
        )
    return records


def _normalize_stress(payload: JSONValue) -> list[CanonicalRecord]:
    # get_all_day_stress → {"stressValuesArray": [[ts_ms, stress_val], ...]}
    if not isinstance(payload, dict):
        return []
    values = payload.get("stressValuesArray")
    if not isinstance(values, list):
        return []
    records: list[CanonicalRecord] = []
    for item in values:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts_ms, val = item[0], item[1]
        if not isinstance(ts_ms, int | float) or not isinstance(val, int | float):
            continue
        if val < 0:  # Garmin uses -1/0 for unavailable readings
            continue
        occurred_at = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        records.append(CanonicalRecord(
            record_type="wellness_sample",
            external_id=f"stress:{occurred_at.isoformat()}",
            occurred_at=occurred_at,
            data={"metric": "stress", "value": float(val)},
        ))
    return records


def _normalize_body_battery(payload: JSONValue) -> list[CanonicalRecord]:
    # get_body_battery → list of {"bodyBatteryValuesArray": [[startGMT_ms, endGMT_ms, status, startLocal_ms, value], ...]}
    if not isinstance(payload, list):
        return []
    records: list[CanonicalRecord] = []
    for day in payload:
        if not isinstance(day, dict):
            continue
        values = day.get("bodyBatteryValuesArray")
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, list) or len(item) < 5:
                continue
            ts_ms, battery_val = item[0], item[4]
            if not isinstance(ts_ms, int | float) or not isinstance(battery_val, int | float):
                continue
            occurred_at = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
            records.append(CanonicalRecord(
                record_type="wellness_sample",
                external_id=f"body_battery:{occurred_at.isoformat()}",
                occurred_at=occurred_at,
                data={"metric": "body_battery", "value": float(battery_val)},
            ))
    return records


def _normalize_hrv(payload: JSONValue) -> list[CanonicalRecord]:
    # get_hrv_data → {"hrvReadings": [{"hrv5MinAvg": 45, "startTimeGMT": "..."}, ...]}
    if not isinstance(payload, dict):
        return []
    readings = payload.get("hrvReadings")
    if not isinstance(readings, list):
        return []
    records: list[CanonicalRecord] = []
    for item in readings:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("startTimeGMT")
        val = item.get("hrv5MinAvg")
        if not isinstance(ts_raw, str) or not isinstance(val, int | float):
            continue
        occurred_at = _parse_datetime_utc(ts_raw)
        if occurred_at is None:
            continue
        records.append(CanonicalRecord(
            record_type="wellness_sample",
            external_id=f"hrv_5min:{occurred_at.isoformat()}",
            occurred_at=occurred_at,
            data={"metric": "hrv_5min", "value": float(val)},
        ))
    return records


def _normalize_respiration(payload: JSONValue) -> list[CanonicalRecord]:
    # get_respiration_data → {"respirationValues": [[ts_ms, value], ...]}
    if not isinstance(payload, dict):
        return []
    values = payload.get("respirationValues") or payload.get("respirationValuesArray")
    if not isinstance(values, list):
        return []
    records: list[CanonicalRecord] = []
    for item in values:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts_ms, val = item[0], item[1]
        if not isinstance(ts_ms, int | float) or not isinstance(val, int | float):
            continue
        if val <= 0:
            continue
        occurred_at = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        records.append(CanonicalRecord(
            record_type="wellness_sample",
            external_id=f"respiration:{occurred_at.isoformat()}",
            occurred_at=occurred_at,
            data={"metric": "respiration", "value": float(val)},
        ))
    return records


def _normalize_spo2(payload: JSONValue) -> list[CanonicalRecord]:
    # get_pulse_ox_data — two possible shapes:
    # a) continuous: {"continuousReadingDTOList": [{"startGMT": "...", "value": 97}]}
    # b) hourly:     {"spO2HourlyAverages": {"spO2HourlyAverages": [{"startGMT": "...", "spO2Value": 97}]}}
    if not isinstance(payload, dict):
        return []
    records: list[CanonicalRecord] = []

    continuous = payload.get("continuousReadingDTOList")
    if isinstance(continuous, list):
        for item in continuous:
            if not isinstance(item, dict):
                continue
            ts_raw = item.get("startGMT")
            val = item.get("value")
            if not isinstance(ts_raw, str) or not isinstance(val, int | float):
                continue
            occurred_at = _parse_datetime_utc(ts_raw)
            if occurred_at is None:
                continue
            records.append(CanonicalRecord(
                record_type="wellness_sample",
                external_id=f"spo2:{occurred_at.isoformat()}",
                occurred_at=occurred_at,
                data={"metric": "spo2", "value": float(val)},
            ))
        return records

    hourly_wrapper = payload.get("spO2HourlyAverages")
    if isinstance(hourly_wrapper, dict):
        hourly = hourly_wrapper.get("spO2HourlyAverages")
        if isinstance(hourly, list):
            for item in hourly:
                if not isinstance(item, dict):
                    continue
                ts_raw = item.get("startGMT")
                val = item.get("spO2Value")
                if not isinstance(ts_raw, str) or not isinstance(val, int | float):
                    continue
                occurred_at = _parse_datetime_utc(ts_raw)
                if occurred_at is None:
                    continue
                records.append(CanonicalRecord(
                    record_type="wellness_sample",
                    external_id=f"spo2:{occurred_at.isoformat()}",
                    occurred_at=occurred_at,
                    data={"metric": "spo2", "value": float(val)},
                ))
    return records


# ── Daily summary ─────────────────────────────────────────────────────────────

def _normalize_daily_summary(payload: JSONValue) -> list[CanonicalRecord]:
    # get_stats → large dict; store as-is in daily_summary table
    if not isinstance(payload, dict):
        return []
    date_str = payload.get("calendarDate") or payload.get("statisticsStartDate")
    if not isinstance(date_str, str):
        return []
    try:
        day_dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return []
    return [CanonicalRecord(
        record_type="daily_summary",
        external_id=f"daily:{date_str[:10]}",
        occurred_at=day_dt,
        data={"summary_type": "garmin_stats", **{k: v for k, v in payload.items()
                                                  if isinstance(v, int | float | str | bool | type(None))}},
    )]


# ── Activities ────────────────────────────────────────────────────────────────

def _normalize_activity_list(payload: JSONValue) -> list[CanonicalRecord]:
    # get_activities_by_date → list of activity summary dicts
    if not isinstance(payload, list):
        return []
    records: list[CanonicalRecord] = []
    for act in payload:
        if not isinstance(act, dict):
            continue
        activity_id = act.get("activityId")
        if activity_id is None:
            continue
        start_raw = act.get("startTimeGMT") or act.get("startTimeLocal")
        occurred_at = _parse_datetime_utc(str(start_raw)) if isinstance(start_raw, str) else None

        activity_type_obj = act.get("activityType")
        sport = (
            activity_type_obj.get("typeKey")
            if isinstance(activity_type_obj, dict)
            else act.get("activityType")
        )

        end_at = None
        if occurred_at is not None:
            duration = act.get("duration") or act.get("elapsedDuration")
            if isinstance(duration, int | float) and duration > 0:
                from datetime import timedelta
                end_at = occurred_at + timedelta(seconds=duration)

        records.append(CanonicalRecord(
            record_type="activity",
            external_id=str(activity_id),
            occurred_at=occurred_at,
            data={
                "name": act.get("activityName"),
                "sport": sport,
                "activity_type": act.get("activityType") if isinstance(act.get("activityType"), str) else None,
                "end_at": end_at.isoformat() if end_at else None,
                "distance_m": act.get("distance"),
                "duration_s": act.get("duration") or act.get("elapsedDuration"),
                "avg_hr": act.get("averageHR"),
                "max_hr": act.get("maxHR"),
                "elevation_gain_m": act.get("elevationGain"),
                "calories": act.get("calories"),
            },
        ))
    return records


# FIT field name → (metric_code, apply_semicircle_conversion)
_FIT_FIELDS: dict[str, tuple[str, bool]] = {
    "heart_rate":         ("hr",          False),
    "cadence":            ("cadence",     False),
    "enhanced_speed":     ("speed_mps",   False),
    "speed":              ("speed_mps",   False),
    "power":              ("power_w",     False),
    "enhanced_altitude":  ("altitude_m",  False),
    "altitude":           ("altitude_m",  False),
    "position_lat":       ("lat_deg",     True),
    "position_long":      ("lng_deg",     True),
    "temperature":        ("temp_c",      False),
}
# Skip basic field if the enhanced version is present in the same record
_ENHANCED_SUPERSEDES = {"speed", "altitude"}


def _normalize_activity_fit(payload: JSONValue) -> list[CanonicalRecord]:
    # connector._fetch_activity_fits → {"activities": [{"activity_id": "...", "records": [...], ...}]}
    if not isinstance(payload, dict):
        return []
    activities = payload.get("activities")
    if not isinstance(activities, list):
        return []

    canonical: list[CanonicalRecord] = []
    for act in activities:
        if not isinstance(act, dict) or "error" in act:
            continue
        activity_id = act.get("activity_id")
        if not isinstance(activity_id, str):
            continue
        records = act.get("records") or []
        if not isinstance(records, list):
            continue

        for rec in records:
            if not isinstance(rec, dict):
                continue
            ts_raw = rec.get("timestamp")
            occurred_at = _parse_datetime_utc(str(ts_raw)) if isinstance(ts_raw, str) else None
            if occurred_at is None:
                continue

            has_enhanced_speed = isinstance(rec.get("enhanced_speed"), int | float)
            has_enhanced_alt = isinstance(rec.get("enhanced_altitude"), int | float)

            for field, (metric_code, is_semicircle) in _FIT_FIELDS.items():
                if field == "speed" and has_enhanced_speed:
                    continue
                if field == "altitude" and has_enhanced_alt:
                    continue
                raw_val = rec.get(field)
                if not isinstance(raw_val, int | float):
                    continue
                value = _semicircle_to_deg(raw_val) if is_semicircle else float(raw_val)
                canonical.append(CanonicalRecord(
                    record_type="activity_record",
                    external_id=f"{activity_id}:{metric_code}:{occurred_at.isoformat()}",
                    occurred_at=occurred_at,
                    data={
                        "activity_external_id": activity_id,
                        "metric": metric_code,
                        "value": value,
                    },
                ))
    return canonical


# ── Helpers ───────────────────────────────────────────────────────────────────

_SEMICIRCLE_FACTOR = 180.0 / 2_147_483_648


def _semicircle_to_deg(val: int | float) -> float:
    # garmin-fit-sdk returns raw semicircle integers for GPS fields
    if abs(val) > 360:
        return val * _SEMICIRCLE_FACTOR
    return float(val)


def _normalize_sleep(payload: JSONValue) -> list[CanonicalRecord]:
    # get_sleep_data -> no top-level "sleepId"; the unique id is
    # dailySleepDTO.id (an int, epoch ms -- same value as
    # sleepStartTimestampGMT). sleepStart/EndTimestampGMT are epoch-ms ints,
    # not ISO strings. Verified against a real archived Garmin response --
    # both original assumptions were wrong and made every sleep_session
    # write a silent no-op across a full 450-day backfill.
    if not isinstance(payload, dict):
        return []

    daily_sleep = payload.get("dailySleepDTO")
    if not isinstance(daily_sleep, dict):
        return []

    sleep_id_raw = daily_sleep.get("id")
    start_raw = daily_sleep.get("sleepStartTimestampGMT")
    end_raw = daily_sleep.get("sleepEndTimestampGMT")
    duration_raw = daily_sleep.get("sleepTimeSeconds")
    day_raw = daily_sleep.get("calendarDate")

    if not isinstance(sleep_id_raw, int | float):
        return []
    if not isinstance(start_raw, int | float) or not isinstance(end_raw, int | float):
        return []
    if not isinstance(duration_raw, int):
        return []
    if not isinstance(day_raw, str):
        return []

    start_at = datetime.fromtimestamp(start_raw / 1000, tz=UTC)
    end_at = datetime.fromtimestamp(end_raw / 1000, tz=UTC)

    return [
        CanonicalRecord(
            record_type="sleep_session",
            external_id=str(int(sleep_id_raw)),
            occurred_at=start_at,
            data={
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "duration_seconds": duration_raw,
                "day": day_raw,
            },
        )
    ]


def _parse_datetime_utc(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    # handle "YYYY-MM-DD HH:MM:SS" format without timezone
    if len(normalized) == 19 and "T" not in normalized:
        normalized = normalized.replace(" ", "T") + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)



