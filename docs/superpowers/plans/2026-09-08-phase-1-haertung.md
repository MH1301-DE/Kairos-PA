# Phase 1 Härtung — Garmin-Datenpipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Garmin-Datenpipeline (Speichern + geordnetes Abrufen) nachweislich Ende-zu-Ende funktionsfähig machen: eine echte Lese-API für Rohdaten ergänzen, den Backfill in der UI überhaupt auslösbar/beobachtbar machen (aktuell unmöglich — Root Cause verifiziert), Datenqualität absichern, Typsicherheit auf dem kritischen Pfad wiederherstellen und die Doku so korrigieren, dass sie nicht mehr über den Projektstand lügt.

**Architecture:** Bestehende Architektur (Connector-Protocol, SyncService, RLS-Repositories) bleibt unverändert — sie funktioniert nachweislich (144/144 Tests grün, Migrationen laufen). Diese Phase ergänzt eine neue Lese-Schicht (`src/kairos/repositories/data_read.py` + `src/kairos/routers/data.py`) nach demselben Repository/Router-Muster wie `metrics.py`, schließt die Frontend-Lücke im bestehenden `/sync`-Flow, und behebt konkrete, empirisch verifizierte Defekte.

**Tech Stack:** Python 3.13 (venv lokal; `pyproject.toml` erlaubt `>=3.12`), FastAPI, SQLAlchemy async, Alembic, pytest, SvelteKit, Playwright.

## Global Constraints

- Tests: `.venv/Scripts/python -m pytest -q` (Windows-venv, NICHT `uv run` — `uv` ist auf diesem System nicht installiert)
- Lint/Typen: `.venv/Scripts/python -m ruff check src tests` (35 vorbestehende `B008`-Findings sind bekannt/akzeptiert, NICHT anfassen) und `.venv/Scripts/python -m mypy src` (muss auf 0 Fehler landen — aktuell 14)
- `install_rls_listener(session, user_id)` MUSS auf jeder Session aufgerufen werden, die RLS-geschützte Tabellen liest oder schreibt (bestehende Regel, siehe CLAUDE.md)
- Kein neuer Task darf `Makefile`/`uv` voraussetzen — jeder Befehl in dieser Phase nutzt `.venv/Scripts/python -m ...` direkt
- Frontend-Tests: `web/` — `npm run check`, `npm run test:unit`, `npm run test:e2e` (PATH ggf. `export PATH="/c/Program Files/nodejs:$PATH"`)
- Commits: conventional commits (`feat(scope):`, `fix:`, `chore:`), ein Commit pro Step 5 je Task
- Kein Produktions-Deployment in dieser Phase (bewusst außerhalb des Scopes — Nutzerauftrag ist "Daten speichern + geordnet abrufen", nicht Produktivbetrieb)

---

## File Structure

- Create: `src/kairos/repositories/data_read.py` — Read-Repository für Rohdaten (Aktivitäten, Wellness-Zeitreihen, Schlaf)
- Create: `src/kairos/routers/data.py` — `/api/data/*` Read-Endpunkte
- Modify: `src/kairos/api.py` — neuen Router einhängen
- Modify: `src/kairos/db/models.py` — `quality` Spalte auf `WellnessSample`
- Create: `alembic/versions/<rev>_wellness_quality_flag.py`
- Modify: `src/kairos/connectors/garmin/normalize.py` — Plausibilitätsprüfung HR
- Modify: `src/kairos/repositories/canonical.py` — `quality` beim Schreiben durchreichen
- Modify: `src/kairos/routers/sync.py` — mypy-Fixes, `_build_garmin_client` loggt statt zu schlucken
- Modify: `src/kairos/routers/connections.py` — mypy-Fixes
- Modify: `src/kairos/routers/metrics.py` — mypy-Fixes
- Modify: `src/kairos/connectors/garmin/connector.py` — mypy-Fix (`_fetch_activity_fits`)
- Modify: `web/src/routes/sync/+page.svelte` — Backfill-Trigger-Button + Live-Polling
- Modify: `web/src/routes/sync/+page.server.ts` — Form-Action für Trigger
- Create: `web/tests/e2e/sync.spec.ts` — E2E: Trigger → Polling → sichtbarer Fortschritt
- Modify: `Makefile` — `uv run` → `.venv/Scripts/python -m` / `.venv/bin/python -m`
- Modify: `CLAUDE.md` — Testzahl korrigieren, `kairos-handover`-Skill-Referenz entfernen (existiert nicht)
- Create: `tests/test_data_read_repository.py`
- Create: `tests/test_data_router.py`
- Create: `tests/test_normalize_quality_flag.py`

---

### Task 1: mypy --strict auf 0 Fehler (4 Dateien)

**Files:**
- Modify: `src/kairos/routers/sync.py:57,59,96,98,225`
- Modify: `src/kairos/routers/connections.py:39,41,110,112`
- Modify: `src/kairos/routers/metrics.py:21,27,40,42`
- Modify: `src/kairos/connectors/garmin/connector.py:90` (genauer: die `result`-Variable in `_fetch_activity_fits`, Zeile 72)

**Interfaces:**
- Produces: keine neuen Signaturen — reine Typannotation, alle Funktionsverhalten bleiben identisch (verifiziert durch die bestehende Testsuite, die nach dem Fix weiterhin grün sein muss)

