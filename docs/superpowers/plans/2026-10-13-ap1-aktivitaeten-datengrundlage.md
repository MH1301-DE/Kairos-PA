# AP 1 — Aktivitäten: Datengrundlage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `activity` korrekt und vollständig befüllen (Sportprofil, Garmin-Typ, lokale Startzeit, Bewegtzeit …), die FIT-Distanz und eine Garmin-genaue Kadenz speichern, bei Garmin gelöschte Aktivitäten erkennen und alle 136 Bestandsaktivitäten ohne Garmin-Request aus `raw_payload` neu verarbeiten.

**Architecture:** Eine Migration erweitert `activity` und seedet `distance_m`. Normalizer und Canonical-Repository schreiben die neuen Felder, der Upsert aktualisiert alle fachlichen Spalten. Der Lösch-Abgleich hängt als optionaler Hook nach jedem `activity_list`-Fenster am `SyncService`. Ein Reprocess-Service liest archivierte Payloads (jüngster gewinnt) und schreibt `activity`/`activity_record` neu; ein Endpoint startet ihn als Job unter denselben Locks und demselben Cooldown wie der Backfill.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy async, Alembic, TimescaleDB, pytest + testcontainers, garminconnect 0.3.17.

**Spec:** `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` — Teil A (A.1–A.5) und §2.1 (AP-0-Ergebnisse).

## Global Constraints

- Jede Session, die RLS-Tabellen liest oder schreibt, braucht `install_rls_listener(session, user_id)` (FORCE RLS auf allen Tenant-Tabellen).
- `activity_list` läuft vor `activity_fit` (`activity_record.activity_id` ist FK).
- `metric_def`-Seeds müssen existieren (`wellness_sample.metric_id` / Metrik-Codes).
- Nur `garminconnect`, nie `garth`.
- `ruff` (line-length 100) + `mypy --strict` sauber; Kommentare höchstens eine kurze Zeile; keine Docstrings an unverändertem Code.
- Tests: `.venv/Scripts/python -m pytest -q`, Docker muss laufen (testcontainers); am Ende 0 skipped.
- Conventional Commits, Footer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Sportprofile: `running`, `cycling`, `swimming`, `hiking`, `generic` (CHECK-Constraint).
- `deleted_reason` ∈ {`kairos`, `garmin_sync`}.
- Lauf-Kadenz in spm = 2 × (`cadence` + `fractional_cadence`) (AP 0, 219/219).
- Garmin filtert `get_activities_by_date` nach **lokalem** Startdatum; ein Tagesfenster fragt `(d, d+1)` ab, beide inklusive (AP 0).
- `GARMIN_FIT_DOWNLOAD_PAUSE_S` Default 2,0 s zwischen FIT-Downloads innerhalb eines Fensters.
- Reprocess teilt Lock (`activity_list` und `activity_fit`) und 300-s-Cooldown mit dem Garmin-Backfill.

## Review Focus

1. Aktivität ohne `startTimeLocal` (ältere/manuelle Einträge) → `start_local`/`utc_offset_min` bleiben `NULL`, nichts crasht, Lösch-Abgleich fasst sie nicht an (Task 3, Task 6).
2. `activity_list`-Abruf scheitert oder liefert keine Liste → keine einzige Aktivität wird als gelöscht markiert (Task 6).
3. Reprocess zweimal hintereinander → identische Zeilenzahlen in `activity` und `activity_record`, keine Dubletten, keine alten Kadenzwerte (Task 7).
4. Eine als gelöscht markierte Aktivität taucht bei Garmin wieder auf → `deleted_at`/`deleted_reason` werden geleert (Task 3).
5. Sommerzeit: Offsets je Aktivität (+60 im Winter, +120 im Sommer für Europe/Berlin), Lauf kurz nach Mitternacht Ortszeit wird über das **lokale** Datum abgeglichen (Task 3, Task 6).

## Was AP 1 bewusst nicht enthält

- Abgeleitete Tabellen (`activity_stats` …) und `algo_version` — AP 2. Deshalb gibt es in AP 1 noch keinen automatischen Reprocess nach dem Sync: Der Sync normalisiert neue Daten bereits mit dem neuen Normalizer.
- Tagesgrenzen in Lokalzeit für die bestehenden Aggregate (offener Befund aus dem Doku-Abgleich, eigener Plan).

## File Structure

| Datei | Verantwortung |
|---|---|
| `alembic/versions/b8e2f4a6c1d3_activity_profile_and_soft_delete.py` (neu) | Spalten, Constraints, Indizes, `distance_m`-Seed, `activity_type` entfernen |
| `src/kairos/db/models.py` | ORM-Spalten für `Activity` |
| `src/kairos/connectors/garmin/sport_profile.py` (neu) | `typeKey`/`parentTypeId` → Sportprofil |
| `src/kairos/connectors/garmin/normalize.py` | `activity_list`: neue Felder; `activity_fit`: `distance_m`, Kadenz |
| `src/kairos/connectors/garmin/connector.py` | zusätzliche FIT-Messages, Pause zwischen FIT-Downloads |
| `src/kairos/config.py` | `garmin_fit_download_pause_s` |
| `src/kairos/repositories/canonical.py` | Upsert aller fachlichen Spalten; `reconcile_deleted_activities()` |
| `src/kairos/ingestion/service.py` | optionaler `after_window`-Hook |
| `src/kairos/routers/sync.py` | Hook setzen, Pause durchreichen |
| `src/kairos/repositories/metrics_recompute.py`, `metrics_data.py`, `data_read.py` | gelöschte Aktivitäten ausschließen |
| `src/kairos/ingestion/reprocess.py` (neu) | Reprocess aus `raw_payload` |
| `src/kairos/routers/activities.py` (neu), `src/kairos/api.py` | `POST /api/activities/reprocess` |
| `tests/fixtures/garmin/activity_list_item.json` (neu) | echtes, anonymisiertes `activity_list`-Element |

---

### Task 1: Migration und ORM für `activity`

**Files:**
- Create: `alembic/versions/b8e2f4a6c1d3_activity_profile_and_soft_delete.py`
- Modify: `src/kairos/db/models.py:286-317` (`Activity`)
- Test: `tests/test_activity_schema_integration.py`

**Interfaces:**
- Produces: `Activity`-Attribute `sport_profile: str`, `garmin_type_id: int | None`, `garmin_parent_type_id: int | None`, `description: str | None`, `start_local: datetime | None` (naiv), `utc_offset_min: int | None`, `moving_duration_s: float | None`, `avg_speed_mps: float | None`, `lap_count: int | None`, `garmin_training_load: float | None`, `garmin_vo2max: float | None`, `deleted_at: datetime | None`, `deleted_reason: str | None`. `activity_type` existiert nicht mehr. `metric_def.code = 'distance_m'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_activity_schema_integration.py
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _user(session: AsyncSession) -> str:
    uid = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'T', :s, 'UTC', 'user')"
        ),
        {"id": uid, "e": f"{uid}@t.de", "s": uid},
    )
    return uid


@pytest.mark.asyncio
async def test_activity_has_profile_and_soft_delete_columns(session: AsyncSession) -> None:
    cols = {
        r[0]
        for r in (
            await session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='activity'")
            )
        ).all()
    }
    assert {
        "sport_profile", "garmin_type_id", "garmin_parent_type_id", "description",
        "start_local", "utc_offset_min", "moving_duration_s", "avg_speed_mps", "lap_count",
        "garmin_training_load", "garmin_vo2max", "deleted_at", "deleted_reason",
    } <= cols
    assert "activity_type" not in cols


@pytest.mark.asyncio
async def test_sport_profile_defaults_to_generic_and_is_checked(session: AsyncSession) -> None:
    uid = await _user(session)
    await session.execute(
        text("INSERT INTO activity (user_id, external_id) VALUES (:u, 'a1')"), {"u": uid}
    )
    profile = (
        await session.execute(text("SELECT sport_profile FROM activity WHERE external_id='a1'"))
    ).scalar_one()
    assert profile == "generic"
    with pytest.raises(IntegrityError):
        await session.execute(
            text("INSERT INTO activity (user_id, external_id, sport_profile) VALUES (:u, 'a2', 'climbing')"),
            {"u": uid},
        )
    await session.rollback()


@pytest.mark.asyncio
async def test_distance_metric_is_seeded(session: AsyncSession) -> None:
    unit = (
        await session.execute(text("SELECT unit FROM metric_def WHERE code='distance_m'"))
    ).scalar_one()
    assert unit == "m"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_activity_schema_integration.py -v`
