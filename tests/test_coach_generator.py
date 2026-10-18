from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kairos.coach.generator import PlanInput, generate
from kairos.coach.knowledge import PlanType, get_knowledge
from kairos.coach.model import (
    BlockDraft,
    DayAvailability,
    GoalSpec,
    ReferenceValues,
    RunRecord,
    TrainingHistory,
    WeekPlan,
    availability_from_json,
    week_start,
)
from kairos.coach.validator import PlanView, validate
from kairos.coach.zones import format_pace, pace_s_per_km, race_time_s, vdot_from_race

START = date(2026, 11, 30)  # a Monday
MAX_AVAILABILITY = availability_from_json(
    {
        "mo": {"max_min": 45},
        "di": {"max_min": 45},
        "mi": {"max_min": 45},
        "do": {"max_min": 45},
        "fr": {"max_min": 75, "quality": True},
        "sa": {"max_min": 90, "quality": True},
        "so": {"max_min": 150, "quality": True},
    }
)


@pytest.fixture(scope="module")
def plan_type() -> PlanType:
    return get_knowledge().plan_types["ausdauer-laufen-pyramidal"]


def _history(weekly_km: float, longest_km: float, weeks: int = 6) -> TrainingHistory:
    runs: list[RunRecord] = []
    for w in range(weeks):
        monday = START - timedelta(weeks=weeks - w)
        if weekly_km <= 0:
            continue
        long_m = min(longest_km, weekly_km) * 1000
        rest = max(weekly_km * 1000 - long_m, 0)
        runs.append(RunRecord(monday + timedelta(days=6), long_m, long_m * 0.33))
        for d in (1, 3, 5):
            if rest > 0:
                runs.append(RunRecord(monday + timedelta(days=d), rest / 3, rest / 3 * 0.33))
    return TrainingHistory(tuple(runs))


def _input(
    plan_type: PlanType,
    *,
    weeks_to_race: int = 21,
    distance_m: float = 42_195,
    vdot: float | None = 45.05,
    history: TrainingHistory | None = None,
    availability: dict[int, DayAvailability] | None = None,
    kraft: bool = True,
    kind: str = "wettkampf",
) -> PlanInput:
    race = week_start(START) + timedelta(weeks=weeks_to_race - 1, days=6)
    return PlanInput(
        plan_type=plan_type,
        parameters={},
        goal=GoalSpec(kind, race if kind == "wettkampf" else None, distance_m, None, "Ziel"),
        start=START,
        availability=availability or MAX_AVAILABILITY,
        reference_values=ReferenceValues(
            vdot=vdot,
            vdot_measured_on=date(2026, 10, 31) if vdot else None,
            hf_max=184,
            hf_max_estimated=True,
        ),
        history=history if history is not None else _history(40, 16),
        supplementary=("kraft",) if kraft else (),
    )


# --- zones (research 6.2) -----------------------------------------------------------------


def test_vdot_from_the_10k_test_matches_the_research() -> None:
    vdot = vdot_from_race(10_000, 45 * 60 + 11)
    assert vdot == pytest.approx(45.0, abs=0.1)
    assert format_pace(pace_s_per_km(vdot, 88)) == "4:38"
    assert abs(pace_s_per_km(vdot, 98) - (4 * 60 + 14)) <= 2
    # E range 65-74 % VO2max: about 5:19-5:54
    assert format_pace(pace_s_per_km(vdot, 74)) == "5:19"
    assert format_pace(pace_s_per_km(vdot, 65)) == "5:54"
    # equivalents: half marathon about 1:40:10, marathon about 3:28
    assert race_time_s(vdot, 21_097.5) == pytest.approx(1 * 3600 + 40 * 60 + 10, abs=60)
    assert race_time_s(vdot, 42_195) / 3600 == pytest.approx(3.47, abs=0.03)


def test_vdot_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        vdot_from_race(0, 100)


# --- table tests --------------------------------------------------------------------------


def test_marathon_scenario_phases_and_first_weeks(plan_type: PlanType) -> None:
    out = generate(_input(plan_type))

    assert [p.kind for p in out.phases] == ["basis", "aufbau", "spitze", "taper"]
    assert sum(w.taper for w in out.weeks) == 3  # 21 taper days for the marathon
    assert out.detail_until == START + timedelta(days=13)
    assert {week_start(b.day) for b in out.blocks} == {START, START + timedelta(weeks=1)}
    long_runs = [b for b in out.blocks if b.workout_type == "long_run"]
    assert [b.day.weekday() for b in long_runs] == [6, 6]
    for block in out.blocks:
        if block.workout_type == "quality":
            assert MAX_AVAILABILITY[block.day.weekday()].quality
        assert all("@" in ref for ref in block.rule_refs)
    # only Friday to Sunday allow quality and Sunday is the long run: one quality per week
    assert any("nur 1 von 2" in w.message for w in out.warnings)
    assert not [
        v
        for v in validate(PlanView(out.blocks, out.weeks, _history(40, 16)), plan_type)
        if v.blocking
    ]
    assert any("Startumfang 40 km" in e for e in out.explain)