- [ ] **Step 1: Baseline bestätigen**

Run: `.venv/Scripts/python -m mypy src`
Erwartet: 14 Fehler in 4 Dateien (exakt die oben gelisteten Zeilen)

- [ ] **Step 2: `dict` → `dict[str, Any]` in den drei Routern**

In `src/kairos/routers/sync.py`, `src/kairos/routers/connections.py`, `src/kairos/routers/metrics.py`: jedes nackte `dict` als Rückgabetyp einer `async def`-Routen-Funktion wird zu `dict[str, Any]`. Beispiel für `sync.py:53-59`:

```python
@router.post("/garmin/backfill", status_code=202)
async def trigger_garmin_backfill(
    req: BackfillRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
```

`Any` ist in `sync.py`/`connections.py`/`metrics.py` bereits importiert bzw. muss (falls nicht) aus `typing` importiert werden — `from typing import Any` prüfen/ergänzen. Gleiches Muster auf `sync_status` (Zeile 94-98), `list_connections` (Zeile 108-112), `connect_garmin` (Zeile 39, 41), und alle drei Routen in `metrics.py` (Zeile 20-42, dort ist der Rückgabetyp `dict[str, Any]`, das Argument `user: dict = Depends(...)` wird zu `user: dict[str, Any] = Depends(...)`).

- [ ] **Step 3: `no-any-return` in `sync.py:225` beheben**

`_build_garmin_client` ist als `-> object | None` deklariert, aber `gc.Garmin()` (aus `importlib.import_module`) liefert `Any`. Fix: explizite Annotation der lokalen Variable.

```python
async def _build_garmin_client(session: AsyncSession, user_id: UUID) -> object | None:
    try:
        ...
        gc = importlib.import_module("garminconnect")
        garmin: object = gc.Garmin()
        await asyncio.to_thread(garmin.login, token_json)  # type: ignore[attr-defined]
        return garmin
    except Exception as exc:
        logger.warning("Garmin client build failed for user %s: %s", user_id, exc)
        return None
```

(Das `type: ignore[attr-defined]` ist nötig, weil `garmin` jetzt als `object` typisiert ist und `.login` nicht kennt — Alternative: `garmin = cast(Any, gc.Garmin())` mit `from typing import cast`, dann kein `type: ignore` nötig und `garmin.login(...)` bleibt ungewarnt. Nimm die `cast`-Variante, sie ist saubereres mypy-Idiom für dieses Projekt.)

Diese Änderung hängt mit Task 4 zusammen (dort wird derselbe `except Exception: return None`-Block durch echtes Logging ersetzt) — beide Änderungen an derselben Stelle in einem Schritt zusammenfassen, nicht zweimal anfassen. `import logging` + `logger = logging.getLogger(__name__)` am Dateikopf von `sync.py` ergänzen, falls nicht vorhanden.

- [ ] **Step 4: `dict-item` in `connector.py:90` beheben**

In `_fetch_activity_fits` (Zeile 64-90): `result: list[dict[str, Any]]` wird zu `result: list[JSONValue]` (import bereits vorhanden: `from kairos.connectors.types import ... JSONValue`). Die restlichen `result.append({...})`-Aufrufe bleiben unverändert (die dict-Literale sind bereits strukturell mit `JSONValue` kompatibel).

- [ ] **Step 5: mypy + volle Testsuite laufen lassen**

Run: `.venv/Scripts/python -m mypy src` → Erwartet: `Success: no issues found`
Run: `.venv/Scripts/python -m pytest -q` → Erwartet: weiterhin alle Tests grün (Baseline: 144 passed bei laufendem Docker)

- [ ] **Step 6: Commit**

```bash
git add src/kairos/routers/sync.py src/kairos/routers/connections.py src/kairos/routers/metrics.py src/kairos/connectors/garmin/connector.py
git commit -m "fix: resolve all 14 mypy --strict errors on the Garmin ingestion path"
```

---

### Task 2: Quality-Flag für Herzfrequenz-Plausibilität

**Files:**
- Modify: `src/kairos/db/models.py`
- Create: `alembic/versions/<rev>_wellness_quality_flag.py`
- Modify: `src/kairos/connectors/garmin/normalize.py`
- Modify: `src/kairos/repositories/canonical.py`
- Create: `tests/test_normalize_quality_flag.py`

**Interfaces:**
- Consumes: `CanonicalRecord.data` (dict, aus `types.py`, unverändert)
- Produces: `CanonicalRecord.data["quality"]` (neuer optionaler Key, `"ok"` oder `"suspect"`, nur für `record_type == "wellness_sample"` mit `metric == "hr"`) — Task 3 (Lese-API) liest diesen Wert über die neue `WellnessSample.quality`-Spalte zurück

- [ ] **Step 1: Failing test für die Plausibilitätsprüfung schreiben**

