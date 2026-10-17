from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive import service as service_module
from kairos.activities.derive.service import derive_activity
from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import StreamSet
from kairos.agent.activity_tools import activity_get_handler, activity_search_handler
from kairos.agent.format import CHARS_PER_TOKEN
from kairos.agent.tools import TOOLS_BY_NAME
from kairos.db.models import Activity, SyncState
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