Expected: FAIL (`sport_profile` fehlt, `activity_type` vorhanden, `distance_m` fehlt).

- [ ] **Step 3: Migration schreiben**

```python
"""activity_profile_and_soft_delete

Revision ID: b8e2f4a6c1d3
Revises: 7a1c2e9d4b30
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8e2f4a6c1d3"
down_revision: str | None = "7a1c2e9d4b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NULLABLE_COLUMNS: tuple[tuple[str, sa.types.TypeEngine[object]], ...] = (
    ("garmin_type_id", sa.Integer()),
    ("garmin_parent_type_id", sa.Integer()),
    ("description", sa.Text()),
    ("start_local", sa.DateTime(timezone=False)),
    ("utc_offset_min", sa.SmallInteger()),
    ("moving_duration_s", sa.Float()),
    ("avg_speed_mps", sa.Float()),
    ("lap_count", sa.SmallInteger()),
    ("garmin_training_load", sa.Float()),
    ("garmin_vo2max", sa.Float()),
    ("deleted_at", sa.DateTime(timezone=True)),
    ("deleted_reason", sa.Text()),
)


def upgrade() -> None:
    op.add_column(
        "activity",
        sa.Column("sport_profile", sa.Text(), nullable=False, server_default="generic"),
    )
    op.create_check_constraint(
        "activity_sport_profile_check",
        "activity",
        "sport_profile IN ('running', 'cycling', 'swimming', 'hiking', 'generic')",
    )
    for name, type_ in _NULLABLE_COLUMNS:
        op.add_column("activity", sa.Column(name, type_, nullable=True))
    op.create_check_constraint(
        "activity_deleted_reason_check",
        "activity",
        "deleted_reason IN ('kairos', 'garmin_sync')",
    )
    # never read anywhere (AP 0, spec §2.1 item 7); always NULL
    op.drop_column("activity", "activity_type")
    op.create_index(
        "ix_activity_user_start_live",
        "activity",
        ["user_id", sa.text("start_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_activity_user_profile_start",
        "activity",
        ["user_id", "sport_profile", sa.text("start_at DESC")],
    )
    op.execute(
        "INSERT INTO metric_def (code, display_name, unit) "
        "VALUES ('distance_m', 'Distance', 'm') ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM activity_record WHERE metric = 'distance_m'"
    )
    op.execute("DELETE FROM metric_def WHERE code = 'distance_m'")
    op.drop_index("ix_activity_user_profile_start", table_name="activity")
    op.drop_index("ix_activity_user_start_live", table_name="activity")
    op.add_column("activity", sa.Column("activity_type", sa.Text(), nullable=True))
    op.drop_constraint("activity_deleted_reason_check", "activity", type_="check")
    for name, _ in reversed(_NULLABLE_COLUMNS):
        op.drop_column("activity", name)
    op.drop_constraint("activity_sport_profile_check", "activity", type_="check")
    op.drop_column("activity", "sport_profile")
```

- [ ] **Step 4: ORM anpassen** — in `class Activity` die Zeile `activity_type: Mapped[str | None] = mapped_column(Text)` entfernen und nach `calories` einfügen:

```python
    sport_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="generic")
    garmin_type_id: Mapped[int | None] = mapped_column(Integer)
    garmin_parent_type_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    # Garmin's local wall-clock start; the zone itself is only a numeric timeZoneId
    start_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    utc_offset_min: Mapped[int | None] = mapped_column(SmallInteger)
    moving_duration_s: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    lap_count: Mapped[int | None] = mapped_column(SmallInteger)
    garmin_training_load: Mapped[float | None] = mapped_column(Float)
    garmin_vo2max: Mapped[float | None] = mapped_column(Float)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_reason: Mapped[str | None] = mapped_column(Text)
```

und `__table_args__` ersetzen durch:

```python
    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_activity"),
        CheckConstraint(
            "sport_profile IN ('running', 'cycling', 'swimming', 'hiking', 'generic')",
            name="activity_sport_profile_check",
        ),
        CheckConstraint(
            "deleted_reason IN ('kairos', 'garmin_sync')", name="activity_deleted_reason_check"
        ),
    )
```

In `src/kairos/repositories/canonical.py` die Zeile `activity_type=d.get("activity_type"),` entfernen (sonst bricht der Insert).

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_activity_schema_integration.py tests/test_canonical_repository_integration.py tests/test_garmin_repositories_integration.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/b8e2f4a6c1d3_activity_profile_and_soft_delete.py src/kairos/db/models.py src/kairos/repositories/canonical.py tests/test_activity_schema_integration.py
git commit -m "feat(db): activity sport profile, local start, soft delete; seed distance_m"
```

---

### Task 2: Sportprofil-Zuordnung

**Files:**
- Create: `src/kairos/connectors/garmin/sport_profile.py`
- Test: `tests/test_garmin_sport_profile.py`

**Interfaces:**
- Produces: `sport_profile(type_key: str | None, parent_type_id: int | None) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_garmin_sport_profile.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kairos.connectors.garmin.sport_profile import _PROFILE_BY_KEY, sport_profile

_TYPES = json.loads(
    (Path(__file__).parent / "fixtures" / "garmin" / "activity_types.json").read_text("utf-8")
)
_BY_KEY = {t["typeKey"]: t for t in _TYPES}

# every typeKey in the operator's real history (2026-10-07) -> expected profile
_REAL = {
    "running": "running",
    "treadmill_running": "running",
    "hiking": "hiking",
    "lap_swimming": "swimming",
    "cycling": "cycling",
    "strength_training": "generic",
    "hiit": "generic",
    "breathwork": "generic",
    "resort_skiing": "generic",
}


@pytest.mark.parametrize(("key", "profile"), sorted(_REAL.items()))
def test_real_type_keys(key: str, profile: str) -> None:
    t = _BY_KEY[key]
    assert sport_profile(key, t["parentTypeId"]) == profile


def test_real_non_generic_keys_resolve_without_parent_fallback() -> None:
    for key, profile in _REAL.items():
        if profile != "generic":
            assert _PROFILE_BY_KEY[key] == profile


def test_unknown_child_falls_back_to_parent() -> None:
    assert sport_profile("some_new_running_variant", 1) == "running"
    assert sport_profile("some_new_bike", 2) == "cycling"
    assert sport_profile("some_new_swim", 26) == "swimming"


def test_missing_values_are_generic() -> None:
    assert sport_profile(None, None) == "generic"
    assert sport_profile("yoga", 29) == "generic"


