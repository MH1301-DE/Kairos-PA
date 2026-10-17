from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive import service as service_module
from kairos.activities.derive.service import derive_activity
from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import StreamSet
from kairos.agent import activity_tools
from kairos.agent.activity_tools import (
    activity_analyze_handler,
    activity_get_handler,
    activity_search_handler,
    activity_splits_handler,
    best_efforts_handler,
)
from kairos.agent.format import CHARS_PER_TOKEN, MINUS, fmt_duration
from kairos.agent.tools import TOOLS_BY_NAME
from kairos.db.models import Activity, ActivityBestEffort, ActivitySplit, SyncState
from kairos.db.rls import install_rls_listener
from tests.activity_fixtures import (
    AUTO_LAP_RUN,
    POOL_SWIM,
    WORKOUT_RUN,
    ActivityFixture,
    load_activity_fixture,
)

_ACTIVITY_COLUMNS = (
    "sport",
    "sport_profile",
    "start_at",
    "end_at",
    "start_local",
    "utc_offset_min",
    "moving_duration_s",
    "distance_m",
    "duration_s",
    "avg_hr",
    "max_hr",
    "elevation_gain_m",
    "calories",
    "garmin_training_load",
    "garmin_vo2max",
)
_WIDE = {"from_date": "2026-01-01", "to_date": "2026-12-31"}
_AS_OF = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Seeded:
    uid: uuid.UUID
    autolap: int
    workout: int
    swim: int
    deleted: int


def _tokens(env: dict[str, Any]) -> float:
    return len(json.dumps(env, ensure_ascii=False)) / CHARS_PER_TOKEN


def _clock_s(text: str) -> int:
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


