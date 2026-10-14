"""Export one activity as an anonymized regression fixture (tests/fixtures/activities/).

Read-only against the database. Usage:
  .venv/Scripts/python scripts/export_activity_fixture.py --user-id <uuid> --activity-id 252 \
      --name run_autolap_1km_9k --lat-offset <deg> --lng-offset <deg>
The GPS offset is not stored anywhere; use the same values for all fixtures of one export.
See tests/fixtures/activities/README.md for the schema.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from kairos.activities.fit_archive import load_fit_messages
from kairos.activities.stream_repository import load_stream
from kairos.db.models import Activity, RawPayload
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory

SCHEMA_VERSION = 1
OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "activities"

MESSAGE_KINDS = (
    "session_mesgs",
    "lap_mesgs",
    "length_mesgs",
    "event_mesgs",
    "split_mesgs",
    "workout_mesgs",
    "workout_step_mesgs",
)
DATETIME_KEYS = frozenset({"timestamp", "start_time", "end_time"})
_SEMICIRCLES_PER_DEG = 2**31 / 180.0

ACTIVITY_COLUMNS = (
    "sport",
    "sport_profile",
    "garmin_type_id",
    "garmin_parent_type_id",
    "start_at",
    "end_at",
    "start_local",
    "utc_offset_min",
    "moving_duration_s",
    "avg_speed_mps",
    "lap_count",
    "garmin_training_load",
    "garmin_vo2max",
    "distance_m",
    "duration_s",
    "avg_hr",
    "max_hr",
    "elevation_gain_m",
    "calories",
)
LIST_ITEM_KEYS = (
    "startTimeGMT",
    "startTimeLocal",
    "distance",
    "duration",
    "elapsedDuration",
    "movingDuration",
    "averageSpeed",
    "maxSpeed",
    "averageHR",
    "maxHR",
    "averageRunningCadenceInStepsPerMinute",
    "maxRunningCadenceInStepsPerMinute",
    "averageBikingCadenceInRevPerMinute",
    "averageSwimCadenceInStrokesPerMinute",
    "elevationGain",
    "elevationLoss",
    "minElevation",
    "maxElevation",
    "avgPower",
    "maxPower",
    "normPower",
    "lapCount",
    "steps",
    "calories",
    "poolLength",
    "activeLengths",
    "averageSwolf",
    "avgStrokes",
    "totalNumberOfStrokes",
)
LIST_ITEM_PREFIXES = ("fastestSplit_", "hrTimeInZone_")


def _shift_semicircles(key: str, value: Any, lat_off: float, lng_off: float) -> Any:
    if not isinstance(value, int) or isinstance(value, bool):
        return value
    if key.endswith("_lat"):
        return value + round(lat_off * _SEMICIRCLES_PER_DEG)
    if key.endswith("_long"):
        return value + round(lng_off * _SEMICIRCLES_PER_DEG)
    return value


def _clean_message(msg: dict[Any, Any], lat_off: float, lng_off: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in msg.items():
        # numeric keys are undocumented fields; some carry raw positions
        if not isinstance(key, str) or key.isdigit() or "serial" in key:
            continue
        if isinstance(value, datetime):
            if key not in DATETIME_KEYS:
                raise ValueError(f"unexpected datetime field {key!r}")
            out[key] = value.isoformat()
        else:
            out[key] = _shift_semicircles(key, value, lat_off, lng_off)
    return out


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _list_item_subset(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item[k] for k in LIST_ITEM_KEYS if k in item}
    out.update({k: v for k, v in item.items() if k.startswith(LIST_ITEM_PREFIXES)})
    atype = item.get("activityType")
    if isinstance(atype, dict):
        out["activityType"] = {
            k: atype.get(k) for k in ("typeKey", "typeId", "parentTypeId") if k in atype
        }
    return out


async def export(
    uid: uuid.UUID, activity_id: int, name: str, lat_off: float, lng_off: float
) -> dict[str, Any]:
    async with async_session_factory() as session:
        install_rls_listener(session, uid)
        activity = (
            await session.execute(select(Activity).where(Activity.id == activity_id))
        ).scalar_one()
        decoded = await load_fit_messages(session, activity=activity)
        if decoded is None:
            raise SystemExit(f"activity {activity_id} has no FIT messages")
        messages, _ = decoded
        stream = await load_stream(session, activity_id=activity_id)
        if stream is None:
            raise SystemExit(f"activity {activity_id} has no stream")
        list_item: dict[str, Any] = {}
        if activity.raw_payload_id is not None:
            blob = (
                await session.execute(
                    select(RawPayload.payload_gzip).where(
                        RawPayload.id == activity.raw_payload_id
                    )
                )
            ).scalar_one_or_none()
            items = json.loads(gzip.decompress(blob)) if blob is not None else []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and str(item.get("activityId")) == activity.external_id:
                    list_item = _list_item_subset(item)
        summary = {col: getattr(activity, col) for col in ACTIVITY_COLUMNS}
        await session.rollback()

    channels = dict(stream.channels)
    for code, off in (("lat_deg", lat_off), ("lng_deg", lng_off)):
        if code in channels:
            channels[code] = [None if v is None else v + off for v in channels[code]]

    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "source_activity_id": activity_id,
        "activity": summary,
        "activity_list_item": list_item,
        "stream": {
            "start_at": stream.start_at.isoformat(),
            "source": stream.source,
            "t_offset_s": stream.t_offset_s,
            "channels": channels,
        },
        "messages": {
            kind: [_clean_message(m, lat_off, lng_off) for m in messages.get(kind) or []]
            for kind in MESSAGE_KINDS
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=uuid.UUID, required=True)
    parser.add_argument("--activity-id", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--lat-offset", type=float, required=True)
    parser.add_argument("--lng-offset", type=float, required=True)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    data = asyncio.run(
        export(args.user_id, args.activity_id, args.name, args.lat_offset, args.lng_offset)
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"{args.name}.json.gz"
    raw = json.dumps(data, default=_json_default, ensure_ascii=False, separators=(",", ":"))
    # mtime=0 keeps the gzip bytes reproducible
    path.write_bytes(gzip.compress(raw.encode("utf-8"), mtime=0))
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