```python
# tests/test_normalize_quality_flag.py
from kairos.connectors.garmin.normalize import normalize_payload


def test_hr_within_range_is_ok():
    payload = {"heartRateValues": [["2026-08-01T10:00:00", 65]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"


def test_hr_below_25_is_suspect():
    payload = {"heartRateValues": [["2026-08-01T10:00:00", 20]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_above_230_is_suspect():
    payload = {"heartRateValues": [["2026-08-01T10:00:00", 240]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_exactly_at_boundaries_is_ok():
    payload = {"heartRateValues": [["2026-08-01T10:00:00", 25], ["2026-08-01T10:00:01", 230]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"
    assert records[1].data["quality"] == "ok"
```

Achtung: `_normalize_hr_intraday` erwartet aktuell `item.get("timestamp")`/`item.get("value")` als dict-Einträge (siehe `normalize.py:44-45`), nicht `["ts", val]`-Listen — die Testfixtures oben müssen exakt dem bestehenden `heartRateValues`-Dict-Format folgen:

```python
def test_hr_below_25_is_suspect():
    payload = {"heartRateValues": [{"timestamp": "2026-08-01T10:00:00", "value": 20}]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"
```

Schreibe alle vier Tests oben mit diesem korrekten dict-Format (nicht dem Listen-Format aus dem ersten Entwurf).

- [ ] **Step 2: Tests laufen lassen, verifizieren dass sie fehlschlagen**

Run: `.venv/Scripts/python -m pytest tests/test_normalize_quality_flag.py -v`
Erwartet: FAIL mit `KeyError: 'quality'`

- [ ] **Step 3: Plausibilitätsprüfung implementieren**

In `src/kairos/connectors/garmin/normalize.py`, `_normalize_hr_intraday` (Zeile 34-61): nach der bestehenden Validierung, vor `records.append(...)`, Quality bestimmen und in `data` aufnehmen:

```python
_HR_MIN_PLAUSIBLE = 25.0
_HR_MAX_PLAUSIBLE = 230.0

...

quality = "ok" if _HR_MIN_PLAUSIBLE <= float(value_raw) <= _HR_MAX_PLAUSIBLE else "suspect"
records.append(
    CanonicalRecord(
        record_type="wellness_sample",
        external_id=f"hr:{occurred_at.isoformat()}",
        occurred_at=occurred_at,
        data={"metric": "hr", "value": float(value_raw), "quality": quality},
    )
)
```

Nur für `hr` — die anderen Wellness-Normalizer (`stress`, `body_battery`, `hrv`, `respiration`, `spo2`) bekommen in diesem Task KEIN Quality-Flag (kein dokumentierter Plausibilitätsbereich dafür, YAGNI — spätere Erweiterung möglich).

- [ ] **Step 4: DB-Spalte + Migration**

In `src/kairos/db/models.py`, `WellnessSample` (Zeile 226-252): neue Spalte nach `value`:

```python
quality: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ok")
```

(`String` muss aus `sqlalchemy` importiert sein — in `models.py` prüfen, ob bereits importiert.)

Migration generieren (Kette folgt auf `339358b313ef`, siehe `docs/HANDOVER.md` Migrationskette — `alembic heads` prüft den aktuellen HEAD, falls abweichend von der Doku dort ansetzen):

```bash
.venv/Scripts/python -m alembic revision --autogenerate -m "wellness_quality_flag"
```

Migration von Hand prüfen: `quality` muss `nullable=False, server_default='ok'` sein, damit bestehende Zeilen beim Upgrade nicht brechen.

- [ ] **Step 5: `canonical.py` reicht `quality` durch**

In `src/kairos/repositories/canonical.py`, `_write_wellness` (Zeile 54-76): `quality` aus `record.data` lesen und mitschreiben.

```python
stmt = (
    insert(WellnessSample)
    .values(
        user_id=user_id,
        metric_id=metric_id,
        observed_at=record.occurred_at,
        value=float(record.data.get("value", 0)),  # type: ignore[arg-type]
        quality=record.data.get("quality", "ok"),
        raw_payload_id=raw_payload_id,
    )
    .on_conflict_do_nothing(constraint="uq_wellness_sample")
)
```

`.get("quality", "ok")` deckt alle Nicht-HR-Metriken ab, die (noch) kein Quality-Flag setzen.

- [ ] **Step 6: Migration anwenden, Tests laufen lassen**

Run: `.venv/Scripts/python -m alembic upgrade head`
Run: `.venv/Scripts/python -m pytest tests/test_normalize_quality_flag.py tests/test_garmin_normalize.py tests/test_garmin_repositories_integration.py -v`
Erwartet: alle PASS (Docker muss laufen für die Integration-Tests)

- [ ] **Step 7: Commit**

```bash
git add src/kairos/db/models.py src/kairos/connectors/garmin/normalize.py src/kairos/repositories/canonical.py alembic/versions/ tests/test_normalize_quality_flag.py
git commit -m "feat(garmin): flag implausible heart-rate readings as suspect"
```

---

### Task 3: Lese-API für Rohdaten (Aktivitäten, Wellness-Zeitreihen, Schlaf)

**Files:**
- Create: `src/kairos/repositories/data_read.py`
- Create: `src/kairos/routers/data.py`
- Modify: `src/kairos/api.py`
- Create: `tests/test_data_read_repository.py`
- Create: `tests/test_data_router.py`