def test_all_children_of_running_cycling_swimming_in_fixture_map_to_their_parent() -> None:
    parents = {1: "running", 2: "cycling", 26: "swimming"}
    for t in _TYPES:
        if t["parentTypeId"] in parents:
            assert sport_profile(t["typeKey"], t["parentTypeId"]) in (
                parents[t["parentTypeId"]],
                "hiking",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_garmin_sport_profile.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementierung**

```python
# src/kairos/connectors/garmin/sport_profile.py
from __future__ import annotations

_PROFILE_BY_KEY: dict[str, str] = {
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "running",
    "track_running": "running",
    "cycling": "cycling",
    "road_biking": "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling": "cycling",
    "indoor_cycling": "cycling",
    "virtual_ride": "cycling",
    "lap_swimming": "swimming",
    "open_water_swimming": "swimming",
    "hiking": "hiking",
    "mountaineering": "hiking",
    "walking": "hiking",
}

# Garmin parent typeIds (activity_types fixture): running=1, cycling=2, swimming=26
_PROFILE_BY_PARENT_ID: dict[int, str] = {1: "running", 2: "cycling", 26: "swimming"}


def sport_profile(type_key: str | None, parent_type_id: int | None) -> str:
    if type_key is not None and type_key in _PROFILE_BY_KEY:
        return _PROFILE_BY_KEY[type_key]
    if parent_type_id is not None and parent_type_id in _PROFILE_BY_PARENT_ID:
        return _PROFILE_BY_PARENT_ID[parent_type_id]
    return "generic"
```

- [ ] **Step 4: Run tests** — `.venv/Scripts/python -m pytest tests/test_garmin_sport_profile.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/kairos/connectors/garmin/sport_profile.py tests/test_garmin_sport_profile.py
git commit -m "feat(garmin): map Garmin activity types to Kairos sport profiles"
```

---

### Task 3: `activity_list`-Normalizer und Upsert aller fachlichen Spalten

**Files:**
- Create: `tests/fixtures/garmin/activity_list_item.json` (echtes Element, anonymisiert)
- Modify: `src/kairos/connectors/garmin/normalize.py:260-305` (`_normalize_activity_list`)
- Modify: `src/kairos/repositories/canonical.py:116-154` (`_write_activity`)
- Test: `tests/test_garmin_normalize_activity_list.py`, `tests/test_canonical_repository_integration.py`

**Interfaces:**
- Consumes: `sport_profile()` (Task 2), ORM-Spalten (Task 1).
- Produces: `CanonicalRecord(record_type="activity").data` mit den Schlüsseln `name, sport, sport_profile, garmin_type_id, garmin_parent_type_id, description, start_local (ISO-String ohne Zone oder None), utc_offset_min, end_at, distance_m, duration_s, moving_duration_s, avg_speed_mps, lap_count, avg_hr, max_hr, elevation_gain_m, calories, garmin_training_load, garmin_vo2max`.

- [ ] **Step 1: Fixture aus der Entwicklungs-DB erzeugen** (Skript im Scratchpad, nicht einchecken):

```python
# extract_activity_list_item.py — run with: .venv/Scripts/python extract_activity_list_item.py
import asyncio, gzip, json
from pathlib import Path
from sqlalchemy import text
from kairos.db.session import engine

DROP = ("ownerId", "ownerDisplayName", "ownerFullName", "ownerProfileImageUrlSmall",
        "ownerProfileImageUrlMedium", "ownerProfileImageUrlLarge", "deviceId", "userRoles")
GEO = ("startLatitude", "startLongitude", "endLatitude", "endLongitude")

async def main() -> None:
    async with engine.connect() as c:
        rows = (await c.execute(text(
            "SELECT payload_gzip FROM raw_payload WHERE kind='activity_list' ORDER BY fetched_at DESC"
        ))).all()
    await engine.dispose()
    for (blob,) in rows:
        for a in json.loads(gzip.decompress(blob)) or []:
            if a["activityType"]["typeKey"] == "running" and a.get("movingDuration"):
                for k in DROP:
                    a.pop(k, None)
                for k in GEO:
                    if a.get(k) is not None:
                        a[k] = 52.0 if "Latitude" in k else 9.0
                a["activityName"] = "Laufen"
                a["locationName"] = None
                a["activityId"] = 1000000001
                out = Path("tests/fixtures/garmin/activity_list_item.json")
                out.write_text(json.dumps(a, indent=2, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")
                print("written", a["startTimeLocal"], a["startTimeGMT"])
                return

asyncio.run(main())
```

Prüfen: `grep -n -i "owner\|maxha\|haenel" tests/fixtures/garmin/activity_list_item.json` liefert nichts.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_garmin_normalize_activity_list.py
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kairos.connectors.garmin.normalize import normalize_payload

_ITEM: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "garmin" / "activity_list_item.json").read_text("utf-8")
)


def _one(item: dict[str, Any]) -> Any:
    [rec] = normalize_payload(kind="activity_list", payload=[item])
    return rec


def test_real_item_maps_all_columns() -> None:
    rec = _one(_ITEM)
    d = rec.data
    assert rec.external_id == "1000000001"
    assert d["sport"] == "running"
    assert d["sport_profile"] == "running"
    assert d["garmin_type_id"] == _ITEM["activityType"]["typeId"]
    assert d["garmin_parent_type_id"] == _ITEM["activityType"]["parentTypeId"]
    assert d["moving_duration_s"] == _ITEM["movingDuration"]
    assert d["avg_speed_mps"] == _ITEM["averageSpeed"]
    assert d["lap_count"] == _ITEM["lapCount"]
    assert d["garmin_training_load"] == _ITEM["activityTrainingLoad"]
    assert d["garmin_vo2max"] == _ITEM["vO2MaxValue"]
    assert "activity_type" not in d
    assert d["start_local"] == _ITEM["startTimeLocal"].replace(" ", "T")


def test_utc_offset_summer_and_winter() -> None:
    summer = copy.deepcopy(_ITEM)
    summer["startTimeGMT"], summer["startTimeLocal"] = "2026-07-01 04:00:00", "2026-07-01 06:00:00"
    winter = copy.deepcopy(_ITEM)
    winter["startTimeGMT"], winter["startTimeLocal"] = "2026-01-10 23:30:00", "2026-01-11 00:30:00"
    assert _one(summer).data["utc_offset_min"] == 120
    w = _one(winter)
    assert w.data["utc_offset_min"] == 60
    assert w.occurred_at == datetime(2026, 1, 10, 23, 30, tzinfo=UTC)
    assert w.data["start_local"] == "2026-01-11T00:30:00"


def test_missing_local_time_leaves_local_fields_empty() -> None:
    item = copy.deepcopy(_ITEM)
    del item["startTimeLocal"]
    d = _one(item).data
    assert d["start_local"] is None
    assert d["utc_offset_min"] is None


def test_child_type_uses_parent_profile() -> None:
    item = copy.deepcopy(_ITEM)
    item["activityType"] = {"typeId": 18, "typeKey": "treadmill_running", "parentTypeId": 1}
    assert _one(item).data["sport_profile"] == "running"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_garmin_normalize_activity_list.py -v`
Expected: FAIL (`KeyError: 'sport_profile'` bzw. Assertion)

- [ ] **Step 4: Normalizer ersetzen** — `_normalize_activity_list` vollständig durch Folgendes ersetzen; `from kairos.connectors.garmin.sport_profile import sport_profile` und `from datetime import timedelta` oben in die Imports aufnehmen (das lokale `from datetime import timedelta` in der Funktion entfällt):

```python
def _normalize_activity_list(payload: JSONValue) -> list[CanonicalRecord]:
    # get_activities_by_date -> list of activity summary dicts
    if not isinstance(payload, list):
        return []
    records: list[CanonicalRecord] = []
    for act in payload:
        if not isinstance(act, dict):
            continue
        activity_id = act.get("activityId")
        if activity_id is None:
            continue
        gmt_raw = act.get("startTimeGMT")
        occurred_at = _parse_datetime_utc(str(gmt_raw)) if isinstance(gmt_raw, str) else None
        local_raw = act.get("startTimeLocal")
        start_local = _parse_naive(local_raw) if isinstance(local_raw, str) else None

        type_obj = act.get("activityType")
        type_key = type_obj.get("typeKey") if isinstance(type_obj, dict) else None
        type_id = type_obj.get("typeId") if isinstance(type_obj, dict) else None
        parent_id = type_obj.get("parentTypeId") if isinstance(type_obj, dict) else None

        duration = act.get("duration") or act.get("elapsedDuration")
        end_at = None
        if occurred_at is not None and isinstance(duration, int | float) and duration > 0:
            end_at = occurred_at + timedelta(seconds=duration)

        utc_offset_min = None
        if occurred_at is not None and start_local is not None:
            delta = start_local - occurred_at.replace(tzinfo=None)
            utc_offset_min = round(delta.total_seconds() / 60)

        records.append(CanonicalRecord(
            record_type="activity",
            external_id=str(activity_id),
            occurred_at=occurred_at,
            data={
                "name": act.get("activityName"),
                "sport": type_key if isinstance(type_key, str) else None,
                "sport_profile": sport_profile(
                    type_key if isinstance(type_key, str) else None,
                    parent_id if isinstance(parent_id, int) else None,
                ),
                "garmin_type_id": type_id if isinstance(type_id, int) else None,
                "garmin_parent_type_id": parent_id if isinstance(parent_id, int) else None,
                "description": act.get("description"),
                "start_local": start_local.isoformat() if start_local else None,
                "utc_offset_min": utc_offset_min,
                "end_at": end_at.isoformat() if end_at else None,
                "distance_m": act.get("distance"),
                "duration_s": duration,
                "moving_duration_s": act.get("movingDuration"),
                "avg_speed_mps": act.get("averageSpeed"),
                "lap_count": act.get("lapCount"),
                "avg_hr": act.get("averageHR"),
                "max_hr": act.get("maxHR"),
                "elevation_gain_m": act.get("elevationGain"),
                "calories": act.get("calories"),
                "garmin_training_load": act.get("activityTrainingLoad"),
                "garmin_vo2max": act.get("vO2MaxValue"),
            },
        ))
    return records


def _parse_naive(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=None)
    except ValueError:
        return None