async def _user(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'Europe/Berlin', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    await session.execute(
        text("INSERT INTO user_setting (user_id, hr_max_override) VALUES (:u, 190)"),
        {"u": str(uid)},
    )
    session.add(
        SyncState(
            user_id=uid,
            connector="garmin",
            kind="activity_list",
            last_success_at=_AS_OF,
            consecutive_failures=0,
        )
    )
    await session.commit()
    return uid


async def _activity(
    session: AsyncSession,
    uid: uuid.UUID,
    fx: ActivityFixture,
    external_id: str,
    *,
    name: str | None,
    with_stream: bool = True,
    **overrides: Any,
) -> int:
    fields = {k: fx.summary.get(k) for k in _ACTIVITY_COLUMNS} | overrides
    activity = Activity(user_id=uid, external_id=external_id, name=name, **fields)
    session.add(activity)
    await session.flush()
    if with_stream:
        await replace_streams(
            session,
            user_id=uid,
            activity_id=activity.id,
            streams=StreamSet(
                start_at=fx.stream.start_at,
                t_offset_s=fx.stream.t_offset_s,
                channels=fx.stream.channels,
                source="fit_zip",
            ),
            algo_version=STREAM_ALGO_VERSION,
        )
    await session.commit()
    return activity.id


@pytest.fixture
def fixtures(monkeypatch: pytest.MonkeyPatch) -> dict[str, ActivityFixture]:
    by_ext = {
        "autolap": load_activity_fixture(AUTO_LAP_RUN),
        "workout": load_activity_fixture(WORKOUT_RUN),
        "swim": load_activity_fixture(POOL_SWIM),
    }

    async def _load(session: AsyncSession, *, activity: Activity) -> Any:
        del session
        fx = by_ext.get(activity.external_id.split("-")[0])
        return None if fx is None else (fx.messages, "fit_zip")

    monkeypatch.setattr(service_module, "load_fit_messages", _load)
    monkeypatch.setattr(activity_tools, "load_fit_messages", _load)
    return by_ext


async def _seed(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> Seeded:
    uid = await _user(session)
    autolap = await _activity(session, uid, fixtures["autolap"], "autolap", name="Abendlauf")
    workout = await _activity(
        session, uid, fixtures["workout"], "workout", name="W3 Do Schwelle 4x6"
    )
    swim = await _activity(session, uid, fixtures["swim"], "swim", name="Bahnen")
    deleted = await _activity(
        session,
        uid,
        fixtures["autolap"],
        "deleted",
        name="Abendlauf alt",
        with_stream=False,
        start_at=datetime(2026, 10, 2, 6, 0, tzinfo=UTC),
        start_local=datetime(2026, 10, 2, 8, 0),
    )
    install_rls_listener(app_session, uid)
    for activity_id in (autolap, workout, swim, deleted):
        outcome = await derive_activity(app_session, user_id=uid, activity_id=activity_id)
        assert outcome.status in ("derived", "summary_only"), outcome
    await app_session.commit()
    await session.execute(
        text("UPDATE activity SET deleted_at = now(), deleted_reason = 'kairos' WHERE id = :i"),
        {"i": deleted},
    )
    await session.commit()
    return Seeded(uid, autolap, workout, swim, deleted)


def _ids(env: dict[str, Any]) -> list[int]:
    return [row[0] for row in env["data"]["rows"]]


@pytest.mark.asyncio
async def test_search_sorts_filters_and_hides_deleted(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    newest = await activity_search_handler(app_session, user_id=s.uid, **_WIDE)
    assert _ids(newest) == [s.autolap, s.workout, s.swim]
    assert newest["data"]["cols"] == [
        "id", "datum", "name", "sport", "distanz", "dauer", "tempo", "hf_avg", "hm_auf", "trimp",
    ]
    first = newest["data"]["rows"][0]
    assert first[1] == "Mi 30.09. 19:32"
    assert first[3] == "Laufen" and first[4] == "9,01 km" and first[6].endswith(" /km")
    assert newest["data"]["rows"][2][6].endswith(" /100 m")
    assert newest["meta"]["as_of"] == _AS_OF.isoformat()
    assert newest["meta"]["next"] == "Details: activity_get(activity_id=…)"
    assert newest["meta"]["row_count"] == 3 and newest["meta"]["truncated"] is False
    assert "3 Aktivitäten" in newest["summary"]

    oldest = await activity_search_handler(app_session, user_id=s.uid, sort="oldest", **_WIDE)
    assert _ids(oldest) == [s.swim, s.workout, s.autolap]

    longest = await activity_search_handler(app_session, user_id=s.uid, sort="longest", **_WIDE)
    assert _ids(longest) == [s.workout, s.autolap, s.swim]

    fastest = await activity_search_handler(
        app_session, user_id=s.uid, sort="fastest", sport_profile="running", **_WIDE
    )
    assert _ids(fastest) == [s.workout, s.autolap]
    assert "2 Läufe" in fastest["summary"] and "19,27 km" in fastest["summary"]

    with pytest.raises(ValueError, match="sport_profile"):
        await activity_search_handler(app_session, user_id=s.uid, sort="fastest", **_WIDE)

    far = await activity_search_handler(app_session, user_id=s.uid, min_distance_km=9.5, **_WIDE)
    assert _ids(far) == [s.workout]
    near = await activity_search_handler(app_session, user_id=s.uid, max_distance_km=9.5, **_WIDE)
    assert _ids(near) == [s.autolap, s.swim]
    named = await activity_search_handler(
        app_session, user_id=s.uid, name_contains="schwelle", **_WIDE
    )
    assert _ids(named) == [s.workout]
    gone = await activity_search_handler(
        app_session, user_id=s.uid, name_contains="alt", **_WIDE
    )
    assert _ids(gone) == [] and gone["meta"]["row_count"] == 0

    window = await activity_search_handler(
        app_session, user_id=s.uid, from_date="2026-09-01", to_date="2026-09-30"
    )
    assert _ids(window) == [s.autolap, s.workout]


@pytest.mark.asyncio
async def test_get_latest_and_by_profile(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    latest = await activity_get_handler(app_session, user_id=s.uid)
    data = latest["data"]
    assert data["aktivitaet"]["id"] == s.autolap
    assert data["aktivitaet"]["sport"] == "Laufen (running)"
    assert data["aktivitaet"]["start"] == "Mi 30.09.2026 19:32"
    assert data["aktivitaet"]["distanzquelle"] == "GPS"
    assert data["umfang"]["distanz"] == "9,01 km"
    assert data["tempo"]["pace"].endswith(" /km")
    assert data["tempo"]["schnellster_km"].startswith("km ")
    assert set(data["herzfrequenz"]["zonen"]) == {"z1", "z2", "z3", "z4", "z5"}
    assert data["technik"]["kadenz"].endswith(" spm")
    assert data["belastung"]["garmin_training_load"] == 78
    assert data["splits"]["km"] >= 9
    assert data["workout"] is None
    assert latest["summary"].startswith("Lauf Mi 30.09.2026: 9,01 km in ")
    assert latest["meta"]["quality"] == "ok"
    assert latest["meta"]["as_of"] == _AS_OF.isoformat()
    assert latest["meta"]["coverage"].startswith("HF ")
    assert latest["meta"]["next"] == f"Kilometerwerte: activity_splits(activity_id={s.autolap})"
    assert "kalorien" not in json.dumps(latest, ensure_ascii=False).lower()

    swim = await activity_get_handler(app_session, user_id=s.uid, sport_profile="swimming")
    sd = swim["data"]
    assert sd["aktivitaet"]["id"] == s.swim
    assert sd["tempo"]["pace"].endswith(" /100 m")
    assert sd["herzfrequenz"]["hinweis"] == "Handgelenk-HF im Wasser eingeschränkt verlässlich"
    assert "hoehe" not in sd["umfang"] and "kadenz" not in sd.get("technik", {})
    assert sd["schwimmen"]["beckenlaenge"] == "50 m"
    assert swim["meta"]["quality"] == "partial"

    by_id = await activity_get_handler(app_session, user_id=s.uid, activity_id=s.workout)
    assert by_id["data"]["aktivitaet"]["id"] == s.workout


@pytest.mark.asyncio
async def test_get_workout_activity_fills_workout_block(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    env = await activity_get_handler(app_session, user_id=s.uid, activity_id=s.workout)
    workout = env["data"]["workout"]
    assert workout["name"] == "W3 Do Schwelle 4x6"
    assert workout["bewertet"] >= 4 and 0 <= workout["getroffen"] <= workout["bewertet"]
    assert "Intervalle" in workout["kurz"]
    assert env["meta"]["next"] == (
        f'Workout-Schritte: activity_splits(activity_id={s.workout}, kind="steps")'
    )


@pytest.mark.asyncio
async def test_deleted_activity_is_invisible_to_get(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    with pytest.raises(ValueError, match="nicht gefunden"):
        await activity_get_handler(app_session, user_id=s.uid, activity_id=s.deleted)
    with pytest.raises(ValueError, match="nicht gefunden"):
        await activity_get_handler(app_session, user_id=s.uid, sport_profile="cycling")


@pytest.mark.asyncio
async def test_token_caps_hold(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    uid = await _user(session)
    fx = fixtures["autolap"]
    long_name = "Sehr langer Name mit vielen Wörtern für den Obergrenzentest " * 10
    base = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    ids = [
        await _activity(
            session,
            uid,
            fx,
            f"cap{i}",
            name=long_name,
            with_stream=False,
            start_at=base + timedelta(days=i),
            start_local=(base + timedelta(days=i, hours=2)).replace(tzinfo=None),
        )
        for i in range(20)
    ]
    install_rls_listener(app_session, uid)
    for activity_id in ids:
        await derive_activity(app_session, user_id=uid, activity_id=activity_id)
    await app_session.commit()

    search = await activity_search_handler(app_session, user_id=uid, limit=20, **_WIDE)
    assert _tokens(search) <= 600
    assert search["meta"]["truncated"] is True
    assert search["meta"]["row_count"] == len(search["data"]["rows"]) > 0

    get = await activity_get_handler(app_session, user_id=uid)
    assert _tokens(get) <= 700
    assert get["meta"]["quality"] == "partial"


@pytest.mark.asyncio
async def test_splits_distance_table_and_range(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    env = await activity_splits_handler(app_session, user_id=s.uid, activity_id=s.autolap)
    data = env["data"]
    assert data["unit"] == "1 km"
    assert data["cols"][:5] == ["km", "pace", "kum_zeit", "hm_auf", "hm_ab"]
    assert {"hf_min", "hf_med", "hf_max", "kadenz"} <= set(data["cols"])
    rows = data["rows"]
    assert [r[0] for r in rows] == [str(i) for i in range(1, 10)]
    assert all(":" in r[1] and "/" not in r[1] for r in rows)
    # kum_zeit is the running total of the split times
    assert _clock_s(rows[1][2]) == pytest.approx(_clock_s(rows[0][1]) + _clock_s(rows[1][1]), abs=1)
    assert env["summary"].startswith("9 Kilometer-Splits. Schnellster km ")
    assert env["meta"]["truncated"] is False and env["meta"]["quality"] == "ok"
    assert _tokens(env) <= 1200

    part = await activity_splits_handler(
        app_session, user_id=s.uid, activity_id=s.autolap, from_idx=3, to_idx=5
    )
    assert [r[0] for r in part["data"]["rows"]] == ["3", "4", "5"]
    assert part["data"]["rows"][0][2] == rows[2][2]

    swim = await activity_splits_handler(app_session, user_id=s.uid, activity_id=s.swim)
    assert swim["data"]["unit"] == "100 m"
    assert swim["data"]["cols"][:3] == ["m", "pace_100m", "kum_zeit"]

    with pytest.raises(ValueError, match="nicht gefunden"):
        await activity_splits_handler(app_session, user_id=s.uid, activity_id=s.deleted)


@pytest.mark.asyncio
async def test_splits_100k_run_is_grouped_into_blocks(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    uid = await _user(session)
    activity = Activity(
        user_id=uid,
        external_id="ultra",
        name="100 km",
        sport="running",
        sport_profile="running",
        start_at=datetime(2026, 9, 5, 5, 0, tzinfo=UTC),
        start_local=datetime(2026, 9, 5, 7, 0),
        distance_m=100_000.0,
        duration_s=36_000.0,
    )
    session.add(activity)
    await session.flush()
    session.add_all(
        ActivitySplit(
            activity_id=activity.id,
            kind="distance",
            idx=i,
            user_id=uid,
            unit_m=1000.0,
            distance_m=1000.0,
            timer_s=300.0 + i,
            pace_s_km=300.0 + i,
            hr_min=120,
            hr_median=140 + i % 5,
            hr_max=150 + i % 7,
            quality="ok",
        )
        for i in range(1, 101)
    )
    await session.commit()
    install_rls_listener(app_session, uid)

    env = await activity_splits_handler(app_session, user_id=uid, activity_id=activity.id)
    rows = env["data"]["rows"]
    assert len(rows) == 20 and rows[0][0] == "1–5" and rows[-1][0] == "96–100"
    assert env["data"]["unit"] == "5 km"
    # block pace = block time / block distance: (301 + … + 305) / 5 s
    assert rows[0][1] == "5:03"
    assert rows[-1][2] == fmt_duration(sum(300.0 + i for i in range(1, 101)))
    assert env["meta"]["truncated"] is True
    assert env["meta"]["next"] == (
        f'Einzelwerte: activity_splits(activity_id={activity.id}, kind="distance", '
        "from_idx=1, to_idx=50)"
    )
    assert _tokens(env) <= 1200

    single = await activity_splits_handler(
        app_session, user_id=uid, activity_id=activity.id, from_idx=51, to_idx=100
    )
    assert len(single["data"]["rows"]) == 50 and single["data"]["rows"][0][0] == "51"
    assert _tokens(single) <= 1200


@pytest.mark.asyncio
async def test_splits_laps_and_workout_steps(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    laps = await activity_splits_handler(
        app_session, user_id=s.uid, activity_id=s.workout, kind="lap"
    )
    cols = laps["data"]["cols"]
    assert cols[:3] == ["runde", "typ", "schritt"]
    types = {r[1] for r in laps["data"]["rows"]}
    assert {"Aufwärmen", "Intervall", "Erholung", "Auslaufen"} <= types
    assert all(r[cols.index("tempo")].endswith(" /km") for r in laps["data"]["rows"])
    assert "kind=\"steps\"" in laps["summary"]

    autolap = await activity_splits_handler(
        app_session, user_id=s.uid, activity_id=s.autolap, kind="lap"
    )
    assert {r[1] for r in autolap["data"]["rows"]} <= {"Auto-Runde (Distanz)", "Ende"}
    assert "schritt" not in autolap["data"]["cols"]

    steps = await activity_splits_handler(
        app_session, user_id=s.uid, activity_id=s.workout, kind="steps"
    )
    assert steps["data"]["cols"] == [
        "nr", "schritt", "wdh", "ziel", "ist", "dauer", "distanz", "hf_med", "getroffen",
    ]
    rows = steps["data"]["rows"]
    warmup, first_interval = rows[0], rows[1]
    assert warmup[1] == "Einlaufen locker" and warmup[2] is None and warmup[8] == "–"
    assert first_interval[1] == "SCHWELLE 4:50"
    assert first_interval[2] == "1/4"
    assert first_interval[3] == "4:35–4:45 /km"
    assert first_interval[4].endswith(" /km") and first_interval[8] in ("ja", "nein")
    assert [r[2] for r in rows if r[1] == "SCHWELLE 4:50"] == ["1/4", "2/4", "3/4", "4/4"]
    assert steps["summary"].startswith("Workout „W3 Do Schwelle 4x6“: Intervalle ")
    assert "(Ø " in steps["summary"]
    assert _tokens(steps) <= 1200

    with pytest.raises(ValueError, match="kein Workout"):
        await activity_splits_handler(
            app_session, user_id=s.uid, activity_id=s.autolap, kind="steps"
        )


@pytest.mark.asyncio
async def test_analyze_segment_and_curve(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    seg = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.autolap, operation="segment",
        from_km=2, to_km=5,
    )
    cols, row = seg["data"]["cols"], seg["data"]["rows"][0]
    assert cols[:4] == ["bereich", "distanz", "dauer", "pace"]
    assert row[0] == "km 2,00–5,00" and row[1] == "3,00 km"
    assert seg["summary"].startswith("Abschnitt km 2,00–5,00: 3,00 km in ")

    by_min = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.autolap, operation="segment",
        from_min=10, to_min=20,
    )
    assert by_min["data"]["rows"][0][0] == "min 10–20"
    assert by_min["data"]["rows"][0][2] == "10:00"

    with pytest.raises(ValueError, match="km oder Minuten"):
        await activity_analyze_handler(
            app_session, user_id=s.uid, activity_id=s.autolap, operation="segment",
            from_km=1, to_min=5,
        )
    with pytest.raises(ValueError, match="km oder Minuten"):
        await activity_analyze_handler(
            app_session, user_id=s.uid, activity_id=s.autolap, operation="segment"
        )

    curve = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.workout, operation="curve", metric="pace"
    )
    data = curve["data"]
    assert len(data["x"]) == len(data["y"]) == 60
    assert data["x_unit"] == "min" and data["y_unit"] == "s/km" and data["y_format"] == "pace"
    assert data["x"] == sorted(data["x"])
    hr = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.workout, operation="curve", points=10
    )
    assert len(hr["data"]["y"]) == 10 and hr["data"]["y_unit"] == "bpm"
    assert all(isinstance(v, int) for v in hr["data"]["y"])
    assert _tokens(curve) <= 800


@pytest.mark.asyncio
async def test_analyze_compare(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    env = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.autolap, operation="compare",
        other_activity_id=s.workout,
    )
    cols = env["data"]["cols"]
    assert cols[0] == "kennzahl" and cols[3] == "differenz a−b"
    assert cols[1].startswith("a: 30.09. Abendlauf")
    rows = {r[0]: r for r in env["data"]["rows"]}
    assert rows["distanz"][1] == "9,01 km"
    assert rows["distanz"][3].startswith(MINUS) and rows["distanz"][3].endswith(" km")
    assert rows["pace"][3][0] in ("+", MINUS) and rows["pace"][3].endswith(" /km")
    assert rows["effizienz"][1].endswith(" m/Herzschlag")
    assert "„Abendlauf“ (30.09.) war " in env["summary"]
    assert _tokens(env) <= 800

    with pytest.raises(ValueError, match="Sportprofil"):
        await activity_analyze_handler(
            app_session, user_id=s.uid, activity_id=s.autolap, operation="compare",
            other_activity_id=s.swim,
        )
    with pytest.raises(ValueError, match="other_activity_id"):
        await activity_analyze_handler(
            app_session, user_id=s.uid, activity_id=s.autolap, operation="compare"
        )


@pytest.mark.asyncio
async def test_analyze_hr_drift(
    session: AsyncSession, app_session: AsyncSession, fixtures: dict[str, ActivityFixture]
) -> None:
    s = await _seed(session, app_session, fixtures)

    intervals = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=s.workout, operation="hr_drift"
    )
    assert intervals["data"]["entkopplung"] is None
    assert intervals["data"]["hinweis"]
    assert intervals["summary"].startswith("Entkopplung nicht berechenbar: ")

    # steady 60 min at 3 m/s while HR climbs from 140 to 160
    n = 3601
    steady = Activity(
        user_id=s.uid,
        external_id="steady",
        name="Langer Lauf",
        sport="running",
        sport_profile="running",
        start_at=datetime(2026, 9, 20, 7, 0, tzinfo=UTC),
        start_local=datetime(2026, 9, 20, 9, 0),
        distance_m=3.0 * (n - 1),
        duration_s=float(n - 1),
    )
    session.add(steady)
    await session.flush()
    await replace_streams(
        session,
        user_id=s.uid,
        activity_id=steady.id,
        streams=StreamSet(
            start_at=steady.start_at,
            t_offset_s=list(range(n)),
            channels={
                "distance_m": [3.0 * i for i in range(n)],
                "hr": [140.0 + 20.0 * i / (n - 1) for i in range(n)],
            },
            source="fit_zip",
        ),
        algo_version=STREAM_ALGO_VERSION,
    )
    await session.commit()

    env = await activity_analyze_handler(
        app_session, user_id=s.uid, activity_id=steady.id, operation="hr_drift"
    )
    data = env["data"]
    assert data["haelften"]["cols"] == ["haelfte", "zeitraum", "pace", "hf_avg", "effizienz"]
    first, second = data["haelften"]["rows"]
    assert first[2] == second[2] == "5:33 /km"
    assert first[3] < second[3]
    assert data["entkopplung"].endswith(" %") and data["einordnung"].startswith("moderat")
    assert env["summary"].startswith("Aerobe Entkopplung ")
    assert _tokens(env) <= 800


@pytest.mark.asyncio
async def test_best_efforts_ytd_and_missing_distance(
    session: AsyncSession,
    app_session: AsyncSession,
    fixtures: dict[str, ActivityFixture],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await _seed(session, app_session, fixtures)
    monkeypatch.setattr(activity_tools, "_today", lambda tz: date(2026, 10, 15))
    fastest = (
        await app_session.execute(
            select(ActivityBestEffort)
            .where(ActivityBestEffort.distance_key == "5k")
            .order_by(ActivityBestEffort.duration_s)
        )
    ).scalars().first()
    assert fastest is not None

    env = await best_efforts_handler(
        app_session, user_id=s.uid, distances=["5k", "hm"], period="ytd"
    )
    assert env["data"]["cols"] == [
        "distanz", "zeit", "pace", "datum", "aktivitaet", "abschnitt", "qualitaet",
    ]
    five, half = env["data"]["rows"]
    assert five[0] == "5 km" and five[1] == fmt_duration(fastest.duration_s)
    assert five[2].endswith(" /km") and five[3].endswith(".2026")
    assert five[4].startswith(f"#{fastest.activity_id} ")
    assert five[5].startswith("km ") and five[6] == "ok"
    assert half == ["HM", "—", "—", "—", "—", "—", "kein GPS-Lauf ≥ 21,1 km im Zeitraum"]
    assert env["summary"].startswith(f"Bestzeiten 2026: 5 km {five[1]} ({five[3][3:]})")
    assert "HM: kein GPS-Lauf dieser Länge" in env["summary"]
    assert _tokens(env) <= 500

    autumn = await best_efforts_handler(
        app_session, user_id=s.uid, distances=["5k"], period="custom",
        from_date="2026-09-20", to_date="2026-09-30", top_n=3,
    )
    assert autumn["data"]["cols"][0] == "rang"
    assert [r[5] for r in autumn["data"]["rows"]] == [f"#{s.autolap} Abendlauf"]

    full = await best_efforts_handler(app_session, user_id=s.uid, top_n=5)
    assert _tokens(full) <= 500
    with pytest.raises(ValueError, match="from_date"):
        await best_efforts_handler(app_session, user_id=s.uid, period="custom")
    with pytest.raises(ValueError, match="distances"):
        await best_efforts_handler(app_session, user_id=s.uid, distances=["7k"])


def test_tools_are_registered_with_spec_schemas() -> None:
    search = TOOLS_BY_NAME["activity_search"]
    get = TOOLS_BY_NAME["activity_get"]
    assert search.risk_class == get.risk_class == "read"
    assert search.description.startswith("Sucht eigene Aktivitäten")
    assert search.json_schema["properties"]["sort"]["enum"] == [
        "newest", "oldest", "longest", "fastest",
    ]
    assert search.json_schema["properties"]["limit"] == {
        "type": "integer", "minimum": 1, "maximum": 20,
    }
    assert get.description.startswith("Steckbrief einer Aktivität")
    assert set(get.json_schema["properties"]) == {"activity_id", "sport_profile"}
    splits = TOOLS_BY_NAME["activity_splits"]
    analyze = TOOLS_BY_NAME["activity_analyze"]
    assert splits.risk_class == analyze.risk_class == "read"
    assert splits.description.startswith("Split-Tabelle einer Aktivität")
    assert splits.json_schema["required"] == ["activity_id"]
    assert splits.json_schema["properties"]["kind"]["enum"] == ["distance", "lap", "steps"]
    assert analyze.description.startswith("Serverseitige Auswertung einer Aktivität")
    assert analyze.json_schema["required"] == ["activity_id", "operation"]
    assert analyze.json_schema["properties"]["points"] == {
        "type": "integer", "minimum": 10, "maximum": 60,
    }
    efforts = TOOLS_BY_NAME["best_efforts"]
    assert efforts.risk_class == "read"
    assert efforts.description.startswith("Lauf-Bestleistungen")
    assert efforts.json_schema["properties"]["distances"]["items"]["enum"] == [
        "800m", "1500m", "3000m", "5k", "10k", "hm", "m", "50k", "100k",
    ]
    assert efforts.json_schema["properties"]["top_n"] == {
        "type": "integer", "minimum": 1, "maximum": 5,
    }
