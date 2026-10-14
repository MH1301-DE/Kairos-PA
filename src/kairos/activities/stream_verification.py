from __future__ import annotations

from dataclasses import dataclass, field

# distance_m is derived at write time and has no matching record rows
IGNORED_CHANNELS = frozenset({"distance_m"})

Counts = dict[int, dict[str, int]]


@dataclass(frozen=True)
class Deviation:
    activity_id: int
    channel: str
    stream_count: int
    record_count: int


@dataclass
class Comparison:
    deviations: list[Deviation] = field(default_factory=list)
    missing_stream: list[int] = field(default_factory=list)
    stream_only: list[tuple[int, str, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.deviations and not self.missing_stream


def compare_counts(stream: Counts, records: Counts) -> Comparison:
    out = Comparison()
    for activity_id in sorted(set(stream) | set(records)):
        s = {c: n for c, n in stream.get(activity_id, {}).items() if c not in IGNORED_CHANNELS}
        r = {c: n for c, n in records.get(activity_id, {}).items() if c not in IGNORED_CHANNELS}
        if activity_id not in stream:
            if r:
                out.missing_stream.append(activity_id)
            continue
        for channel in sorted(set(s) | set(r)):
            if channel not in r:
                out.stream_only.append((activity_id, channel, s[channel]))
            elif s.get(channel, 0) != r[channel]:
                out.deviations.append(
                    Deviation(activity_id, channel, s.get(channel, 0), r[channel])
                )
    return out