```

- [ ] **Step 5: Run unit tests** — `.venv/Scripts/python -m pytest tests/test_garmin_normalize_activity_list.py tests/test_garmin_normalize.py -v` → PASS (bestehende Normalizer-Tests, die `activity_type` erwarten, an das neue Ergebnis anpassen: der Schlüssel existiert nicht mehr).

- [ ] **Step 6: Failing integration test für den Upsert** — an `tests/test_canonical_repository_integration.py` anhängen:

```python
def _activity_record(start: datetime, **extra: object) -> CanonicalRecord:
    data: dict[str, object] = {
        "name": "Lauf", "sport": "running", "sport_profile": "running",
        "garmin_type_id": 1, "garmin_parent_type_id": 17, "description": None,
        "start_local": (start + timedelta(hours=2)).replace(tzinfo=None).isoformat(),
        "utc_offset_min": 120, "end_at": (start + timedelta(minutes=50)).isoformat(),
        "distance_m": 10000.0, "duration_s": 3000.0, "moving_duration_s": 2950.0,
        "avg_speed_mps": 3.4, "lap_count": 10, "avg_hr": 150, "max_hr": 170,
        "elevation_gain_m": 50.0, "calories": 600, "garmin_training_load": 120.0,
        "garmin_vo2max": 52.0,
    }
    data.update(extra)
    return CanonicalRecord(record_type="activity", external_id="ext-upsert", occurred_at=start, data=data)


@pytest.mark.asyncio
async def test_activity_upsert_updates_times_and_clears_soft_delete(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id, "upsert-all@test.com", "sub-upsert-all")
    raw_id = await SqlRawPayloadRepository(session=session).upsert(
        user_id=user_id, connector_id="garmin", kind="activity_list",
        window=Window(start=datetime(2026, 7, 1, tzinfo=UTC), end=datetime(2026, 7, 2, tzinfo=UTC)),
        payload=[], content_hash=b"hash-upsert-all",
    )
    repo = SqlCanonicalRepository(session)
    first = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    await repo.upsert_many(user_id=user_id, connector_id="garmin", kind="activity_list",
                           records=[_activity_record(first)], raw_payload_id=raw_id)
    await session.execute(
        text("UPDATE activity SET deleted_at = now(), deleted_reason = 'garmin_sync' "
             "WHERE external_id = 'ext-upsert'")
    )
    moved = first + timedelta(minutes=5)
    await repo.upsert_many(user_id=user_id, connector_id="garmin", kind="activity_list",
                           records=[_activity_record(moved, name="Lauf neu")], raw_payload_id=raw_id)
    row = (await session.execute(text(
        "SELECT name, start_at, start_local, utc_offset_min, sport_profile, moving_duration_s, "
        "deleted_at, deleted_reason FROM activity WHERE external_id = 'ext-upsert'"
    ))).one()
    assert row.name == "Lauf neu"
    assert row.start_at == moved
    assert row.start_local == datetime(2026, 7, 1, 6, 5)
    assert (row.utc_offset_min, row.sport_profile, row.moving_duration_s) == (120, "running", 2950.0)
    assert row.deleted_at is None and row.deleted_reason is None
```

Run: `.venv/Scripts/python -m pytest tests/test_canonical_repository_integration.py -v` → FAIL.

- [ ] **Step 7: `_write_activity` ersetzen**

```python
    async def _write_activity(
        self, user_id: UUID, record: CanonicalRecord, raw_payload_id: int
    ) -> None:
        if not isinstance(record.data, dict):
            return
        d = record.data
        values = {
            "name": d.get("name"),
            "sport": d.get("sport"),
            "sport_profile": d.get("sport_profile") or "generic",
            "garmin_type_id": d.get("garmin_type_id"),
            "garmin_parent_type_id": d.get("garmin_parent_type_id"),
            "description": d.get("description"),
            "start_at": record.occurred_at,
            "start_local": _parse_naive_dt(d.get("start_local")),
            "utc_offset_min": d.get("utc_offset_min"),
            "end_at": _parse_dt(d.get("end_at")),
            "distance_m": d.get("distance_m"),
            "duration_s": d.get("duration_s"),
            "moving_duration_s": d.get("moving_duration_s"),
            "avg_speed_mps": d.get("avg_speed_mps"),
            "lap_count": d.get("lap_count"),
            "avg_hr": d.get("avg_hr"),
            "max_hr": d.get("max_hr"),
            "elevation_gain_m": d.get("elevation_gain_m"),
            "calories": d.get("calories"),
            "garmin_training_load": d.get("garmin_training_load"),
            "garmin_vo2max": d.get("garmin_vo2max"),
            "raw_payload_id": raw_payload_id,
        }
        stmt = (
            insert(Activity)
            .values(user_id=user_id, external_id=record.external_id, **values)
            .on_conflict_do_update(
                constraint="uq_activity",
                # an activity that reappears at Garmin is no longer deleted
                set_={**values, "deleted_at": None, "deleted_reason": None},
            )
        )
        await self._session.execute(stmt)
```

und unten in der Datei ergänzen:

```python
def _parse_naive_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None
```

- [ ] **Step 8: Run tests** — `.venv/Scripts/python -m pytest tests/test_canonical_repository_integration.py tests/test_garmin_normalize_activity_list.py -v` → PASS

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/garmin/activity_list_item.json src/kairos/connectors/garmin/normalize.py src/kairos/repositories/canonical.py tests/test_garmin_normalize_activity_list.py tests/test_canonical_repository_integration.py tests/test_garmin_normalize.py
git commit -m "feat(garmin): full activity summary incl. profile and local start, upsert all fields"
```

---

### Task 4: FIT — Distanz, Garmin-genaue Kadenz, zusätzliche Messages

**Files:**
- Modify: `src/kairos/connectors/garmin/normalize.py:308-374` (`_FIT_FIELDS`, `_normalize_activity_fit`)
- Modify: `src/kairos/connectors/garmin/connector.py:81-86`
- Test: `tests/test_garmin_normalize_activity_fit.py`

**Interfaces:**
- Produces: `activity_record`-Metrik `distance_m`; `cadence` = `cadence + fractional_cadence`; FIT-Payload-Schlüssel `lengths`, `events`, `workouts`, `workout_steps` zusätzlich zu `records`, `sessions`, `laps`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_garmin_normalize_activity_fit.py
from __future__ import annotations

from unittest.mock import create_autospec

from garminconnect import Garmin

from kairos.connectors.garmin import connector as connector_mod
from kairos.connectors.garmin.connector import GarminConnector
from kairos.connectors.garmin.normalize import normalize_payload


def _payload(rec: dict[str, object]) -> dict[str, object]:
    return {"activities": [{"activity_id": "42", "records": [rec], "sessions": [], "laps": []}]}


def _metrics(rec: dict[str, object]) -> dict[str, float]:
    out = normalize_payload(kind="activity_fit", payload=_payload(rec))
    return {r.data["metric"]: r.data["value"] for r in out}  # type: ignore[index]


def test_distance_is_stored_as_distance_m() -> None:
    m = _metrics({"timestamp": "2026-10-07T04:30:00+00:00", "distance": 1234.5})
    assert m["distance_m"] == 1234.5


def test_cadence_includes_fractional_part() -> None:
    m = _metrics({"timestamp": "2026-10-07T04:30:00+00:00", "cadence": 79, "fractional_cadence": 0.5})
    assert m["cadence"] == 79.5


def test_cadence_without_fractional_part_is_unchanged() -> None:
    m = _metrics({"timestamp": "2026-10-07T04:30:00+00:00", "cadence": 80})
    assert m["cadence"] == 80.0


def test_connector_archives_extra_fit_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    garmin = create_autospec(Garmin, instance=True)
    garmin.get_activities_by_date.return_value = [{"activityId": 42}]
    garmin.download_activity.return_value = b"zip"
    messages = {
        "record_mesgs": [], "session_mesgs": [], "lap_mesgs": [],
        "length_mesgs": [{"length_type": "active"}], "event_mesgs": [{"event": "timer"}],
        "workout_mesgs": [{"wkt_name": "x"}], "workout_step_mesgs": [{"message_index": 0}],
    }
    monkeypatch.setattr(connector_mod, "decode_fit_zip", lambda _b: messages)
    payload = GarminConnector(garmin)._fetch_activity_fits("2026-10-07", "2026-10-08")
    [act] = payload["activities"]  # type: ignore[index]
    assert act["lengths"] == [{"length_type": "active"}]
    assert act["events"] == [{"event": "timer"}]
    assert act["workouts"] == [{"wkt_name": "x"}]
    assert act["workout_steps"] == [{"message_index": 0}]
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_garmin_normalize_activity_fit.py -v` → FAIL

- [ ] **Step 3: Implementierung** — in `_FIT_FIELDS` nach `"temperature"` ergänzen:

```python
    "distance":           ("distance_m",  False),