def test_quality_steps_carry_pace_and_heart_rate(plan_type: PlanType) -> None:
    out = generate(_input(plan_type))
    quality = next(b for b in out.blocks if b.workout_type == "quality")
    belastung = [s for g in quality.steps if g.steps for s in g.steps if s.typ == "belastung"]
    assert belastung and all(s.pace and s.hr for s in belastung)
    assert quality.steps[0].to_json()["pace_s_km"][0] < quality.steps[0].to_json()["pace_s_km"][1]


def test_without_vdot_the_first_week_is_a_test(plan_type: PlanType) -> None:
    out = generate(_input(plan_type, vdot=None))
    kinds = {b.unit_id for b in out.blocks}
    assert "lauf.einheit.test-10km" in kinds
    assert not kinds & {
        "lauf.einheit.schwelle",
        "lauf.einheit.intervall",
        "lauf.einheit.wiederholung",
    }


def test_stale_vdot_plans_a_test(plan_type: PlanType) -> None:
    inp = _input(plan_type)
    stale = PlanInput(
        **{
            **inp.__dict__,
            "reference_values": ReferenceValues(
                vdot=45.0, vdot_measured_on=START - timedelta(days=120)
            ),
        }
    )
    out = generate(stale)
    assert sum(b.unit_id == "lauf.einheit.test-10km" for b in out.blocks) == 1


def test_short_time_gives_taper_only(plan_type: PlanType) -> None:
    out = generate(_input(plan_type, weeks_to_race=3, distance_m=10_000))
    assert [p.kind for p in out.phases] == ["taper"]
    assert any("Nur 3 Woche" in w.message for w in out.warnings)


