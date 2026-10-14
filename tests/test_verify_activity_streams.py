from __future__ import annotations

from kairos.activities.stream_verification import Deviation, compare_counts


def test_equal_counts_have_no_deviation() -> None:
    result = compare_counts({1: {"hr": 5, "cadence": 3}}, {1: {"hr": 5, "cadence": 3}})
    assert result.ok and result.deviations == [] and result.stream_only == []


def test_mismatch_is_listed() -> None:
    result = compare_counts({1: {"hr": 5}}, {1: {"hr": 6}})
    assert result.deviations == [Deviation(1, "hr", 5, 6)]
    assert not result.ok


def test_distance_is_ignored() -> None:
    result = compare_counts({1: {"hr": 5, "distance_m": 5}}, {1: {"hr": 5, "distance_m": 2}})
    assert result.ok


def test_activity_with_records_but_no_stream_is_listed() -> None:
    result = compare_counts({}, {7: {"hr": 5}})
    assert result.missing_stream == [7] and not result.ok


def test_stream_only_channel_is_informational() -> None:
    result = compare_counts({1: {"hr": 5, "temp_c": 4}}, {1: {"hr": 5}})
    assert result.stream_only == [(1, "temp_c", 4)]
    assert result.ok


def test_record_channel_missing_in_stream_is_deviation() -> None:
    result = compare_counts({1: {"hr": 5}}, {1: {"hr": 5, "power_w": 2}})
    assert result.deviations == [Deviation(1, "power_w", 0, 2)]