```

In `_normalize_activity_fit` die Wertberechnung ersetzen durch:

```python
                value = _semicircle_to_deg(raw_val) if is_semicircle else float(raw_val)
                if field == "cadence":
                    # Garmin's own spm = 2 * (cadence + fractional_cadence), AP 0: 219/219
                    frac = rec.get("fractional_cadence")
                    if isinstance(frac, int | float):
                        value += float(frac)
```

In `connector.py` das `result.append({...})` ersetzen durch:

```python
                result.append({
                    "activity_id": str(activity_id),
                    "records": cast(JSONValue, records_to_json(messages.get("record_mesgs", []))),
                    "sessions": cast(JSONValue, records_to_json(messages.get("session_mesgs", []))),
                    "laps": cast(JSONValue, records_to_json(messages.get("lap_mesgs", []))),
                    "lengths": cast(JSONValue, records_to_json(messages.get("length_mesgs", []))),
                    "events": cast(JSONValue, records_to_json(messages.get("event_mesgs", []))),
                    "workouts": cast(JSONValue, records_to_json(messages.get("workout_mesgs", []))),
                    "workout_steps": cast(
                        JSONValue, records_to_json(messages.get("workout_step_mesgs", []))
                    ),
                })
```

- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest tests/test_garmin_normalize_activity_fit.py tests/test_garmin_normalize.py tests/test_garmin_connector_kinds.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/kairos/connectors/garmin/normalize.py src/kairos/connectors/garmin/connector.py tests/test_garmin_normalize_activity_fit.py
git commit -m "feat(garmin): store FIT distance, Garmin-exact cadence, archive lengths/events/workout steps"
```

---

### Task 5: Pause zwischen FIT-Downloads

**Files:**
- Modify: `src/kairos/config.py:21`, `src/kairos/connectors/garmin/connector.py:18-21,65-91`, `src/kairos/routers/sync.py` (Konstruktion von `GarminConnector`)
- Test: `tests/test_garmin_normalize_activity_fit.py`

**Interfaces:**
- Produces: `GarminConnector(garmin, *, fit_download_pause_s: float = 0.0, sleep: Callable[[float], None] = time.sleep)`; `settings.garmin_fit_download_pause_s: float = 2.0`.

- [ ] **Step 1: Write the failing test** — anhängen:

```python
def test_pause_between_fit_downloads_not_before_first(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    garmin = create_autospec(Garmin, instance=True)
    garmin.get_activities_by_date.return_value = [{"activityId": 1}, {"activityId": 2}, {"activityId": 3}]
    garmin.download_activity.return_value = b"zip"
    monkeypatch.setattr(connector_mod, "decode_fit_zip", lambda _b: {})
    sleeps: list[float] = []
    GarminConnector(garmin, fit_download_pause_s=2.0, sleep=sleeps.append)._fetch_activity_fits(
        "2026-10-07", "2026-10-08"
    )
    assert sleeps == [2.0, 2.0]
```

- [ ] **Step 2: Run** → FAIL (`unexpected keyword argument`)

- [ ] **Step 3: Implementierung** — `connector.py`:

```python
import time
from collections.abc import Callable, Sequence
...
    def __init__(
        self,
        garmin: Any,
        *,
        fit_download_pause_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # garmin is an authenticated garminconnect.Garmin instance
        self._garmin = garmin
        self._fit_download_pause_s = fit_download_pause_s
        self._sleep = sleep
```

In `_fetch_activity_fits` direkt vor `try:` innerhalb der Schleife:

```python
            if result and self._fit_download_pause_s > 0:
                self._sleep(self._fit_download_pause_s)
```

`config.py` nach `garmin_backfill_throttle_seconds`:

```python
    garmin_fit_download_pause_s: float = 2.0
```

`routers/sync.py` in `_run_backfill_task`:

```python
        connector = GarminConnector(
            garmin, fit_download_pause_s=settings.garmin_fit_download_pause_s
        )
```

- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest tests/test_garmin_normalize_activity_fit.py tests/test_sync_router.py tests/test_config.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/kairos/config.py src/kairos/connectors/garmin/connector.py src/kairos/routers/sync.py tests/test_garmin_normalize_activity_fit.py
git commit -m "fix(garmin): pause between FIT downloads within a window"
```

---

### Task 6: Lösch-Abgleich und gelöschte Aktivitäten ausblenden

**Files:**
- Modify: `src/kairos/repositories/canonical.py` (neue Methode), `src/kairos/ingestion/service.py` (Hook), `src/kairos/routers/sync.py` (Hook setzen)
- Modify: `src/kairos/repositories/metrics_recompute.py:23-37`, `src/kairos/repositories/metrics_data.py:104-108`, `src/kairos/repositories/data_read.py:58-105`
- Test: `tests/test_activity_reconcile_integration.py`, `tests/test_sync_service.py`

**Interfaces:**
- Consumes: `Activity.start_local`, `deleted_at`, `deleted_reason` (Task 1).
- Produces:
  - `SqlCanonicalRepository.reconcile_deleted_activities(*, user_id: UUID, first_day: date, last_day: date, seen_external_ids: set[str], now: datetime) -> int` (Anzahl markierter Aktivitäten)
  - `AfterWindow = Callable[[UUID, str, Window, JSONValue], Awaitable[None]]`; `SyncService(..., after_window: AfterWindow | None = None)` — wird nach erfolgreichem `upsert_many` und vor `mark_success` aufgerufen.

- [ ] **Step 1: Failing integration test**

```python
# tests/test_activity_reconcile_integration.py
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.canonical import SqlCanonicalRepository


async def _setup(session: AsyncSession) -> UUID:
    uid = uuid4()
    await session.execute(
        text("INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
             "VALUES (:id, :e, 'T', :s, 'UTC', 'user')"),
        {"id": str(uid), "e": f"{uid}@t.de", "s": str(uid)},
    )
    rows = [
        ("keep", "2026-05-29 08:00:00", datetime(2026, 5, 29, 6, 0, tzinfo=UTC)),
        ("gone", "2026-05-29 02:05:30", datetime(2026, 5, 28, 23, 5, 30, tzinfo=UTC)),
        ("other-day", "2026-05-31 08:00:00", datetime(2026, 5, 31, 6, 0, tzinfo=UTC)),
        ("no-local", None, datetime(2026, 5, 29, 9, 0, tzinfo=UTC)),
    ]
    for ext, local, start in rows:
        await session.execute(
            text("INSERT INTO activity (user_id, external_id, start_at, start_local) "
                 "VALUES (:u, :x, :s, CAST(:l AS timestamp))"),
            {"u": str(uid), "x": ext, "s": start, "l": local},
        )
    return uid


@pytest.mark.asyncio
async def test_marks_only_unseen_activities_by_local_date(session: AsyncSession) -> None:
    uid = await _setup(session)
    n = await SqlCanonicalRepository(session).reconcile_deleted_activities(
        user_id=uid, first_day=date(2026, 5, 29), last_day=date(2026, 5, 30),
        seen_external_ids={"keep"}, now=datetime(2026, 10, 13, tzinfo=UTC),
    )
    assert n == 1
    rows = dict((await session.execute(text(
        "SELECT external_id, deleted_reason FROM activity WHERE user_id = :u"), {"u": str(uid)}
    )).all())
    assert rows == {"keep": None, "gone": "garmin_sync", "other-day": None, "no-local": None}


@pytest.mark.asyncio
async def test_empty_response_marks_all_dated_activities_in_window(session: AsyncSession) -> None:
    uid = await _setup(session)
    n = await SqlCanonicalRepository(session).reconcile_deleted_activities(
        user_id=uid, first_day=date(2026, 5, 29), last_day=date(2026, 5, 29),
        seen_external_ids=set(), now=datetime(2026, 10, 13, tzinfo=UTC),
    )
    assert n == 2