**Interfaces:**
- Consumes: `WellnessSample`, `Activity`, `ActivityRecord`, `SleepSession`, `MetricDef` (aus `src/kairos/db/models.py`, unverändert), `WellnessSample.quality` (aus Task 2)
- Produces: `SqlDataReadRepository` mit `list_activities`, `get_activity_detail`, `list_wellness_series`, `list_sleep_sessions` — Signaturen unten exakt, spätere Frontend-Arbeit (Visualisierung) ruft ausschließlich die HTTP-Endpunkte auf, nicht das Repository direkt

**Warum ein eigener Read-Layer statt Erweiterung von `metrics.py`:** `metrics.py` liefert ausschließlich abgeleitete Kennzahlen (CTL/ATL/TSB, Baselines) über die `MetricRegistry` — bewusst kein Rohdatenzugriff (siehe `docs/03-agent-design.md`: der Agent bekommt nie Rohdaten). Diese Trennung bleibt bestehen; `/api/data/*` ist ein neuer, getrennter Zugriffspfad ausschließlich für Dashboard/Visualisierung (menschlicher Nutzer im Browser), nicht für den Agenten.

- [ ] **Step 1: Failing Repository-Tests schreiben**

```python
# tests/test_data_read_repository.py
import uuid
from datetime import UTC, datetime

import pytest

from kairos.repositories.data_read import SqlDataReadRepository


@pytest.mark.asyncio
async def test_list_wellness_series_filters_by_date_range(db_session, seeded_hr_samples):
    user_id, metric_id = seeded_hr_samples
    repo = SqlDataReadRepository(session=db_session)
    result = await repo.list_wellness_series(
        user_id=user_id,
        metric="hr",
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert all(datetime(2026, 8, 1, tzinfo=UTC) <= s.observed_at <= datetime(2026, 8, 2, tzinfo=UTC) for s in result)


@pytest.mark.asyncio
async def test_list_activities_paginates_with_cursor(db_session, seeded_activities):
    user_id = seeded_activities
    repo = SqlDataReadRepository(session=db_session)
    page1 = await repo.list_activities(user_id=user_id, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    page2 = await repo.list_activities(user_id=user_id, limit=2, cursor=page1.next_cursor)
    assert {a.external_id for a in page1.items}.isdisjoint({a.external_id for a in page2.items})


@pytest.mark.asyncio
async def test_get_activity_detail_includes_records(db_session, seeded_activity_with_records):
    user_id, external_id = seeded_activity_with_records
    repo = SqlDataReadRepository(session=db_session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id=external_id)
    assert detail is not None
    assert len(detail.records) > 0
```

Die Fixtures `seeded_hr_samples`/`seeded_activities`/`seeded_activity_with_records` existieren noch nicht — als lokale `pytest.fixture`-Funktionen in derselben Testdatei anlegen (Muster: `tests/test_garmin_repositories_integration.py` ansehen, wie dort `db_session`-Fixture + Test-User-Seeding bereits funktioniert, exakt übernehmen statt neu erfinden).

- [ ] **Step 2: Tests laufen lassen, verifizieren dass sie fehlschlagen**

Run: `.venv/Scripts/python -m pytest tests/test_data_read_repository.py -v`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'kairos.repositories.data_read'`

- [ ] **Step 3: `SqlDataReadRepository` implementieren**

```python
# src/kairos/repositories/data_read.py
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import Activity, ActivityRecord, MetricDef, SleepSession, WellnessSample


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class ActivityDetail:
    activity: Activity
    records: list[ActivityRecord]


class SqlDataReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_wellness_series(
        self, *, user_id: UUID, metric: str, from_date: datetime, to_date: datetime
    ) -> list[WellnessSample]:
        metric_id_row = await self._session.execute(
            select(MetricDef.id).where(MetricDef.code == metric)
        )
        metric_id = metric_id_row.scalar_one_or_none()
        if metric_id is None:
            return []
        result = await self._session.execute(
            select(WellnessSample)
            .where(
                WellnessSample.user_id == user_id,
                WellnessSample.metric_id == metric_id,
                WellnessSample.observed_at >= from_date,
                WellnessSample.observed_at <= to_date,
            )
            .order_by(WellnessSample.observed_at)
        )
        return list(result.scalars().all())

    async def list_activities(
        self, *, user_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> Page[Activity]:
        stmt = select(Activity).where(Activity.user_id == user_id)
        if cursor is not None:
            cursor_start_at = _decode_cursor(cursor)
            stmt = stmt.where(Activity.start_at < cursor_start_at)
        stmt = stmt.order_by(Activity.start_at.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = _encode_cursor(items[-1].start_at) if has_more and items[-1].start_at else None
        return Page(items=items, next_cursor=next_cursor)

    async def get_activity_detail(self, *, user_id: UUID, external_id: str) -> ActivityDetail | None:
        activity_row = await self._session.execute(
            select(Activity).where(Activity.user_id == user_id, Activity.external_id == external_id)
        )
        activity = activity_row.scalar_one_or_none()
        if activity is None:
            return None
        records_row = await self._session.execute(
            select(ActivityRecord)
            .where(ActivityRecord.user_id == user_id, ActivityRecord.activity_id == activity.id)
            .order_by(ActivityRecord.recorded_at)
        )
        return ActivityDetail(activity=activity, records=list(records_row.scalars().all()))

    async def list_sleep_sessions(
        self, *, user_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[SleepSession]:
        result = await self._session.execute(
            select(SleepSession)
            .where(
                SleepSession.user_id == user_id,
                SleepSession.start_at >= from_date,
                SleepSession.start_at <= to_date,
            )
            .order_by(SleepSession.start_at)
        )
        return list(result.scalars().all())


def _encode_cursor(dt: datetime) -> str:
    return base64.urlsafe_b64encode(dt.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    return datetime.fromisoformat(base64.urlsafe_b64decode(cursor.encode()).decode())
```

Prüfe vor dem Schreiben, ob `Activity`/`ActivityRecord`/`SleepSession` exakt die hier verwendeten Spaltennamen (`start_at`, `activity_id`, `recorded_at`, `user_id`, `external_id`) haben — mit `src/kairos/db/models.py` abgleichen, nicht raten. Python-3.12-Generics-Syntax (`class Page[T]`) ist projektkompatibel (`pyproject.toml` verlangt `>=3.12`).

- [ ] **Step 4: Repository-Tests grün bekommen**

Run: `.venv/Scripts/python -m pytest tests/test_data_read_repository.py -v`
Erwartet: PASS

- [ ] **Step 5: Failing Router-Test schreiben**

```python
# tests/test_data_router.py
import pytest
from httpx import ASGITransport, AsyncClient

from kairos.api import app


@pytest.mark.asyncio
async def test_wellness_series_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/wellness/hr")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wellness_series_returns_ordered_points(authed_client, seeded_hr_samples):
    resp = await authed_client.get(
        "/api/data/wellness/hr", params={"from_date": "2026-08-01", "to_date": "2026-08-02"}
    )
    assert resp.status_code == 200
    body = resp.json()
    values = [p["observed_at"] for p in body["points"]]
    assert values == sorted(values)


@pytest.mark.asyncio
async def test_activities_list_paginates(authed_client, seeded_activities):
    resp = await authed_client.get("/api/data/activities", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert "next_cursor" in body
```

`authed_client`-Fixture existiert vermutlich schon für andere Router-Tests (z.B. `tests/test_metrics_*.py` prüfen, wie dort `current_user`-Dependency in Tests überschrieben wird — `app.dependency_overrides[current_user] = ...`-Muster übernehmen, nicht neu erfinden).

- [ ] **Step 6: Router implementieren**

```python
# src/kairos/routers/data.py
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.data_read import SqlDataReadRepository

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/wellness/{metric}")
async def wellness_series(
    metric: str,
    from_date: date | None = None,
    to_date: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    points = await repo.list_wellness_series(
        user_id=user_id,
        metric=metric,
        from_date=_to_utc_midnight(from_date or date.today().replace(day=1)),
        to_date=_to_utc_midnight(to_date or date.today()),
    )
    return {
        "metric": metric,
        "points": [
            {"observed_at": p.observed_at.isoformat(), "value": p.value, "quality": p.quality}
            for p in points
        ],
    }


@router.get("/activities")
async def list_activities(
    limit: int = 50,
    cursor: str | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    page = await repo.list_activities(user_id=user_id, limit=limit, cursor=cursor)
    return {
        "items": [
            {
                "external_id": a.external_id,
                "name": a.name,
                "sport": a.sport,
                "start_at": a.start_at.isoformat() if a.start_at else None,
                "distance_m": a.distance_m,
                "duration_s": a.duration_s,
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
            }
            for a in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.get("/activities/{external_id}")
async def activity_detail(
    external_id: str,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id=external_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="activity not found")
    return {
        "external_id": detail.activity.external_id,
        "name": detail.activity.name,
        "sport": detail.activity.sport,
        "start_at": detail.activity.start_at.isoformat() if detail.activity.start_at else None,
        "records": [
            {"recorded_at": r.recorded_at.isoformat(), "metric": r.metric, "value": r.value}
            for r in detail.records
        ],
    }


@router.get("/sleep")
async def sleep_sessions(
    from_date: date | None = None,
    to_date: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    sessions = await repo.list_sleep_sessions(
        user_id=user_id,
        from_date=_to_utc_midnight(from_date or date.today().replace(day=1)),
        to_date=_to_utc_midnight(to_date or date.today()),
    )
    return {
        "sessions": [
            {
                "start_at": s.start_at.isoformat(),
                "end_at": s.end_at.isoformat() if s.end_at else None,
                "duration_seconds": s.duration_seconds,
            }
            for s in sessions
        ]
    }


def _to_utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
```

`GET /api/data/wellness/{metric}` ohne Auth muss 401 liefern — das ist bereits durch `Depends(current_user)` abgedeckt (identisches Muster wie jede andere geschützte Route in diesem Projekt, siehe `sync.py`/`connections.py`), kein Zusatzcode nötig.

- [ ] **Step 7: Router in `api.py` einhängen**

In `src/kairos/api.py`: `from kairos.routers import data` (bzw. exaktes Import-Muster der bestehenden Router dort kopieren) + `app.include_router(data.router)`.

- [ ] **Step 8: Alle neuen Tests + volle Suite grün**

Run: `.venv/Scripts/python -m pytest tests/test_data_read_repository.py tests/test_data_router.py -v` → PASS
Run: `.venv/Scripts/python -m pytest -q` → weiterhin alle grün
Run: `.venv/Scripts/python -m mypy src` → weiterhin 0 Fehler

- [ ] **Step 9: Commit**

```bash
git add src/kairos/repositories/data_read.py src/kairos/routers/data.py src/kairos/api.py tests/test_data_read_repository.py tests/test_data_router.py
git commit -m "feat(data): add read API for activities, wellness series, and sleep sessions"
```

---

### Task 4: Backfill in der UI auslösbar + beobachtbar machen (Root-Cause-Fix)

**Files:**
- Modify: `web/src/routes/sync/+page.svelte`
- Modify: `web/src/routes/sync/+page.server.ts`
- Create: `web/tests/e2e/sync.spec.ts`

**Interfaces:**
- Consumes: `POST /api/sync/garmin/backfill` (Response: `{"jobs": [SyncJob, ...]}`), `GET /api/sync/status` (Response: `{"jobs": [SyncJob, ...]}`) — beide bereits vollständig implementiert und getestet in `src/kairos/routers/sync.py`, unverändert in diesem Task
- Produces: nichts, das andere Tasks konsumieren — dies ist die letzte Frontend-Nahtstelle der Phase

**Root Cause (verifiziert):** `web/src/routes/onboarding/+page.server.ts` ruft ausschließlich `POST /api/connections/garmin` auf. Kein Code-Pfad im gesamten `web/src`-Baum ruft `/api/sync/garmin/backfill` auf (`grep -rn "backfill" web/src` → 0 Treffer). `sync/+page.svelte` ist reines SSR ohne Trigger-Button und ohne Polling (`grep -rln "setInterval|poll" web/src` → 0 Treffer). Ein Nutzer kann nach dem Onboarding buchstäblich keine Daten abrufen, ohne selbst `curl` zu benutzen.

- [ ] **Step 1: Failing E2E-Test schreiben**

```typescript
// web/tests/e2e/sync.spec.ts
import { test, expect } from '@playwright/test';
import http from 'node:http';

const STUB_PORT = 8791;

function startSyncStub(): Promise<http.Server> {
	let backfillTriggered = false;
	let pollCount = 0;
	const server = http.createServer((req, res) => {
		if (req.method === 'GET' && req.url === '/api/connections') {
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(
				JSON.stringify({
					connections: [{ connector: 'garmin', status: 'active', external_account: 'user@example.com' }]
				})
			);
			return;
		}
		if (req.method === 'GET' && req.url === '/api/sync/status') {
			pollCount += 1;
			const status = !backfillTriggered ? [] : pollCount < 3 ? 'running' : 'done';
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(
				JSON.stringify({
					jobs: !backfillTriggered
						? []
						: [
								{
									job_id: 'job-1',
									connector: 'garmin',
									kind: 'hr_intraday',
									from_date: '2025-06-01',
									to_date: '2026-09-08',
									status,
									windows_processed: pollCount,
									error: null,
									started_at: '2026-09-08T10:00:00Z',
									finished_at: status === 'done' ? '2026-09-08T10:05:00Z' : null
								}
							]
				})
			);
			return;
		}
		if (req.method === 'POST' && req.url === '/api/sync/garmin/backfill') {
			backfillTriggered = true;
			req.resume();
			req.on('end', () => {
				res.writeHead(202, { 'Content-Type': 'application/json' });
				res.end(
					JSON.stringify({
						jobs: [
							{
								job_id: 'job-1',
								connector: 'garmin',
								kind: 'hr_intraday',
								from_date: '2025-06-01',
								to_date: '2026-09-08',
								status: 'queued',
								windows_processed: 0,
								error: null,
								started_at: '2026-09-08T10:00:00Z',
								finished_at: null
							}
						]
					})
				);
			});
			return;
		}
		res.writeHead(404).end();
	});
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(STUB_PORT, () => resolve(server));
	});
}

test.describe('sync page', () => {
	let stub: http.Server | undefined;

	test.beforeEach(async ({ context }) => {
		await context.addCookies([
			{ name: 'session_id', value: 'e2e-fake-session', domain: 'localhost', path: '/' }
		]);
		stub = await startSyncStub();
	});

	test.afterEach(async () => {
		if (stub) await new Promise<void>((resolve) => stub!.close(() => resolve()));
		stub = undefined;
	});

	test('trigger button starts a backfill and polling shows progress to done', async ({ page }) => {
		await page.goto('/sync', { waitUntil: 'networkidle' });
		await page.locator('button', { hasText: 'Backfill starten' }).click();
		await expect(page.getByText('running')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('done')).toBeVisible({ timeout: 10000 });
	});
});
```

Playwright-Config (`playwright.config.ts`) leitet `/api` bereits auf `KAIROS_API_PROXY_TARGET`/Port 8791 um (siehe `web/tests/e2e/onboarding.spec.ts` Kommentar Zeile 3-13) — dasselbe Setup, kein Config-Änderung nötig.

- [ ] **Step 2: Test laufen lassen, verifizieren dass er fehlschlägt**

Run: `cd web && npm run test:e2e -- sync.spec.ts`
Erwartet: FAIL — kein Button mit Text "Backfill starten" vorhanden

- [ ] **Step 3: Form-Action für den Trigger ergänzen**

```typescript
// web/src/routes/sync/+page.server.ts
import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, apiPost, ApiError } from '$lib/api';
import type { ConnectionInfo, SyncJob } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	try {
		const [connections, syncStatus] = await Promise.all([
			apiGet<{ connections: ConnectionInfo[] }>(fetch, '/api/connections'),
			apiGet<{ jobs: SyncJob[] }>(fetch, '/api/sync/status')
		]);
		return { connections: connections.connections, jobs: syncStatus.jobs };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	triggerBackfill: async ({ fetch }) => {
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/sync/garmin/backfill',
			{}
		);
		if (status !== 202) {
			return { triggerError: `Backfill konnte nicht gestartet werden (${status}): ${data.detail ?? 'unbekannt'}` };
		}
		return { triggered: true };
	}
};
```

- [ ] **Step 4: Trigger-Button + Live-Polling im Svelte-Component**

```svelte
<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { invalidate } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));

	// polls while any job is queued/running; stops once every job is done/failed/skipped
	const ACTIVE_STATUSES = new Set(['queued', 'running']);
	let pollHandle: ReturnType<typeof setInterval> | undefined;

	$effect(() => {
		const hasActiveJob = data.jobs.some((j) => ACTIVE_STATUSES.has(j.status));
		if (hasActiveJob && !pollHandle) {
			pollHandle = setInterval(() => invalidate('sync:status'), 2000);
		} else if (!hasActiveJob && pollHandle) {
			clearInterval(pollHandle);
			pollHandle = undefined;
		}
	});

	onDestroy(() => {
		if (pollHandle) clearInterval(pollHandle);
	});
</script>

<h1>Sync-Status</h1>

{#if !garminConnection}
	<div class="tile">
		<p>Keine Garmin-Verbindung.</p>
		<a href={resolve('/onboarding')} class="btn btn-primary">Jetzt einrichten</a>
	</div>
{:else}
	<p class="connection-line">
		Garmin: <span class="figure">{garminConnection.status}</span>
		({garminConnection.external_account})
	</p>

	<form method="POST" action="?/triggerBackfill" use:enhance class="tile trigger-panel">
		<button type="submit" class="btn btn-primary">Backfill starten</button>
		{#if form?.triggerError}
			<p class="status-error">{form.triggerError}</p>
		{/if}
	</form>

	<div class="tile">
		<table>
			<thead>
				<tr>
					<th>Kind</th>
					<th>Status</th>
					<th>Verarbeitete Fenster</th>
					<th>Fehler</th>
				</tr>
			</thead>
			<tbody>
				{#each data.jobs as job (job.job_id)}
					<tr>
						<td>{job.kind}</td>
						<td>{job.status}</td>
						<td>{job.windows_processed}</td>
						<td>{job.error ?? '–'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.connection-line {
		color: var(--color-text-muted);
	}
	.trigger-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		align-items: flex-start;
	}
</style>
```

`invalidate('sync:status')` braucht ein passendes `depends('sync:status')` im `load`-Function von `+page.server.ts`, sonst läuft `load` bei `invalidate()` nicht erneut. In `+page.server.ts`s `load`-Signatur `depends` mit aufnehmen: `export const load: PageServerLoad = async ({ fetch, depends }) => { depends('sync:status'); ... }`.

- [ ] **Step 5: `_build_garmin_client` loggt echte Fehler statt sie zu schlucken**

Dieser Fix gehört inhaltlich zu Task 1 Step 3 (bereits dort umgesetzt) — hier nur verifizieren, dass die Kombination aus Trigger-Button (dieser Task) und echtem Logging (Task 1) zusammen dazu führt, dass ein fehlgeschlagener Backfill (z.B. `reauth_required`-Connection) sowohl im Server-Log sichtbar ist als auch als `job.error`-Text im Frontend erscheint (bereits über die bestehende `job.error`-Spalte in der Tabelle abgedeckt, kein weiterer Code nötig).

- [ ] **Step 6: E2E-Test grün bekommen**

Run: `cd web && npm run test:e2e -- sync.spec.ts`
Erwartet: PASS

- [ ] **Step 7: Restliche Frontend-Suite + Typecheck**

Run: `cd web && npm run check` → 0 Fehler
Run: `cd web && npm run test:unit` → weiterhin alle grün
Run: `cd web && npm run test:e2e` → komplette E2E-Suite grün (inkl. bestehendem `onboarding.spec.ts`)

- [ ] **Step 8: Commit**

```bash
git add web/src/routes/sync/+page.svelte web/src/routes/sync/+page.server.ts web/tests/e2e/sync.spec.ts
git commit -m "fix(web): add backfill trigger button and live status polling to /sync"
```

---

### Task 5: Makefile reparieren (uv-Abhängigkeit entfernen)

**Files:**
- Modify: `Makefile`

**Interfaces:** keine — reine Tooling-Korrektur, kein Produktionscode betroffen

- [ ] **Step 1: Aktuellen Makefile-Inhalt lesen**

`cat Makefile` — jedes Target, das `uv run` nutzt, notieren (laut As-Is-Analyse: migrate/test/lint/dev, ggf. weitere).

- [ ] **Step 2: `uv run <cmd>` → `.venv/Scripts/python -m <cmd>` (bzw. Unix-Pfad für Cross-Platform)**

Muster pro Target, z.B.:

```makefile
test:
	.venv/bin/python -m pytest -q || .venv/Scripts/python -m pytest -q

lint:
	.venv/bin/python -m ruff check src tests || .venv/Scripts/python -m ruff check src tests

migrate:
	.venv/bin/python -m alembic upgrade head || .venv/Scripts/python -m alembic upgrade head

dev:
	.venv/bin/uvicorn kairos.api:app --reload || .venv/Scripts/uvicorn kairos.api:app --reload
```

Das `||`-Fallback-Muster deckt macOS/Linux (`.venv/bin/`) und Windows (`.venv/Scripts/`) in einem Target ab, ohne Plattformerkennung im Makefile selbst — pragmatisch, kein Over-Engineering für ein 5-Nutzer-Projekt. Alle Original-Targets (Namen, Reihenfolge) unverändert lassen, nur den Interpreter-Aufruf ersetzen.

- [ ] **Step 3: Jedes Target manuell durchlaufen**

Run: `make test`, `make lint`, `make migrate` (Docker muss laufen)
Erwartet: alle drei laufen durch ohne `command not found: uv`

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "fix: Makefile targets use .venv python directly, uv is not installed here"
```

---

### Task 6: Doku korrigieren (CLAUDE.md)

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** keine

- [ ] **Step 1: Testzahl korrigieren**

`CLAUDE.md` Zeile 33: `→ must be 109 passed, 0 skipped` → `→ must be 144 passed, 0 skipped` (Stand nach Phase 3, verifiziert in der As-Is-Analyse — falls diese Phase neue Tests addiert, die finale Zahl in Task 7 nochmal nachziehen).

- [ ] **Step 2: `kairos-handover`-Skill-Referenz entfernen**

`CLAUDE.md` Abschnitt "Session Start Protocol", Punkt 3 (Zeile 26-27) verlangt `Invoke kairos-handover` — dieser Skill existiert nirgends im Repo (verifiziert: kein `.claude/skills/`-Verzeichnis, keine Definition). Ersatzlos streichen, da Punkt 1 (`docs/HANDOVER.md` lesen) und Punkt 2 (Commit-Autorenschaft prüfen) den kompletten inhaltlichen Zweck bereits abdecken — ein Skill nur zu bauen, damit die Doku-Zeile stimmt, wäre Doku-getriebene Scope-Erweiterung ohne echten Mehrwert (YAGNI):

```markdown
### 1. Read the handover document
```
Read: docs/HANDOVER.md
```

### 2. Check for agent commits
```bash
git log --format="%h|%an|%ae|%s" -20
```

**Human developers** (skip diff review for these):
- `Maximilian Haenel` — mhaenel@deloitte.de
- `Maximilian Haenel` — max.haenel@t-online.de

For every commit by a **different author**, read its diff:
```bash
git show <hash>
```
```

(Punkt 3 komplett entfernen, Nummerierung bleibt bei zwei Punkten — keine Lücke lassen.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: fix stale test count and remove dead kairos-handover skill reference"
```

---

### Task 7: Phase-Abnahme

**Files:** keine Code-Änderungen — reine Verifikation

- [ ] **Step 1: Volle Backend-Suite**

Run: `.venv/Scripts/python -m pytest -q`
Erwartet: alle Tests grün (Docker läuft), 0 skipped, Zahl in `CLAUDE.md` (Task 6) muss exakt damit übereinstimmen — bei Abweichung Task 6 nachziehen

- [ ] **Step 2: mypy + ruff**

Run: `.venv/Scripts/python -m mypy src` → `Success: no issues found`
Run: `.venv/Scripts/python -m ruff check src tests` → nur die bekannten 35 `B008`-Findings, keine neuen

- [ ] **Step 3: Frontend-Suite**

Run: `cd web && npm run check && npm run test:unit && npm run test:e2e`
Erwartet: alle grün

- [ ] **Step 4: Manueller Ende-zu-Ende-Check gegen ein echtes Garmin-Konto**

Nicht automatisierbar in dieser Session (braucht echten Garmin-Login mit MFA). Nach Merge: Nutzer durchläuft `/onboarding` → `/sync` → "Backfill starten" im Browser gegen sein echtes Konto, beobachtet Live-Polling bis `done`, prüft stichprobenartig über `GET /api/data/wellness/hr?from_date=...&to_date=...` und `GET /api/data/activities`, ob die zurückgegebenen Werte mit der Garmin-Connect-App übereinstimmen.

- [ ] **Step 5: Tag**

```bash
git tag v0.2.0-phase1-haertung
```

---

## Mac → Windows Notes

- Diese Phase wurde auf Windows entwickelt (Python 3.13, `.venv/Scripts/python`) — `Makefile`-Fix in Task 5 deckt beide Plattformen über `||`-Fallback ab.
- Docker Desktop hat auf diesem System keinen Autostart — vor jeder Session manuell prüfen (`docker ps`), sonst schlagen Integrationstests und die App selbst mit Connection-Refused fehl.
