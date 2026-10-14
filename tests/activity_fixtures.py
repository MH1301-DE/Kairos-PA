from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kairos.activities.stream_repository import LoadedStream

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "activities"
DATETIME_KEYS = frozenset({"timestamp", "start_time", "end_time"})

AUTO_LAP_RUN = "run_autolap_1km_9k"
WORKOUT_RUN = "run_workout_threshold_4x6"
POOL_SWIM = "swim_pool_1000m"
TREADMILL_RUN = "run_treadmill_intervals_7k"


@dataclass(frozen=True)
class ActivityFixture:
    stream: LoadedStream
    messages: dict[str, list[dict[str, Any]]]
    summary: dict[str, Any]
    list_item: dict[str, Any]


def _message(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        k: datetime.fromisoformat(v) if k in DATETIME_KEYS and isinstance(v, str) else v
        for k, v in raw.items()
    }


def load_activity_fixture(name: str) -> ActivityFixture:
    data = json.loads(gzip.decompress((FIXTURE_DIR / f"{name}.json.gz").read_bytes()))
    stream = data["stream"]
    summary = dict(data["activity"])
    for key in ("start_at", "end_at", "start_local"):
        if summary.get(key) is not None:
            summary[key] = datetime.fromisoformat(summary[key])
    return ActivityFixture(
        stream=LoadedStream(
            start_at=datetime.fromisoformat(stream["start_at"]),
            t_offset_s=list(stream["t_offset_s"]),
            channels={k: list(v) for k, v in stream["channels"].items()},
            source=stream["source"],
        ),
        messages={k: [_message(m) for m in v] for k, v in data["messages"].items()},
        summary=summary,
        list_item=data["activity_list_item"],
    )