```

- [ ] **Step 2: Run** — FAIL (`AttributeError`)

- [ ] **Step 3: Repository-Methode** in `SqlCanonicalRepository` (Imports: `date` aus `datetime`, `func`, `update` aus `sqlalchemy`):

```python
    async def reconcile_deleted_activities(
        self,
        *,
        user_id: UUID,
        first_day: date,
        last_day: date,
        seen_external_ids: set[str],
        now: datetime,
    ) -> int:
        # Garmin filters by local start date; rows without start_local are never touched
        local_day = func.date(Activity.start_local)
        stmt = (
            update(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.deleted_at.is_(None),
                Activity.start_local.is_not(None),
                local_day >= first_day,
                local_day <= last_day,
                Activity.external_id.not_in(seen_external_ids),
            )
            .values(deleted_at=now, deleted_reason="garmin_sync")
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
```

Run: `.venv/Scripts/python -m pytest tests/test_activity_reconcile_integration.py -v` → PASS

- [ ] **Step 4: Failing unit test für den Hook** — an `tests/test_sync_service.py` anhängen (verwendet die vorhandenen Fakes der Datei; Namen dort nachsehen und genauso konstruieren wie in `test_sync_service_orchestrates_steps_in_order`):

```python
@pytest.mark.asyncio
async def test_after_window_hook_runs_after_upsert_and_not_on_failure() -> None:
    events: list[str] = []
    calls: list[tuple[str, object]] = []

    async def hook(user_id: UUID, kind: str, window: Window, payload: object) -> None:
        events.append("after_window")
        calls.append((kind, payload))

    service = SyncService(
        raw_repo=FakeRawRepo(events),
        canonical_repo=FakeCanonicalRepo(events),
        sync_state_repo=FakeSyncStateRepo(events),
        hash_payload=payload_sha256,
        after_window=hook,
    )
    window = Window(start=datetime(2026, 5, 29, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    await service.run_window(connector=SpyConnector(events), user_id=uuid4(), kind="activity_list", window=window)
    assert events.index("after_window") > events.index("upsert_many")
    assert events.index("after_window") < events.index("mark_success")
    assert calls[0][0] == "activity_list"

    # a failed fetch must never reach the hook (no deletion without a complete response)
    events.clear()
    calls.clear()
    with pytest.raises(RuntimeError):
        await service.run_window(
            connector=FailingConnector(events), user_id=uuid4(), kind="activity_list", window=window
        )
    assert calls == []
```

(Die Fakes heißen in dieser Datei `SpyConnector`, `FailingConnector` usw.; die Raw-/Canonical-/State-Fakes und die Event-Namen `upsert_many`/`mark_success` an die Strings anpassen, die die Fakes in dieser Datei tatsächlich anhängen.)

Run → FAIL (`unexpected keyword argument 'after_window'`).

- [ ] **Step 5: Hook im SyncService** — in `ingestion/service.py`:

```python
AfterWindow = Callable[[UUID, str, Window, JSONValue], Awaitable[None]]
```

(`Awaitable` aus `collections.abc` importieren), Konstruktor-Parameter `after_window: AfterWindow | None = None` → `self._after_window = after_window`, und in `run_window` direkt nach `records_written = await self._canonical_repo.upsert_many(...)`:

```python
            if self._after_window is not None:
                await self._after_window(user_id, kind, envelope.window, envelope.payload)
```

- [ ] **Step 6: Hook in `routers/sync.py` setzen** — in `_run_backfill_task` nach dem Erzeugen von `canonical_repo` (die Instanz in einer Variablen halten und an `SyncService` übergeben):

```python
        canonical_repo = SqlCanonicalRepository(session=session)

        async def reconcile(
            uid: UUID, kind: str, window: Window, payload: JSONValue
        ) -> None:
            # only a complete list response may delete anything
            if kind != "activity_list" or not isinstance(payload, list):
                return
            seen = {
                str(a["activityId"])
                for a in payload
                if isinstance(a, dict) and a.get("activityId") is not None
            }
            # get_activities_by_date(d, d+1) covers both days inclusive
            await canonical_repo.reconcile_deleted_activities(
                user_id=uid, first_day=window.start.date(), last_day=window.end.date(),
                seen_external_ids=seen, now=datetime.now(UTC),
            )
```

und `SyncService(..., canonical_repo=canonical_repo, ..., after_window=reconcile)`. Imports `Window`, `JSONValue` aus `kairos.connectors.types`.

- [ ] **Step 7: Gelöschte Aktivitäten ausblenden** — failing Test an `tests/test_metrics_recompute_integration.py` anhängen (Hilfsfunktionen der Datei verwenden; Muster: Nutzer + Aktivität + 60 HF-Records anlegen, dann `deleted_at` setzen):

```python
@pytest.mark.asyncio
async def test_hr_buckets_exclude_deleted_activities(session: AsyncSession) -> None:
    uid = uuid4()
    await _insert_user(session, uid)  # vorhandene Hilfsfunktion der Datei
    act_id = (await session.execute(text(
        "INSERT INTO activity (user_id, external_id, start_at, deleted_at, deleted_reason) "
        "VALUES (:u, 'del', '2026-05-29 06:00+00', now(), 'garmin_sync') RETURNING id"),
        {"u": str(uid)})).scalar_one()
    await session.execute(text(
        "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
        "SELECT :u, :a, '2026-05-29 06:00+00'::timestamptz + make_interval(secs => g), 'hr', 140 "
        "FROM generate_series(0, 59) g"), {"u": str(uid), "a": act_id})
    install_rls_listener(session, uid)
    await recompute_hr_bucket_seconds_daily(session, user_id=uid, start=date(2026, 5, 29), end=date(2026, 5, 29))
    n = (await session.execute(text(
        "SELECT count(*) FROM hr_bucket_seconds_daily WHERE user_id = :u"), {"u": str(uid)})).scalar_one()
    assert n == 0
```

Implementierung `metrics_recompute.py` — im `INSERT … SELECT` von `recompute_hr_bucket_seconds_daily` die WHERE-Klausel ergänzen:

```sql
              AND activity_id IN (
                  SELECT id FROM activity WHERE user_id = :uid AND deleted_at IS NULL
              )
```

`metrics_data.py:observed_max_hr_ever`:

```python
        text("SELECT max(max_hr) FROM activity WHERE user_id = :uid AND deleted_at IS NULL"),
```

`data_read.py`: in `list_activities` `select(Activity).where(Activity.user_id == user_id, Activity.deleted_at.is_(None))`, in `get_activity_detail` die Bedingung `Activity.deleted_at.is_(None)` ergänzen.

- [ ] **Step 8: Run** — `.venv/Scripts/python -m pytest tests/test_activity_reconcile_integration.py tests/test_sync_service.py tests/test_metrics_recompute_integration.py tests/test_data_read_repository.py tests/test_sync_router.py tests/test_backfill_cursor.py -v` → PASS

- [ ] **Step 9: Commit**

```bash
git add src/kairos/repositories/canonical.py src/kairos/ingestion/service.py src/kairos/routers/sync.py src/kairos/repositories/metrics_recompute.py src/kairos/repositories/metrics_data.py src/kairos/repositories/data_read.py tests/test_activity_reconcile_integration.py tests/test_sync_service.py tests/test_metrics_recompute_integration.py
git commit -m "feat(sync): mark activities deleted at Garmin, exclude them from metrics and reads"
```

---

### Task 7: Reprocess-Service

**Files:**
- Create: `src/kairos/ingestion/reprocess.py`
- Test: `tests/test_activity_reprocess_integration.py`

**Interfaces:**
- Consumes: `normalize_payload`, `SqlCanonicalRepository.upsert_many`, Recompute-Funktionen.
- Produces:

```python
@dataclass(frozen=True)
class ReprocessResult:
    activities: int
    records: int
    first_day: date | None
    last_day: date | None

async def reprocess_activities(
    session: AsyncSession, *, user_id: UUID,
    from_date: date | None = None, to_date: date | None = None,
    activity_ids: set[str] | None = None,
) -> ReprocessResult
```

Der Aufrufer hat `install_rls_listener(session, user_id)` gesetzt und committet.

- [ ] **Step 1: Failing integration test**

```python
# tests/test_activity_reprocess_integration.py
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import Window
from kairos.db.rls import install_rls_listener
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.reprocess import reprocess_activities
from kairos.repositories.raw_payload import SqlRawPayloadRepository

_ITEM = json.loads(
    (Path(__file__).parent / "fixtures" / "garmin" / "activity_list_item.json").read_text("utf-8")
)
_DAY = datetime.fromisoformat(_ITEM["startTimeGMT"].replace(" ", "T")).replace(tzinfo=UTC)


def _fit(cadence: int) -> dict[str, object]:
    recs = [
        {"timestamp": _DAY.replace(second=s).isoformat(), "heart_rate": 140, "cadence": cadence,
         "fractional_cadence": 0.5, "distance": float(s * 3)}
        for s in range(10)
    ]
    return {"activities": [{"activity_id": "1000000001", "records": recs, "sessions": [], "laps": []}]}


async def _seed(session: AsyncSession) -> UUID:
    uid = uuid4()
    await session.execute(
        text("INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
             "VALUES (:id, :e, 'T', :s, 'UTC', 'user')"),
        {"id": str(uid), "e": f"{uid}@t.de", "s": str(uid)},
    )
    raw = SqlRawPayloadRepository(session=session)
    w = Window(start=_DAY.replace(hour=0, minute=0, second=0), end=_DAY.replace(hour=23))
    for kind, payload in (("activity_list", [_ITEM]), ("activity_fit", _fit(70)), ("activity_fit", _fit(79))):
        await raw.upsert(user_id=uid, connector_id="garmin", kind=kind, window=w,
                         payload=payload, content_hash=payload_sha256(payload))
    # legacy row as written before AP 1
    await session.execute(text(
        "INSERT INTO activity (user_id, external_id, start_at) VALUES (:u, '1000000001', :s)"),
        {"u": str(uid), "s": _DAY})
    return uid


@pytest.mark.asyncio
async def test_reprocess_rebuilds_from_raw_payload_and_is_idempotent(session: AsyncSession) -> None:
    uid = await _seed(session)
    install_rls_listener(session, uid)
    first = await reprocess_activities(session, user_id=uid)
    second = await reprocess_activities(session, user_id=uid)
    assert first.activities == second.activities == 1
    assert first.records == second.records == 30  # 10 x (hr, cadence, distance_m)
    row = (await session.execute(text(
        "SELECT sport_profile, start_local FROM activity WHERE user_id = :u"), {"u": str(uid)})).one()
    assert row.sport_profile == "running" and row.start_local is not None
    counts = dict((await session.execute(text(
        "SELECT metric, count(*) FROM activity_record WHERE user_id = :u GROUP BY metric"),
        {"u": str(uid)})).all())
    assert counts == {"hr": 10, "cadence": 10, "distance_m": 10}
    cadence = (await session.execute(text(
        "SELECT DISTINCT value FROM activity_record WHERE user_id = :u AND metric = 'cadence'"),
        {"u": str(uid)})).scalars().all()
    # the newest payload (79) wins, incl. the fractional part
    assert cadence == [79.5]


@pytest.mark.asyncio
async def test_reprocess_filters_by_activity_ids(session: AsyncSession) -> None:
    uid = await _seed(session)
    install_rls_listener(session, uid)
    result = await reprocess_activities(session, user_id=uid, activity_ids={"does-not-exist"})
    assert (result.activities, result.records) == (0, 0)
```

- [ ] **Step 2: Run** — FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementierung**

```python
# src/kairos/ingestion/reprocess.py
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.garmin.normalize import normalize_payload
from kairos.connectors.types import JSONValue
from kairos.repositories.canonical import SqlCanonicalRepository
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_metric_daily_values,
)


@dataclass(frozen=True)
class ReprocessResult:
    activities: int
    records: int
    first_day: date | None
    last_day: date | None


async def reprocess_activities(
    session: AsyncSession,
    *,
    user_id: UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    activity_ids: set[str] | None = None,
) -> ReprocessResult:
    repo = SqlCanonicalRepository(session)
    touched: set[str] = set()

    # activity_list first: activity_record needs activity.id; later payloads overwrite earlier ones
    for payload_id, payload in await _payloads(session, user_id, "activity_list", from_date, to_date):
        if not isinstance(payload, list):
            continue
        items = [a for a in payload if isinstance(a, dict) and _wanted(a.get("activityId"), activity_ids)]
        records = normalize_payload(kind="activity_list", payload=items)
        await repo.upsert_many(user_id=user_id, connector_id="garmin", kind="activity_list",
                               records=records, raw_payload_id=payload_id)
        touched.update(r.external_id for r in records)

    # one FIT per activity: the newest payload wins; only ids are kept to bound memory
    newest: dict[str, int] = {}
    for payload_id, payload in await _payloads(session, user_id, "activity_fit", from_date, to_date):
        for act in _fit_activities(payload):
            if _wanted(act.get("activity_id"), activity_ids):
                newest[str(act["activity_id"])] = payload_id

    records_written = 0
    by_payload: dict[int, set[str]] = {}
    for activity_id, payload_id in newest.items():
        by_payload.setdefault(payload_id, set()).add(activity_id)
    for payload_id, ids in by_payload.items():
        payload = await _payload(session, payload_id)
        acts = [a for a in _fit_activities(payload) if str(a.get("activity_id")) in ids]
        await session.execute(
            text("DELETE FROM activity_record WHERE user_id = :u AND activity_id IN "
                 "(SELECT id FROM activity WHERE user_id = :u AND external_id = ANY(:ids))"),
            {"u": str(user_id), "ids": sorted(ids)},
        )
        records = normalize_payload(kind="activity_fit", payload={"activities": acts})
        records_written += await repo.upsert_many(user_id=user_id, connector_id="garmin",
                                                  kind="activity_fit", records=records,
                                                  raw_payload_id=payload_id)
        touched.update(ids)

    first_day, last_day = await _day_range(session, user_id, touched)
    if first_day is not None and last_day is not None:
        await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=first_day, end=last_day)
        await recompute_metric_daily_values(session, user_id=user_id, start=first_day, end=date.today())
    return ReprocessResult(len(touched), records_written, first_day, last_day)


def _wanted(activity_id: object, activity_ids: set[str] | None) -> bool:
    return activity_id is not None and (activity_ids is None or str(activity_id) in activity_ids)


def _fit_activities(payload: JSONValue) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("activities"), list):
        return []
    return [a for a in payload["activities"] if isinstance(a, dict) and "error" not in a]