def test_tight_time_shortens_the_base_first(plan_type: PlanType) -> None:
    out = generate(_input(plan_type, weeks_to_race=8, distance_m=21_097.5))
    weeks = {p.kind: (p.end - p.start).days // 7 + 1 for p in out.phases}
    assert weeks["taper"] == 1  # 10 taper days for the half marathon
    assert sum(weeks.values()) == 8


def test_no_history_starts_low(plan_type: PlanType) -> None:
    out = generate(_input(plan_type, history=TrainingHistory()))
    assert out.weeks[0].volume_km <= 11
    assert any("Keine Laufdaten" in w.message for w in out.warnings)
    # without a reference the first runs stay at most 10 km
    assert all((b.distance_m or 0) <= 10_050 for b in out.blocks)


def test_health_goal_has_one_phase_without_taper(plan_type: PlanType) -> None:
    out = generate(_input(plan_type, kind="gesundheit"))
    assert {p.kind for p in out.phases} == {"basis"}
    assert not any(w.taper for w in out.weeks)


# --- validator ----------------------------------------------------------------------------


def _run(
    day: date,
    km: float,
    unit: str = "lauf.einheit.locker",
    *,
    z1: float | None = None,
    z2: float = 0.0,
    z3: float = 0.0,
    main_km: float | None = None,
    workout_type: str = "easy",
    sport: str = "laufen",
    start: str | None = None,
) -> BlockDraft:
    duration = km * 330
    return BlockDraft(
        day=day,
        sport=sport,
        unit_id=unit,
        unit_ref=f"{unit}@1",
        workout_type=workout_type,
        duration_s=duration,
        distance_m=km * 1000 if sport == "laufen" else None,
        zone_s={"z1": duration if z1 is None else z1, "z2": z2, "z3": z3},
        main_distance_m=(main_km if main_km is not None else km) * 1000,
        steps=[],
        rule_refs=[],
        phase="basis",
        start_time=start,
    )


def _ids(violations: list) -> set[str]:  # type: ignore[type-arg]
    return {v.rule_ref.split("@")[0] for v in violations}


def test_validator_blocks_a_run_far_beyond_the_longest(plan_type: PlanType) -> None:
    history = TrainingHistory((RunRecord(START - timedelta(days=5), 20_000, 7000),))
    view = PlanView(
        [_run(START + timedelta(days=6), 23.0)], [WeekPlan(START, "basis", 23)], history
    )
    hits = [
        v for v in validate(view, plan_type) if v.rule_ref.startswith("lauf.progression.einzellauf")
    ]
    assert hits and hits[0].blocking and hits[0].grenze == 22.0
    ok = PlanView([_run(START + timedelta(days=6), 21.9)], [WeekPlan(START, "basis", 22)], history)
    assert "lauf.progression.einzellauf" not in _ids(validate(ok, plan_type))


def test_validator_checks_z1_share_quality_count_and_strength_spacing(plan_type: PlanType) -> None:
    day = START
    blocks = [
        _run(day, 8, "lauf.einheit.schwelle", z1=1000, z2=1640, main_km=4, workout_type="quality"),
        _run(
            day + timedelta(days=2),
            8,
            "lauf.einheit.intervall",
            z1=1000,
            z2=0,
            z3=1640,
            main_km=3,
            workout_type="quality",
        ),
        _run(
            day + timedelta(days=4),
            8,
            "lauf.einheit.schwelle",
            z1=1000,
            z2=1640,
            main_km=4,
            workout_type="quality",
        ),
        _run(
            day + timedelta(days=4), 0, "kraft.schwere-last", sport="kraft", workout_type="strength"
        ),
    ]
    ids = _ids(
        validate(PlanView(blocks, [WeekPlan(START, "basis", 24)], TrainingHistory()), plan_type)
    )
    assert {
        "lauf.intensitaet.z1-anteil",
        "lauf.haeufigkeit.qualitaet",
        "kraft.abstand",
        "lauf.einheit.schwelle",
    } <= ids


def test_strength_with_enough_gap_is_fine(plan_type: PlanType) -> None:
    blocks = [
        _run(START, 8, "lauf.einheit.schwelle", main_km=0.5, workout_type="quality", start="07:00"),
        _run(START, 0, "kraft.schwere-last", sport="kraft", workout_type="strength", start="18:00"),
    ]
    view = PlanView(blocks, [WeekPlan(START, "basis", 30)], TrainingHistory())
    assert "kraft.abstand" not in _ids(validate(view, plan_type))


def test_validator_warns_on_weekly_jumps_but_ignores_deload_weeks(plan_type: PlanType) -> None:
    history = _history(30, 12, weeks=3)
    weeks = [
        WeekPlan(START, "basis", 40),
        WeekPlan(START + timedelta(weeks=1), "basis", 20, deload=True),
    ]
    hits = [
        v
        for v in validate(PlanView([], weeks, history), plan_type)
        if v.rule_ref.startswith("lauf.progression.wochenzuwachs")
    ]
    assert len(hits) == 1 and not hits[0].blocking and hits[0].week == START


# --- properties ---------------------------------------------------------------------------

_DAY = st.builds(
    DayAvailability,
    max_min=st.sampled_from([0, 30, 45, 60, 75, 90, 120, 150]),
    quality=st.booleans(),
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    days=st.lists(_DAY, min_size=7, max_size=7),
    weekly_km=st.sampled_from([0.0, 10.0, 25.0, 40.0, 60.0, 80.0]),
    longest_km=st.sampled_from([5.0, 12.0, 18.0, 25.0, 32.0]),
    vdot=st.one_of(st.none(), st.floats(30, 65)),
    weeks_to_race=st.integers(2, 30),
    distance_m=st.sampled_from([10_000.0, 21_097.5, 42_195.0]),
    kraft=st.booleans(),
)
def test_generated_plans_respect_the_guard_rails(
    plan_type: PlanType,
    days: list[DayAvailability],
    weekly_km: float,
    longest_km: float,
    vdot: float | None,
    weeks_to_race: int,
    distance_m: float,
    kraft: bool,
) -> None:
    history = _history(weekly_km, longest_km)
    inp = _input(
        plan_type,
        weeks_to_race=weeks_to_race,
        distance_m=distance_m,
        vdot=vdot,
        history=history,
        availability=dict(enumerate(days)),
        kraft=kraft,
    )
    out = generate(inp)

    violations = validate(PlanView(out.blocks, out.weeks, history), plan_type)
    assert not [v for v in violations if v.blocking], [v.detail for v in violations if v.blocking]
    for monday in {week_start(b.day) for b in out.blocks}:
        week_blocks = [b for b in out.blocks if week_start(b.day) == monday]
        runs = [b for b in week_blocks if b.sport == "laufen"]
        if len(runs) >= 3:
            total = sum(sum(b.zone_s.values()) for b in runs)
            assert sum(b.zone_s["z1"] for b in runs) / total >= 0.70
        busy = {b.day for b in week_blocks}
        assert len({monday + timedelta(days=i) for i in range(7)} - busy) >= 1
        for block in week_blocks:
            if block.workout_type == "quality":
                assert days[block.day.weekday()].quality
            if block.workout_type == "long_run":
                assert block.duration_s <= 9000 + 60
            assert block.duration_s <= days[block.day.weekday()].max_min * 60 + 60
    taper = [w.volume_km for w in out.weeks if w.taper]
    build = [w.volume_km for w in out.weeks if not w.taper and not w.deload]
    # without any available minutes every week is 0 km
    if taper and build and max(build) > 0:
        change = sum(taper) / len(taper) / max(build) - 1
        assert -0.62 <= change <= -0.39
