"""Value types shared by generator, validator and service (coach spec 6.2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

WEEKDAY_KEYS = ("mo", "di", "mi", "do", "fr", "sa", "so")
RUN_SPORT = "laufen"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


@dataclass(frozen=True)
class GoalSpec:
    kind: str  # wettkampf | gesundheit | einsteiger
    race_date: date | None = None
    distance_m: float | None = None
    target_time_s: float | None = None
    title: str = ""


@dataclass(frozen=True)
class DayAvailability:
    max_min: int
    quality: bool
    time: str | None = None  # preferred start "HH:MM", local time


Availability = Mapping[int, DayAvailability]  # 0 = Monday


def availability_from_json(data: Mapping[str, Any]) -> dict[int, DayAvailability]:
    out: dict[int, DayAvailability] = {}
    for index, key in enumerate(WEEKDAY_KEYS):
        day = data.get(key) or {}
        out[index] = DayAvailability(
            max_min=max(0, int(day.get("max_min", 0))),
            quality=bool(day.get("quality", False)),
            time=day.get("time"),
        )
    return out


@dataclass(frozen=True)
class ReferenceValues:
    vdot: float | None = None
    vdot_measured_on: date | None = None
    lthr_laufen: float | None = None
    hf_max: int | None = None
    hf_max_estimated: bool = False


@dataclass(frozen=True)
class RunRecord:
    day: date
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class TrainingHistory:
    runs: tuple[RunRecord, ...] = ()

    def weekly_km(self, before: date, weeks: int) -> list[float]:
        """Run kilometres of the ``weeks`` full weeks before ``before`` (oldest first)."""
        first = week_start(before) - timedelta(weeks=weeks)
        totals = [0.0] * weeks
        for run in self.runs:
            index = (week_start(run.day) - first).days // 7
            if 0 <= index < weeks:
                totals[index] += run.distance_m / 1000
        return totals

    def longest_run_m(self, end: date, days: int = 30) -> float:
        start = end - timedelta(days=days)
        return max((r.distance_m for r in self.runs if start <= r.day < end), default=0.0)


@dataclass
class StepDraft:
    typ: str
    tempo: str | None
    duration_s: float | None
    distance_m: float | None
    pace: tuple[float, float] | None = None  # s/km fast..slow
    hr: tuple[int, int] | None = None
    repeat: int | None = None
    steps: list[StepDraft] | None = None
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"typ": self.typ}
        for key in ("tempo", "repeat", "note"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.duration_s is not None:
            out["dauer_s"] = round(self.duration_s)
        if self.distance_m is not None:
            out["distanz_m"] = round(self.distance_m)
        if self.pace is not None:
            out["pace_s_km"] = [round(self.pace[0]), round(self.pace[1])]
        if self.hr is not None:
            out["hr_bpm"] = list(self.hr)
        if self.steps:
            out["schritte"] = [s.to_json() for s in self.steps]
        return out


@dataclass
class BlockDraft:
    day: date
    sport: str
    unit_id: str
    unit_ref: str
    workout_type: str
    duration_s: float
    distance_m: float | None
    # seconds per three-zone zone; running only
    zone_s: dict[str, float]
    # distance of the unit's characteristic tempo (T in threshold work), for anteil_max_woche
    main_distance_m: float
    steps: list[StepDraft]
    rule_refs: list[str]
    phase: str
    start_time: str | None = None
    override_reason: str | None = None

    @property
    def is_run(self) -> bool:
        return self.sport == RUN_SPORT


@dataclass(frozen=True)
class PhaseDraft:
    kind: str
    start: date
    end: date
    focus: str
    volume_min_km: float
    volume_max_km: float
    rule_refs: tuple[str, ...]


@dataclass(frozen=True)
class WeekPlan:
    start: date
    phase: str
    volume_km: float
    deload: bool = False
    taper: bool = False


@dataclass(frozen=True)
class Verstoss:
    rule_ref: str
    art: str  # leitplanke | regel | hinweis
    message: str
    detail: str
    evidenz: str | None = None
    ist: float | None = None
    grenze: float | None = None
    day: date | None = None
    week: date | None = None

    @property
    def blocking(self) -> bool:
        return self.art == "leitplanke"

    def to_json(self) -> dict[str, Any]:
        return {
            "regel": self.rule_ref,
            "art": self.art,
            "evidenz": self.evidenz,
            "text": self.message,
            "detail": self.detail,
            "ist": self.ist,
            "grenze": self.grenze,
            "tag": self.day.isoformat() if self.day else None,
            "woche": self.week.isoformat() if self.week else None,
        }


@dataclass
class PlanOutput:
    phases: list[PhaseDraft]
    weeks: list[WeekPlan]
    blocks: list[BlockDraft]
    warnings: list[Verstoss] = field(default_factory=list)
    explain: list[str] = field(default_factory=list)
    detail_until: date | None = None