async def _payloads(
    session: AsyncSession, user_id: UUID, kind: str, from_date: date | None, to_date: date | None
) -> list[tuple[int, JSONValue]]:
    # a window fetches (d, d+1), so widen by a day on both sides
    rows = (await session.execute(
        text("SELECT id, payload_gzip FROM raw_payload WHERE user_id = :u AND kind = :k "
             "AND (CAST(:f AS date) IS NULL OR window_start::date >= CAST(:f AS date)) "
             "AND (CAST(:t AS date) IS NULL OR window_start::date <= CAST(:t AS date)) "
             "ORDER BY fetched_at, id"),
        {"u": str(user_id), "k": kind,
         "f": from_date - timedelta(days=1) if from_date else None,
         "t": to_date + timedelta(days=1) if to_date else None},
    )).all()
    return [(int(r.id), json.loads(gzip.decompress(r.payload_gzip))) for r in rows]


async def _payload(session: AsyncSession, payload_id: int) -> JSONValue:
    blob = (await session.execute(
        text("SELECT payload_gzip FROM raw_payload WHERE id = :i"), {"i": payload_id}
    )).scalar_one()
    return json.loads(gzip.decompress(blob))  # type: ignore[no-any-return]


async def _day_range(
    session: AsyncSession, user_id: UUID, external_ids: set[str]
) -> tuple[date | None, date | None]:
    if not external_ids:
        return None, None
    row = (await session.execute(
        text("SELECT min((start_at AT TIME ZONE 'UTC')::date), "
             "max((coalesce(end_at, start_at) AT TIME ZONE 'UTC')::date) "
             "FROM activity WHERE user_id = :u AND external_id = ANY(:ids)"),
        {"u": str(user_id), "ids": sorted(external_ids)},
    )).one()
    return row[0], row[1]
```

Hinweis zum Speicher: `_payloads` für `activity_fit` lädt alle Payloads einer Abfrage auf einmal. Damit der erste Durchlauf nicht alle 748 FIT-Payloads (≈ 150 MB JSON) gleichzeitig hält, für `activity_fit` stattdessen nur `id` und `fetched_at` abfragen und jeden Payload einzeln über `_payload()` laden:

```python
    fit_rows = (await session.execute(
        text("SELECT id FROM raw_payload WHERE user_id = :u AND kind = 'activity_fit' "
             "AND (CAST(:f AS date) IS NULL OR window_start::date >= CAST(:f AS date)) "
             "AND (CAST(:t AS date) IS NULL OR window_start::date <= CAST(:t AS date)) "
             "ORDER BY fetched_at, id"),
        {"u": str(user_id),
         "f": from_date - timedelta(days=1) if from_date else None,
         "t": to_date + timedelta(days=1) if to_date else None},
    )).scalars().all()
    for payload_id in fit_rows:
        for act in _fit_activities(await _payload(session, int(payload_id))):
            if _wanted(act.get("activity_id"), activity_ids):
                newest[str(act["activity_id"])] = int(payload_id)
```

(diesen Block statt der Schleife über `_payloads(…, "activity_fit", …)` verwenden).

- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest tests/test_activity_reprocess_integration.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/kairos/ingestion/reprocess.py tests/test_activity_reprocess_integration.py
git commit -m "feat(ingestion): reprocess activities from archived Garmin payloads"
```

---

### Task 8: `POST /api/activities/reprocess`

