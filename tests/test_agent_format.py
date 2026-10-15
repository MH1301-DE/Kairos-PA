from __future__ import annotations

from datetime import UTC, datetime

from kairos.agent.format import (
    cap_envelope,
    drop_last_row,
    fmt_date_short,
    fmt_datetime_local,
    fmt_diff,
    fmt_distance,
    fmt_duration,
    fmt_pace_100m,
    fmt_pace_km,
    fmt_speed_kmh,
    table,
)
from kairos.agent.tools import _envelope

TZ = "Europe/Berlin"


def test_distance() -> None:
    assert fmt_distance(8020) == "8,02 km"
    assert fmt_distance(800) == "800 m"
    assert fmt_distance(999.7) == "1,00 km"


def test_duration_and_pace() -> None:
    assert fmt_duration(41 * 60 + 30) == "41:30"
    assert fmt_duration(4166) == "1:09:26"
    assert fmt_pace_km(309.6) == "5:10 /km"
    assert fmt_pace_100m(125) == "2:05 /100 m"
    assert fmt_speed_kmh(28.43) == "28,4 km/h"


def test_datetime_local_respects_dst() -> None:
    summer = datetime(2026, 10, 7, 5, 12, tzinfo=UTC)
    winter = datetime(2026, 12, 7, 6, 12, tzinfo=UTC)
    assert fmt_datetime_local(summer, TZ) == "Mi 07.10.2026 07:12"
    assert fmt_datetime_local(winter, TZ) == "Mo 07.12.2026 07:12"
    assert fmt_date_short(summer, TZ) == "Mi 07.10. 07:12"


def test_diff_uses_unicode_minus() -> None:
    assert fmt_diff(25, "pace") == "+0:25 /km"
    assert fmt_diff(-2030, "distance") == "\u22122,03 km"
    assert fmt_diff(-16, "int") == "\u221216"
    assert fmt_diff(90, "duration") == "+1:30"
    assert fmt_diff(0, "int") == "0"


def test_cap_envelope_truncates_table() -> None:
    rows = [[i, "Di 07.10. 07:12", "Morgenlauf", "8,02 km"] for i in range(200)]
    env = _envelope("x", table(["id", "d", "n", "k"], rows))
    capped = cap_envelope(env, max_tokens=600, shrink=drop_last_row)
    assert capped["meta"]["truncated"] is True
    assert 0 < len(capped["data"]["rows"]) < 200
    assert capped["meta"]["row_count"] == len(capped["data"]["rows"])


def test_cap_envelope_untouched_when_small() -> None:
    env = _envelope("x", table(["a"], [[1]]), max_tokens=600)
    assert env["meta"]["truncated"] is False


def test_envelope_next_quality_and_cap() -> None:
    env = _envelope("x", table(["a"], [[1]]), next_hint="activity_get", quality="ok")
    assert env["meta"]["next"] == "activity_get"
    assert env["meta"]["quality"] == "ok"
    assert env["meta"]["row_count"] == 1
    plain = _envelope("x", [1, 2])
    assert "next" not in plain["meta"]
    assert "quality" not in plain["meta"]