**Files:**
- Create: `src/kairos/routers/activities.py`
- Modify: `src/kairos/api.py`, `src/kairos/routers/sync.py` (Konstante `_GARMIN_BACKFILL_COOLDOWN_SECONDS` exportierbar lassen; nur importieren)
- Test: `tests/test_activities_router.py`

**Interfaces:**
- Consumes: `reprocess_activities` (Task 7), `SyncJobRegistry`, `current_user`, `_GARMIN_BACKFILL_COOLDOWN_SECONDS`.
- Produces: `POST /api/activities/reprocess` Body `{"from_date"?: date, "to_date"?: date, "activity_ids"?: [str], "refetch_fit"?: bool}` → 202 `{"job_id": str}`; 409 wenn `activity_list` oder `activity_fit` gerade laufen; 429 im Cooldown; 400 bei `refetch_fit=true` (in AP 1 nicht unterstützt, siehe unten). Der Job erscheint in `GET /api/sync/status` mit `kind="reprocess"`.

`refetch_fit` (Spec A.4 Punkt 4, erneutes Laden von FIT-Dateien für Schwimmbahnen) bleibt in AP 1 abgelehnt: Es braucht einen Garmin-Request und ist erst für `activity_split` der Schwimmeinheiten (AP 2) nötig. Der Parameter existiert, damit sich die API nicht mehr ändert.

- [ ] **Step 1: Failing test** (Muster aus `tests/test_sync_router.py` übernehmen: dort steht, wie `current_user` und `get_registry` per `app.dependency_overrides` ersetzt werden):

```python
# tests/test_activities_router.py
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.ingestion.job_registry import SyncJobRegistry, get_registry

_USER = uuid4()


@pytest.fixture
def registry() -> Iterator[SyncJobRegistry]:
    reg = SyncJobRegistry()
    app.dependency_overrides[current_user] = lambda: {"user_id": str(_USER)}
    app.dependency_overrides[get_registry] = lambda: reg
    yield reg
    app.dependency_overrides.clear()


def test_refetch_fit_is_rejected_in_ap1(registry: SyncJobRegistry) -> None:
    r = TestClient(app).post("/api/activities/reprocess", json={"refetch_fit": True})
    assert r.status_code == 400


def test_conflicts_with_running_activity_sync(registry: SyncJobRegistry) -> None:
    asyncio.run(registry.get_lock(_USER, "garmin", "activity_fit").acquire())
    r = TestClient(app).post("/api/activities/reprocess", json={})
    assert r.status_code == 409


def test_cooldown_is_shared_with_backfill(registry: SyncJobRegistry) -> None:
    registry.record_trigger(_USER, "garmin")
    r = TestClient(app).post("/api/activities/reprocess", json={})
    assert r.status_code == 429
```

- [ ] **Step 2: Run** — FAIL (404)

- [ ] **Step 3: Router**

```python
# src/kairos/routers/activities.py
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.job_registry import SyncJob, SyncJobRegistry, get_registry
from kairos.ingestion.reprocess import reprocess_activities
from kairos.routers.sync import _GARMIN_BACKFILL_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/activities", tags=["activities"])

# reprocess rewrites activity/activity_record, so it must not overlap a running fetch
_LOCKED_KINDS = ("activity_list", "activity_fit")


class ReprocessRequest(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    activity_ids: list[str] | None = None
    refetch_fit: bool = False


@router.post("/reprocess", status_code=202)
async def trigger_reprocess(
    req: ReprocessRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
    if req.refetch_fit:
        raise HTTPException(status_code=400, detail="refetch_fit is not supported yet")
    user_id = UUID(user["user_id"])
    if any(registry.is_locked(user_id, "garmin", k) for k in _LOCKED_KINDS):
        raise HTTPException(status_code=409, detail="A Garmin activity sync is running")
    remaining = registry.seconds_until_trigger_allowed(
        user_id, "garmin", _GARMIN_BACKFILL_COOLDOWN_SECONDS
    )
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Bitte {int(remaining) + 1}s warten, bevor erneut synchronisiert wird",
            headers={"Retry-After": str(int(remaining) + 1)},
        )
    registry.record_trigger(user_id, "garmin")
    [job] = registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=["reprocess"],
        from_date=(req.from_date or date.min).isoformat(),
        to_date=(req.to_date or date.today()).isoformat(),
    )
    background_tasks.add_task(_run, user_id=user_id, req=req, job=job, registry=registry)
    return {"job_id": job.job_id}


async def _run(
    *, user_id: UUID, req: ReprocessRequest, job: SyncJob, registry: SyncJobRegistry
) -> None:
    list_lock = registry.get_lock(user_id, "garmin", "activity_list")
    fit_lock = registry.get_lock(user_id, "garmin", "activity_fit")
    async with list_lock, fit_lock:
        job.status = "running"
        try:
            async with async_session_factory() as session:
                install_rls_listener(session, user_id)
                result = await reprocess_activities(
                    session, user_id=user_id, from_date=req.from_date, to_date=req.to_date,
                    activity_ids=set(req.activity_ids) if req.activity_ids else None,
                )
                await session.commit()
            job.status = "done"
            job.windows_processed = result.activities
        except Exception as exc:
            logger.exception("Reprocess failed for user %s", user_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(UTC).isoformat()
```

In `api.py`: `from kairos.routers.activities import router as activities_router` und `app.include_router(activities_router)`.

- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest tests/test_activities_router.py tests/test_sync_router.py -v` → PASS

- [ ] **Step 5: Lint und Typen über alles** — `.venv/Scripts/python -m ruff check src tests` (nur die vorbestehenden B008-Befunde dürfen bleiben) und `.venv/Scripts/python -m mypy src` → keine neuen Fehler.

- [ ] **Step 6: Commit**

```bash
git add src/kairos/routers/activities.py src/kairos/api.py tests/test_activities_router.py
git commit -m "feat(api): POST /api/activities/reprocess as a locked background job"
```

---

### Task 9: Bestandsdaten neu verarbeiten und Abnahme

**Files:**
- Modify: `docs/HANDOVER.md`, `CLAUDE.md` (Testzahl), `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` (§13 AP 1 als erledigt markieren)

- [ ] **Step 1: Volle Suite** — `.venv/Scripts/python -m pytest -q` → alle grün, 0 skipped. Zahl in `CLAUDE.md` anpassen.

- [ ] **Step 2: Migration auf die Entwicklungs-DB** — `.venv/Scripts/python -m alembic upgrade head`; Backend neu starten.

- [ ] **Step 3: Reprocess über die UI-Session auslösen** (eingeloggt, im Browser-DevTools oder per Skript mit dem Session-Cookie):

```bash
curl -s -X POST http://127.0.0.1:8000/api/activities/reprocess -H "Content-Type: application/json" -b "session_id=<cookie>" -d '{}'
```

Danach `GET /api/sync/status` bis der Job `reprocess` auf `done` steht. Es darf dabei **kein** Garmin-Request entstehen (Backend-Log prüfen: kein `garminconnect`-Login).

- [ ] **Step 4: Abnahme-Prüfungen** (read-only SQL gegen die Entwicklungs-DB):

```sql
SELECT count(*) FROM activity;                                    -- 136
SELECT sport, sport_profile, count(*) FROM activity GROUP BY 1, 2 ORDER BY 3 DESC;
-- running/treadmill_running → running, hiking → hiking, lap_swimming → swimming,
-- cycling → cycling, strength_training/hiit/breathwork/resort_skiing → generic
SELECT count(*) FROM activity WHERE start_local IS NULL OR garmin_type_id IS NULL;  -- 0
SELECT count(DISTINCT activity_id) FROM activity_record WHERE metric = 'distance_m'; -- 136 bzw. alle mit GPS/Fußpod
SELECT count(*) FROM activity WHERE deleted_at IS NOT NULL;      -- 0 erwartet
```

Kadenz-Stichprobe: Für drei Läufe den Mittelwert von `2 * value` aus `activity_record` (metric `cadence`, nur Werte > 0) mit `averageRunningCadenceInStepsPerMinute` aus dem `activity_list`-Payload vergleichen — Abweichung ≤ 1 spm.

- [ ] **Step 5: Doku** — in `docs/HANDOVER.md` einen Abschnitt „AP 1 Datengrundlage (2026-10-13)“ mit Ergebnis der Abnahme-Prüfungen und den bewusst offenen Punkten (`refetch_fit`, automatischer Reprocess erst mit AP 2); in der Spec §13 AP 1 als erledigt markieren.

- [ ] **Step 6: Commit und Push**

```bash
git add docs/HANDOVER.md CLAUDE.md docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md
git commit -m "docs: AP 1 data foundation done, acceptance results"
git push origin main
```
