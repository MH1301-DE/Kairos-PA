# Stufe 1 — Datenbasis, abgeleitete Daten, Lese-Tools (AP 1a–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native, vom Nutzer so beauftragt) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sekundendaten als Arrays (`activity_stream`) aus archivierten FIT-ZIPs, TimescaleDB entfernt, `activity` vollständig und korrekt, Tage nach Ortszeit, HFmax aus Nutzereingabe; darauf vier abgeleitete Tabellen (Steckbrief, Splits, Best Efforts, Soll/Ist) und fünf Aktivitäts-Lese-Tools für den Agenten.

**Architecture:** Der Sync archiviert pro Aktivität das Original-ZIP als eigene `raw_payload`-Zeile (`payload_format='fit_zip'`) und schreibt daraus Achse + Kanäle (`activity_stream_axis`/`activity_stream`). Ein Reprocess-Job baut alles aus dem Archiv neu (optional mit gedrosseltem Nachabruf). Abgeleitete Daten sind reine Python-Funktionen über die ausgerichteten Arrays plus FIT-Messages, versioniert über `ACTIVITY_DERIVED_ALGO_VERSION`. Die Lese-Tools lesen nur die DB und formatieren serverseitig über `agent/format.py`.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy async, Alembic, PostgreSQL 16 (ab AP 1b ohne TimescaleDB), garmin-fit-sdk, garminconnect 0.3.17, SvelteKit (Einstellungsseite), pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` (§1.4, §2.1–2.2, Teil A, B, C, §12, §13) und `docs/superpowers/specs/2026-10-13-brainstorming-entscheidungen.md` (D1–D34). Die Spec ist verbindlich; Korrekturen beim Umsetzen werden mit Datum in die Spec eingetragen.

**Ersetzt:** `docs/superpowers/plans/2026-10-13-ap1-aktivitaeten-datengrundlage.md` (vor dem Brainstorming geschrieben: schrieb weiter in `activity_record`, behielt TimescaleDB). Wiederverwendbare Teile (Sportprofil, Upsert-Fix, Lösch-Abgleich, FIT-Pause) sind hier übernommen und angepasst.

## Global Constraints

- `install_rls_listener(session, user_id)` auf jeder Session, die RLS-Tabellen liest oder schreibt; jede neue Tabelle: `ENABLE` + `FORCE ROW LEVEL SECURITY` + Policy `tenant_isolation` auf `user_id` (Muster `7c1b2e4f9a3d_goal_table.py`).
- `activity_list` vor `activity_fit`; Streams brauchen `activity.id`.
- FIT-Download = ZIP, immer über `decode_fit_zip` entpacken.
- Nur `garminconnect`, nur Token-Login (R6). Kein wiederholtes Login; ein Client pro Job.
- `GARMIN_FIT_DOWNLOAD_PAUSE_S` Default 2,0 s zwischen FIT-Downloads (A.5).
- Kanäle V1: `hr`, `cadence`, `speed_mps`, `distance_m`, `altitude_m`, `power_w`, `lat_deg`, `lng_deg`, `temp_c`; `lat_deg`/`lng_deg` in `v8`, alle anderen in `v4`.
- Kadenz-Kanal = FIT `cadence + fractional_cadence` pro Bein; Lauf-spm = 2 × Wert.
- `payload_format` ∈ {`json_gzip`, `fit_zip`}; `deleted_reason` ∈ {`kairos`, `garmin_sync`}; `sport_profile` ∈ {`running`, `cycling`, `swimming`, `hiking`, `generic`}; `quality` ∈ {`ok`, `partial`, `suspect`}; `distance_source` ∈ {`gps`, `watch_estimate`, `pool`, `mixed`, `none`}.
- HFmax: `hr_max_override` (120–230) → sonst 220 − Alter → sonst nichts. Kein gemessener Wert als Kandidat.
- Trefferregel: Pace/Speed/Kadenz/Leistung Ø im Bereich ± 2 %; HF ≥ 80 % der Zeit im Bereich; < 20 s, kein Ziel, „unklar“ → `hit = NULL`.
- Tool-Obergrenzen (Tokens, ≈ 3,7 Zeichen/Token): search 600, get 700, splits 1.200, analyze 800, best_efforts 500.
- Distanzschlüssel: `800m`, `1500m`, `3000m`, `5k`, `10k`, `hm`, `m`, `50k`, `100k`; `BEST_EFFORT_MAX_STEP_SPEED_MPS` = 8,5.
- `ruff` (line-length 100), `mypy --strict src`, pytest **alle grün, 0 skipped** (Docker läuft) vor jedem Commit. Kommentare eine kurze Zeile; keine Docstrings an unverändertem Code.
- Conventional Commits, ein Commit pro Task, Footer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Branch `stufe1-datenbasis`. Kein `git push` ohne OK.

## Haltepunkte (aus dem Auftrag)

| # | Wann | Was ich zeige / wofür ich das OK brauche |
|---|---|---|
| H1 | Task 7, vor dem ersten Garmin-Request | Nachabruf für 2–3 Aktivitäten, gemessene Dauer, Hochrechnung für 139 → OK für den Rest |
| H2 | Task 9, vor dem Entfernen von TimescaleDB auf der Dev-DB | `pg_dump` erstellt, V8-Bericht, Zeilenzahlen → OK |
| H3 | Task 13 | Hinweis an Max: HFmax 214 auf der neuen Seite eintragen, **bevor** Task 14 live geht |
| H4 | Task 15, vor dem Recompute der Historie | Vorher/Nachher-Tabelle für 7 Tage (TRIMP, HF-Zonen, Ruhepuls, Schlaf) → OK |
| H5 | jederzeit | ein Abnahmekriterium aus §13 ist nicht erreichbar |

## Review Focus

1. **Doppelte Zeitstempel in FIT-Records** (Uhr schreibt zwei Records in derselben Sekunde) → Achse bleibt streng aufsteigend, erster Wert gewinnt (wie `ON CONFLICT DO NOTHING` bei `activity_record`), V8 stimmt trotzdem (Task 2).
2. **ZIP nicht mehr ladbar** (bei Garmin gelöscht, 404/500) → JSON-Rückfall mit `source='fit_json'`, Aktivität im Ergebnis gelistet, Job läuft weiter; 429 oder Auth-Fehler → sofortiger Abbruch ohne weitere Requests (Task 6).
3. **Teilweise oder fehlerhafte `activity_list`-Antwort** → kein einziger Lösch-Marker; eine wieder auftauchende Aktivität bekommt `deleted_at = NULL` (Task 10, 11).
4. **Sommerzeit und Mitternacht** → Lauf um 00:30 Ortszeit zählt zum lokalen Tag, Offsets +60/+120 je Saison, Wellness-Werte nach `home_timezone` (Task 12).
5. **Aktivität ohne Sekundendaten / ohne GPS / Indoor / Schwimmen** → Steckbrief `quality='partial'`, keine Splits/Best Efforts, kein Crash in Tools (Task 18–20, 25).

## Entscheidungen zu den offenen Fragen

**2026-10-14:** Max hat den Plan freigegeben („Der Plan passt so“); für Q2–Q6 gilt jeweils der Vorschlag. Q1: `gh` fehlt weiterhin, der Branch `stufe1-datenbasis` zweigt vom lokalen `main` ab; PR #1 merged Max im Browser, Konflikte sind nicht zu erwarten (Spec-Dateien identisch).

| # | Thema | Lücke / Widerspruch | Mein Vorschlag |
|---|---|---|---|
| Q1 | PR #1 mergen | `gh` ist auf diesem Rechner nicht installiert. Außerdem: lokales `main` hat 2 ungepushte Commits (`52dae17` alter AP-1-Plan, `0b86196` Spec — inhaltsgleich mit `35ffb8b` aus dem PR); der PR enthält zusätzlich `38ab5c5` (`{SPEC}`-Links). | Du mergst PR #1 im Browser, danach `git pull` (konfliktfrei, Spec-Dateien identisch). Alternativ `gh` installieren (`winget install GitHub.cli`, dann `gh auth login`). |
| Q2 | Frische Datenbank ohne TimescaleDB | Migration `6bf30be597a0` ruft `CREATE EXTENSION timescaledb` und `create_hypertable` auf. Auf `postgres:16` (Testcontainer, CI, neue Installation) scheitert `alembic upgrade head` damit schon vor der neuen Migration. A.7 sagt dazu nichts. | `6bf30be597a0` so ändern, dass sie ohne verfügbare Extension nichts tut (Prüfung über `pg_available_extensions`). Bestehende DBs sind davon nicht betroffen. Eintrag in der Spec unter A.7. |
| Q3 | HF-Ziele in Soll/Ist (B.6) | B.6 nimmt HF-Ziele aus dem Workout-Spiegel `garmin_workout` — der entsteht erst in AP 5 (D.3). In AP 2 gäbe es keinen Spiegel. | In AP 2 HF-Ziele mit `target_source='unclear'` (nicht bewertet); Pace/Kadenz/Leistung aus der FIT werden bewertet. In AP 5 nach dem Spiegel-Abgleich `algo_version` erhöhen → HF-Schritte werden nachbewertet. V7 prüft Ausführungen und Dauer, also unabhängig davon. Alternative: in AP 2 einen schmalen Lese-Abruf `get_workouts`/`get_workout_by_id` bauen (Garmin-Requests, Teil von D.7). |
| Q4 | Datensatz für Eval 17–21, 26 | Die Eval-Suite seedet synthetische Tageswerte; echte Aktivitäten mit Splits, Schwimmen und Workout-Schritten lassen sich nicht sinnvoll synthetisch erzeugen. | Diese sechs Fälle (alles Lese-Tools) gegen deinen echten Nutzer in der Dev-DB laufen lassen (`--user-id`), Prüfung „Zahlen exakt wie im Tool-Ergebnis“. Fälle 1–16 bleiben auf dem Seed. |
| Q5 | Regressions-Fixtures (§12.3) | Fixierte Beispielaktivitäten bedeuten echte FIT-Inhalte im Repo (GPS-Spur). | Dekodierte Messages als `json.gz` (keine FIT-Datei), GPS um einen festen Versatz verschoben, Seriennummern/Gerätedaten entfernt; 4 Aktivitäten: Lauf mit Auto-Lap 1 km, Workout 272, Schwimmen, Laufband. |
| Q6 | `resting_hr_override` | A.6 nennt den Wertebereich nur für `hr_max_override`. | 30–100 bpm. |

## Abweichungen vom Spec-Zuschnitt (bewusst, bitte prüfen)

- Die Systemprompt-Zeilen aus G.5, die die **Aktivitäts-Lese-Tools** betreffen (erste zwei Punkte), kommen schon in AP 3, damit Eval 17–21/26 sinnvoll laufen. Die HF-Zonen-Zeile im Lagebild und die Workout-Punkte bleiben AP 4/5.
- `activity_analyze(operation="curve")` liefert in AP 3 die Daten; `render` mit `y_format: "pace"` und km/min-Achse ist G.2 und kommt in AP 4.
- In AP 1a ordnet der HF-Bucket-Recompute Samples wie bisher dem **UTC-Tag des Samples** zu (Ergebnis identisch zu heute, dadurch prüfbar). Der Wechsel auf den lokalen Starttag folgt in AP 1c (A.8).

## File Structure

| Datei | Verantwortung |
|---|---|
| `alembic/versions/<rev>_activity_stream_and_fit_archive.py` (1a) | `raw_payload.payload_format`, `activity.fit_payload_id` (ersetzt `fit_object_key`), `activity_stream_axis`, `activity_stream`, lz4, RLS |
| `alembic/versions/6bf30be597a0_…py` (1b, nach Q2) | ohne verfügbare Extension no-op |
| `alembic/versions/<rev>_drop_timescaledb.py` (1b) | `wellness_sample` als normale Tabelle, `activity_record` und Extensions löschen |
| `alembic/versions/<rev>_activity_profile_and_soft_delete.py` (1c) | Spalten aus A.1, Indizes, `activity_type` entfernen |
| `alembic/versions/<rev>_activity_derived_tables.py` (2) | `activity_stats`, `activity_split`, `activity_best_effort`, `activity_step_result` |
| `src/kairos/activities/streams.py` | `STREAM_CHANNELS`, `build_streams()` (rein) |
| `src/kairos/activities/stream_repository.py` | `replace_streams()`, `load_stream()` |
| `src/kairos/activities/fit_archive.py` | ZIP → `raw_payload`, `fit_payload_id` setzen, ZIP/JSON-Rückfall laden |
| `src/kairos/activities/reprocess.py` | Reprocess-Service (A.4) |
| `src/kairos/activities/reconcile.py` | Lösch-Abgleich (A.3) |
| `src/kairos/activities/derive/{common,stats,splits,best_efforts,steps,service}.py` | Teil B |
| `src/kairos/connectors/garmin/sport_profile.py` | `typeKey`/`parentTypeId` → Profil |
| `src/kairos/connectors/types.py` | `RawFile`, `RawPayloadEnvelope.files` |
| `src/kairos/connectors/garmin/connector.py`, `normalize.py` | ZIP statt JSON-Records, Pause, neue `activity`-Felder |
| `src/kairos/ingestion/service.py` | Dateien archivieren, `post_window`-Hook |
| `src/kairos/repositories/raw_payload.py` | `upsert_file()` |
| `src/kairos/repositories/canonical.py` | `activity_record`-Pfad entfernt, Upsert aller fachlichen Spalten |
| `src/kairos/repositories/metrics_recompute.py`, `metrics_data.py`, `data_read.py` | Streams statt `activity_record`, Ortszeit, gelöschte ausblenden |
| `src/kairos/metrics/hr_zones.py` + 3 Varianten | neue HFmax-Regel |
| `src/kairos/routers/activities.py` (neu), `settings_profile.py` (neu), `api.py` | `POST /api/activities/reprocess`, `GET/PUT /api/settings/profile` |
| `web/src/routes/settings/+page.{server.ts,svelte}` (neu) | Einstellungsseite HFmax/Geburtsdatum/Ruhepuls |
| `src/kairos/agent/format.py` (neu), `agent/activity_tools.py` (neu), `agent/tools.py`, `agent/prompt.py` | AP 3 |
| `scripts/verify_activity_streams.py`, `scripts/validate_activity_derivations.py` | V8 bzw. V1–V7 |
| `scripts/agent_eval_suite.py` | Seed ohne `activity_record`; Fälle 17–21, 26 |
| `tests/fixtures/activities/*.json.gz` | anonymisierte Beispielaktivitäten (Q5) |
| `tests/conftest.py`, `deploy/docker-compose*.yml`, `.github/workflows/ci.yml` | `postgres:16` |

---

## AP 1a — Speicher und FIT-Archiv (A.2, A.4, A.5)

### Task 1: Migration und ORM für Archiv und Streams

**Files:**
- Create: `alembic/versions/<rev>_activity_stream_and_fit_archive.py` (down_revision `7a1c2e9d4b30`)
- Modify: `src/kairos/db/models.py` (`RawPayload.payload_format`, `Activity.fit_payload_id`, `Activity.fit_object_key` entfernen, neue Klassen `ActivityStreamAxis`, `ActivityStream`)
- Test: `tests/test_activity_stream_schema_integration.py`

**Interfaces:**
- Produces: `RawPayload.payload_format: str` (Server-Default `'json_gzip'`, CHECK `raw_payload_payload_format_check`); `Activity.fit_payload_id: int | None` (FK `raw_payload.id` ON DELETE SET NULL); `ActivityStreamAxis(activity_id: int PK, user_id, start_at, t_offset_s: list[int], source: str, algo_version: int)`; `ActivityStream(activity_id, channel PK, user_id, v4: list[float|None] | None, v8: list[float|None] | None)`, CHECK `num_nonnulls(v4, v8) = 1`. Beide `user_id` mit FK auf `app_user` (CASCADE). `SET COMPRESSION lz4` auf `t_offset_s`, `v4`, `v8`.

- [ ] **Step 1: Failing tests**
  - `test_stream_tables_exist_with_rls`: `pg_class.relrowsecurity` und `relforcerowsecurity` sind für beide Tabellen `true`.
  - `test_stream_columns_use_lz4`: `pg_attribute.attcompression = 'l'` für die drei Array-Spalten.
  - `test_stream_check_exactly_one_array`: Insert mit `v4` und `v8` gesetzt → `IntegrityError`.
  - `test_payload_format_defaults_to_json_gzip` und CHECK lehnt `'xml'` ab.
  - `test_stream_rls_isolates_users` (Muster `tests/test_rls.py`, `app_session`): Nutzer B sieht Achse/Kanäle von A nicht.
  - `test_activity_delete_cascades_streams`.
- [ ] **Step 2:** `.venv/Scripts/python -m pytest tests/test_activity_stream_schema_integration.py -q` → FAIL (Tabellen fehlen).
- [ ] **Step 3:** Migration schreiben. `fit_object_key` droppen (laut Spec 0/136 befüllt; die Migration prüft das und bricht ab, falls doch Werte drinstehen). Downgrade: Tabellen droppen, Spalten zurück.
- [ ] **Step 4:** Tests grün; `alembic upgrade head` gegen den Testcontainer läuft (conftest).
- [ ] **Step 5:** Volle Suite, ruff, mypy; Commit `feat(db): activity_stream tables and fit archive columns`.

### Task 2: Stream-Aufbau aus FIT-Records (rein)

**Files:**
- Create: `src/kairos/activities/__init__.py`, `src/kairos/activities/streams.py`
- Test: `tests/test_activity_streams.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ChannelSpec:
      code: str; unit: str; storage: Literal["v4", "v8"]

  STREAM_CHANNELS: tuple[ChannelSpec, ...]  # die 9 Kanäle aus den Global Constraints

  @dataclass(frozen=True)
  class StreamSet:
      start_at: datetime                    # UTC, erster Record
      t_offset_s: list[int]                 # streng aufsteigend
      channels: dict[str, list[float | None]]  # nur Kanäle mit ≥ 1 Wert, Länge == len(t_offset_s)
      source: Literal["fit_zip", "fit_json"]

  def build_streams(records: Sequence[Mapping[str, object]], *, source: ...) -> StreamSet | None
  ```
  `records` sind `record_mesgs` aus `decode_fit_zip` (Zeitstempel `datetime`) **oder** die archivierten JSON-Records (Zeitstempel ISO-String). Ohne gültigen Zeitstempel → Record übersprungen; ohne Records → `None`.

Regeln: `speed_mps` = `enhanced_speed`, sonst `speed`; `altitude_m` = `enhanced_altitude`, sonst `altitude`; `distance_m` = `distance`; `cadence` = `cadence + (fractional_cadence or 0)`; Positionen über `_semicircle_to_deg` (aus `normalize.py` nach `streams.py` verschieben und dort importieren); `temp_c` = `temperature`; `hr` = `heart_rate`; `power_w` = `power`. Doppelte Sekunde → erster Record gewinnt. Ganzzahlige Offsets (`int((ts - start).total_seconds())`), Sub-Sekunden-Zeitstempel → abgerundet, Duplikat danach ebenfalls verworfen.

- [ ] **Step 1: Failing tests**
  - Ausrichtung: 3 Records, `heart_rate` nur in Record 1 und 3 → `channels["hr"] == [140.0, None, 150.0]`, Länge 3.
  - Kanal ohne Werte fehlt in `channels`.
  - Enhanced-Vorrang: Record mit `speed=2.0, enhanced_speed=2.5` → 2.5.
  - Kadenz: `cadence=82, fractional_cadence=0.5` → 82.5.
  - Semicircle: `position_lat=2**30` → 90.0.
  - Duplikat-Sekunde: zwei Records mit gleichem `timestamp`, HF 140/141 → ein Offset, Wert 140.
  - JSON- und datetime-Zeitstempel ergeben identische `StreamSet`s.
  - Leere Liste → `None`.
- [ ] **Step 2:** FAIL (Modul fehlt).
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Grün.
- [ ] **Step 5:** Commit `feat(activities): build aligned per-channel streams from FIT records`.

### Task 3: Stream-Repository

**Files:**
- Create: `src/kairos/activities/stream_repository.py`
- Test: `tests/test_activity_stream_repository_integration.py`

**Interfaces:**
- Consumes: `StreamSet`, `STREAM_CHANNELS` (Task 2), ORM (Task 1).
- Produces:
  ```python
  async def replace_streams(session, *, user_id: UUID, activity_id: int, streams: StreamSet, algo_version: int) -> int  # Zahl der Kanäle
  async def load_stream(session, *, activity_id: int, channels: Sequence[str] | None = None) -> LoadedStream | None
  @dataclass(frozen=True)
  class LoadedStream: start_at: datetime; t_offset_s: list[int]; channels: dict[str, list[float | None]]; source: str
  STREAM_ALGO_VERSION = 1
  ```
  `replace_streams` löscht Achse + Kanäle der Aktivität und schreibt neu, in der Transaktion des Aufrufers. Prüfung beim Schreiben (A.2): Länge jedes Kanals == Länge der Achse, sonst `ValueError`.

- [ ] **Step 1: Failing tests:** Rundweg (schreiben → laden, identisch inkl. `None`-Elementen); zweimal `replace_streams` → gleiche Zeilenzahl, neue Werte; `channels=["hr"]` lädt nur HF; Kanal mit falscher Länge → `ValueError`; ohne RLS-Listener auf `app_session` → `load_stream` liefert `None`.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(activities): stream repository with replace and load`.

### Task 4: Sync archiviert ZIPs und schreibt Streams; FIT-Pause

**Files:**
- Modify: `src/kairos/connectors/types.py`, `src/kairos/connectors/garmin/connector.py`, `src/kairos/connectors/garmin/normalize.py` (`_normalize_activity_fit` entfällt bzw. liefert `[]`), `src/kairos/ingestion/service.py`, `src/kairos/repositories/raw_payload.py`, `src/kairos/repositories/canonical.py` (Pfad `activity_record` raus), `src/kairos/routers/sync.py`, `src/kairos/config.py`
- Create: `src/kairos/activities/fit_archive.py`
- Test: `tests/test_garmin_connector_fit_archive.py`, `tests/test_sync_service.py` (erweitern), `tests/test_fit_archive_integration.py`

**Interfaces:**
- Produces:
  ```python
  # connectors/types.py
  @dataclass(frozen=True)
  class RawFile:
      kind: str               # 'activity_fit_file'
      key: str                # Garmin activity_id
      window_start: datetime  # Aktivitätsstart UTC (aus startTimeGMT)
      content: bytes          # ZIP unverändert
      payload_format: Literal["fit_zip"]
  @dataclass(frozen=True)
  class RawPayloadEnvelope:
      window: Window; payload: JSONValue; files: tuple[RawFile, ...] = ()

  # repositories/raw_payload.py
  async def upsert_file(self, *, user_id, connector_id, file: RawFile) -> int  # content_hash = sha256(content), payload_gzip = content

  # ingestion/service.py
  PostWindowHook = Callable[[str, RawPayloadEnvelope, int, dict[str, int]], Awaitable[None]]
  # (kind, envelope, raw_payload_id, file_ids_by_key) — läuft nach dem Canonical-Upsert, vor mark_success
  SyncService(..., post_window: PostWindowHook | None = None)

  # activities/fit_archive.py
  async def ingest_fit_files(session, *, user_id: UUID, file_ids_by_key: dict[str, int], files: Sequence[RawFile]) -> list[str]  # Liste fehlgeschlagener activity_ids
  async def load_fit_messages(session, *, activity: Activity) -> tuple[dict[str, Any], Literal["fit_zip", "fit_json"]] | None
  ```
- `activity_fit`-Tages-Payload wird ein Manifest: `{"activities": [{"activity_id": "…", "sha256": "<hex>"} | {"activity_id": "…", "error": "…"}]}` — kein dekodiertes JSON mehr (A.2).
- Connector: `GarminConnector(garmin, *, fit_download_pause_s: float = 0.0)`; `time.sleep(pause)` **zwischen** zwei Downloads (nicht vor dem ersten), läuft ohnehin in `asyncio.to_thread`.
- `ingest_fit_files`: je Datei Aktivität per `external_id` suchen (fehlt → überspringen, `activity_list` muss vorher laufen), `activity.fit_payload_id` setzen, `decode_fit_zip` → `build_streams(..., source="fit_zip")` → `replace_streams`. Fehler einer Datei → Savepoint (`session.begin_nested()`) zurückrollen, ID in die Rückgabeliste, Rest läuft weiter.
- `Settings.garmin_fit_download_pause_s: float = 2.0`.

- [ ] **Step 1: Failing tests**
  - Connector mit Fake-Garmin (2 Aktivitäten, `download_activity` liefert ZIP-Bytes aus einer Mini-FIT der bestehenden Testhilfen in `tests/test_fit_decoder.py`): Envelope hat 2 `RawFile`s, Manifest ohne `records`; Pause: `time.sleep` (gepatcht) genau einmal mit 2.0 aufgerufen.
  - Download wirft → Manifest-Eintrag mit `error`, keine Datei, nächste Aktivität wird trotzdem geladen.
  - `SyncService.run_window`: Fake-Raw-Repo bekommt 1× `upsert` + 2× `upsert_file`; `post_window` mit `file_ids_by_key` aufgerufen.
  - Integration: `ingest_fit_files` schreibt Achse + Kanäle und `fit_payload_id`; kaputtes ZIP → in Rückgabeliste, andere Aktivität geschrieben.
  - `SqlCanonicalRepository` kennt `activity_record` nicht mehr (Test, dass `upsert_many` mit `record_type="activity_record"` 0 schreibt).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementieren; in `routers/sync.py` den Hook verdrahten (`kind == "activity_fit"` → `ingest_fit_files`) und `settings.garmin_fit_download_pause_s` an den Connector übergeben.
- [ ] **Step 4:** Grün; `tests/test_garmin_connector_kinds.py` weiterhin grün.
- [ ] **Step 5:** Commit `feat(sync): archive original FIT zips and write activity streams`.

### Task 5: Lesepfade auf Streams umstellen

**Files:**
- Modify: `src/kairos/repositories/metrics_recompute.py` (`recompute_hr_bucket_seconds_daily`), `src/kairos/repositories/data_read.py` (`get_activity_detail`), `src/kairos/routers/data.py`
- Test: `tests/test_metrics_recompute_integration.py` (erweitern), `tests/test_data_read_repository.py`, `tests/test_data_router.py`

**Interfaces:**
- `recompute_hr_bucket_seconds_daily` zählt HF-Werte aus `activity_stream` (`channel='hr'`), SQL über `unnest(v4) WITH ORDINALITY` + `t_offset_s[ord]`, Tag = `((axis.start_at + t_offset * interval '1 second') AT TIME ZONE 'UTC')::date` (1a; siehe Abweichungen). `NULL`-Elemente zählen nicht. Bucket wie bisher `floor(v/5)*5`.
- `get_activity_detail(..., max_points: int = 2000) -> ActivityDetail(activity, series: dict[str, list[float | None]], t_offset_s: list[int])`: Mittelung je Bucket, wenn länger als `max_points`.
- `GET /api/data/activities/{external_id}?max_points=` (1–10.000) liefert `{…, "t_offset_s": [...], "series": {"hr": [...], …}}` statt `records`. Kein Frontend-Aufrufer (Spec §2), Antwortform darf sich ändern.

- [ ] **Step 1: Failing tests:** gleiche HF-Daten einmal als `activity_record` (alte Tabelle existiert in 1a noch) und einmal als Stream → `hr_bucket_seconds_daily` identisch (Test fixiert das alte Ergebnis als erwartete Zahlen); Sample über UTC-Mitternacht landet auf zwei Tagen; Detail mit 5.000 Punkten und `max_points=100` → 100 Werte, Mittelwerte korrekt.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `refactor(metrics): read HR buckets and activity detail from activity_stream`.

### Task 6: Reprocess-Service und `POST /api/activities/reprocess`

**Files:**
- Create: `src/kairos/activities/reprocess.py`, `src/kairos/routers/activities.py`
- Modify: `src/kairos/api.py`, `src/kairos/ingestion/job_registry.py` (Kind `reprocess` im Job-Listing), `src/kairos/routers/sync.py` (`_build_garmin_client` nur importiert, nicht verändert)
- Test: `tests/test_reprocess_integration.py`, `tests/test_activities_router.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class ReprocessResult:
      activities_total: int
      streams_written: int
      from_zip: int; from_json: int
      no_data: list[str]          # weder ZIP noch JSON
      fetch_failed: list[dict[str, str]]  # {"activity_id", "reason"}
      fetched: int
      aborted_reason: str | None  # 429 / Auth

  async def reprocess_activities(session, *, user_id, from_date: date | None, to_date: date | None,
      activity_ids: list[int] | None, refetch_fit: bool, garmin: object | None,
      pause_s: float, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
      on_progress: Callable[[int, int], None] | None = None) -> ReprocessResult
  ```
  Ablauf (A.4): (1) `activity_list`-Payloads im Bereich neu normalisieren (jüngster Payload je Aktivität gewinnt, nach `fetched_at`), ohne Garmin; (2) mit `refetch_fit`: für Aktivitäten ohne `fit_payload_id` ZIP laden (`download_activity(..., ORIGINAL)` in `to_thread`), Pause **zwischen** Downloads, als `RawFile` archivieren; 429 (`GarminConnectTooManyRequestsError`) oder `GarminConnectAuthenticationError` → `aborted_reason`, keine weiteren Requests; andere Fehler → `fetch_failed`; (3) je Aktivität `load_fit_messages` (ZIP, sonst jüngster `activity_fit`-JSON-Payload mit diesem `activity_id`, Dedup nach AP 0 #6) → `build_streams` → `replace_streams`; (4) Teil B kommt in Task 22 hinzu.
- Router: `POST /api/activities/reprocess` Body `{from_date?, to_date?, activity_ids?, refetch_fit=false}` → 202 + Job. Teilt Lock (`garmin`/`activity_list` **und** `activity_fit`) und 300-s-Cooldown mit dem Backfill; nur mit `refetch_fit` wird ein Garmin-Client gebaut (ein Token-Login pro Job). 409 bei laufendem Lock, 429 im Cooldown. Commit je 10 Aktivitäten (ein Absturz verliert höchstens 10).

- [ ] **Step 1: Failing tests**
  - Ohne `refetch_fit`: zwei JSON-Payloads derselben Aktivität (alt/neu) → Streams aus dem jüngeren, `source='fit_json'`, Fake-Garmin nie aufgerufen.
  - Mit `refetch_fit`: Fake-Garmin, 3 Aktivitäten ohne ZIP → 3 Downloads, `sleep` 2× mit 2.0; danach `source='fit_zip'`, `fit_payload_id` gesetzt.
  - 2. Download wirft 404-artigen Fehler → `fetch_failed` enthält ihn, Aktivität nutzt JSON-Rückfall.
  - 2. Download wirft 429 → `aborted_reason`, 3. Download nie aufgerufen.
  - Zweimal hintereinander → identische Zeilenzahlen in `activity_stream`.
  - Router: Cooldown nach Backfill → 429; laufender `activity_fit`-Lock → 409; `refetch_fit=false` baut keinen Garmin-Client.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(activities): reprocess job with optional throttled FIT refetch`.

### Task 7: Betrieb 1a — Nachabruf, V8, Abnahme

**Files:**
- Create: `scripts/verify_activity_streams.py`
- Modify: `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` (Korrekturen mit Datum, falls nötig)

**Interfaces:**
- `verify_activity_streams.py --user-id <uuid>`: je Aktivität und Kanal Nicht-NULL-Werte in `activity_stream` vs. Zeilen in `activity_record` (`distance_m` ausgenommen, `cadence` nur Anzahl); listet Abweichungen, Aktivitäten ohne Stream, Kanäle nur im Stream (z. B. `temp_c`), Quelle (ZIP/JSON) und Ø Größe je Aktivität (`pg_column_size`). Exit-Code 1 bei Abweichung.

- [ ] **Step 1:** Test `tests/test_verify_activity_streams.py` für die Vergleichsfunktion (reine Funktion über zwei Count-Dicts).
- [ ] **Step 2:** Backend mit neuem Code starten (`alembic upgrade head` auf der Dev-DB — nur additive Migration aus Task 1; vorher prüfen, dass kein Sync-Job läuft).
- [ ] **Step 3:** Reprocess **ohne** Garmin (`refetch_fit=false`) → alle 139 aus JSON; V8 laufen lassen.
- [ ] **Step 4: ⏸ H1.** Reprocess mit `activity_ids` = 3 Aktivitäten und `refetch_fit=true`. Dauer messen, Hochrechnung für 139 (Download-Zeit + 2 s Pause) zeigen. **Auf OK warten.**
- [ ] **Step 5:** Rest nachladen (`refetch_fit=true`, ohne IDs). Ergebnisliste (`fetch_failed`, `aborted_reason`) dokumentieren.
- [ ] **Step 6:** V8 erneut; Abnahme §13 1a: 139/139 in `activity_stream`, V8 erfüllt, ≈ 60 KB je Aktivität. Commit `chore(activities): stream verification script and 1a acceptance`.

---

## AP 1b — TimescaleDB entfernen (A.7)

### Task 8: Migration ohne TimescaleDB, Images, Modelle

**Files:**
- Modify: `alembic/versions/6bf30be597a0_hypertables_wellness_activity_record.py` (Q2), `src/kairos/db/models.py` (`ActivityRecord` raus, `WellnessSample.observed_at` nicht mehr PK), `tests/conftest.py` (`POSTGRES_IMAGE = "postgres:16"`), `deploy/docker-compose.yml`, `deploy/docker-compose.dev.yml` (Image `postgres:16`, Volume-Pfad `/var/lib/postgresql/data`, neues Volume `pgdata_dev16` bzw. `pgdata16`), `.github/workflows/ci.yml`, `src/kairos/repositories/data_read.py`, `scripts/agent_eval_suite.py` (Seed schreibt Streams statt `activity_record`), alle Tests, die `activity_record` schreiben
- Create: `alembic/versions/<rev>_drop_timescaledb.py`
- Test: `tests/test_drop_timescaledb_migration_integration.py`

**Interfaces:**
- Migration `upgrade()`:
  1. `CREATE TABLE wellness_sample_new (LIKE wellness_sample INCLUDING DEFAULTS)`; PK nur `id`; `uq_wellness_sample (user_id, metric_id, observed_at)`; FKs wie bisher.
  2. `INSERT … SELECT *` ; Zeilenzahl vergleichen, sonst `RuntimeError`.
  3. `DROP TABLE wellness_sample`; `ALTER TABLE wellness_sample_new RENAME TO wellness_sample`; Sequenz an neue Tabelle hängen und `setval(max(id))`.
  4. RLS: `ENABLE`, `FORCE`, Policy `tenant_isolation`; Indizes wie bisher (inkl. `(user_id, metric_id, observed_at DESC)` aus `a7f9f3d1c2b4` prüfen und nachbauen).
  5. `DROP TABLE activity_record`; `DROP EXTENSION IF EXISTS timescaledb_toolkit`; `DROP EXTENSION IF EXISTS timescaledb`.
  - `downgrade()` → `NotImplementedError("restore pg_dump")`.
  - Schutz: bricht ab, wenn es Aktivitäten mit `activity_record`-Zeilen, aber ohne `activity_stream_axis` gibt (V8-Voraussetzung).
- `6bf30be597a0`: nur ausführen, wenn `SELECT 1 FROM pg_available_extensions WHERE name='timescaledb'` eine Zeile liefert.

- [ ] **Step 1: Failing tests** (gegen `postgres:16`): `alembic upgrade head` von leer läuft durch; `wellness_sample` hat PK `(id)`, RLS forced, Unique-Key vorhanden; `activity_record` existiert nicht; `pg_extension` ohne `timescaledb`; Migrationstest mit Daten: Upgrade bis zur Vorgänger-Revision, 3 Wellness-Zeilen einfügen, Upgrade → 3 Zeilen, neue Inserts bekommen höhere `id`; `test_rls.py` grün.
- [ ] **Step 2:** FAIL (`CREATE EXTENSION` auf `postgres:16`).
- [ ] **Step 3:** Implementieren, Modelle/Seed/Tests bereinigen (Kommentare „Timescale needs the partitioning column …“ entfernen).
- [ ] **Step 4:** Volle Suite gegen `postgres:16` grün, 0 skipped.
- [ ] **Step 5:** Commit `feat(db)!: drop TimescaleDB, wellness_sample as plain table, remove activity_record`.

### Task 9: Betrieb 1b — Dev-DB umziehen, Runbook

**Files:**
- Modify: `docs/HANDOVER.md` (Runbook A.7)

- [ ] **Step 1:** Prüfen, dass kein Sync/Reprocess läuft. `pg_dump -Fc` der Dev-DB (mit Timescale) nach `backups/2026-10-xx-pre-1b.dump` (außerhalb des Repos, Pfad im Runbook).
- [ ] **Step 2: ⏸ H2.** Zeigen: Dump-Größe, V8-Bericht (Task 7), Zeilenzahlen aller Tabellen (`SELECT relname, n_live_tup` + exakte `count(*)` für `wellness_sample`, `activity`, `activity_stream*`, `raw_payload`). **Auf OK warten.**
- [ ] **Step 3:** `alembic upgrade head` auf der Dev-DB (noch Timescale-Image).
- [ ] **Step 4:** Zweiter Dump (jetzt ohne Extension), neuen Container `postgres:16` mit neuem Volume starten (`docker compose -f deploy/docker-compose.dev.yml up -d`), `pg_restore`, Zeilenzahlen vorher/nachher vergleichen, `alembic current` = Head, Backend gegen die neue DB starten, Dashboard-Endpunkte stichprobenartig abrufen.
- [ ] **Step 5:** Altes Volume **nicht** löschen (Rückweg), im Runbook vermerkt. Runbook schreiben (Schritte, Befehle, Rückweg). Commit `docs(handover): runbook for removing TimescaleDB`.

---

## AP 1c — Aktivitäts-Spalten, Abgleich, Tage, HFmax (A.1, A.3, A.6, A.8)

### Task 10: `activity` erweitern, Sportprofil, Normalizer, Upsert-Fix

**Files:**
- Create: `alembic/versions/<rev>_activity_profile_and_soft_delete.py`, `src/kairos/connectors/garmin/sport_profile.py`, `tests/fixtures/garmin/activity_list_item.json` (echtes Element, anonymisiert)
- Modify: `src/kairos/db/models.py` (`Activity`), `src/kairos/connectors/garmin/normalize.py` (`_normalize_activity_list`), `src/kairos/repositories/canonical.py` (`_write_activity`)
- Test: `tests/test_sport_profile.py`, `tests/test_garmin_normalize.py`, `tests/test_canonical_repository_integration.py`

**Interfaces:**
- Spalten aus A.1 exakt (`sport_profile text NOT NULL DEFAULT 'generic'` + CHECK, `garmin_type_id int`, `garmin_parent_type_id int`, `description text`, `start_local timestamp`, `utc_offset_min smallint`, `moving_duration_s real`, `avg_speed_mps real`, `lap_count smallint`, `garmin_training_load real`, `garmin_vo2max real`, `deleted_at timestamptz`, `deleted_reason text` + CHECK); `activity_type` entfällt. Indizes `ix_activity_user_start_live (user_id, start_at DESC) WHERE deleted_at IS NULL`, `ix_activity_user_profile_start (user_id, sport_profile, start_at DESC)`.
- `def sport_profile_for(type_key: str | None, parent_type_id: int | None) -> str` — Tabelle aus A.1, Elterntypen über `tests/fixtures/garmin/activity_types.json` → als Paketdaten `src/kairos/connectors/garmin/activity_types.json` kopiert (Laufzeit darf nicht aus `tests/` lesen).
- Normalizer liefert zusätzlich alle neuen Felder; `utc_offset_min = round((startTimeLocal − startTimeGMT)/60 s)`; fehlt `startTimeLocal` → beide `None`.
- Upsert: `set_` = alle fachlichen Spalten inkl. `start_at`, `end_at`, `start_local`, `raw_payload_id`; `deleted_at = NULL`, `deleted_reason = NULL`; ausgenommen `id`, `user_id`, `external_id`, `created_at`, `fit_payload_id`.

- [ ] **Step 1: Failing tests:** alle 9 real vorkommenden `typeKey`s ohne Fallback korrekt (`treadmill_running→running`, `lap_swimming→swimming`, `hiking→hiking`, `strength_training/hiit/breathwork/resort_skiing→generic`, `cycling→cycling`); unbekannter Key mit Elterntyp running → `running`; Fixture-Normalisierung (Werte, Offset +120 im Sommer, +60 im Winter); Upsert ändert `start_at`; als gelöscht markierte Aktivität wird durch Upsert reaktiviert.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(activities): sport profile, local start, summary fields, full upsert`.

### Task 11: Lösch-Abgleich und gelöschte Aktivitäten ausblenden

**Files:**
- Create: `src/kairos/activities/reconcile.py`
- Modify: `src/kairos/routers/sync.py` (Hook für `activity_list`), `src/kairos/repositories/metrics_recompute.py`, `metrics_data.py`, `data_read.py`
- Test: `tests/test_activity_reconcile_integration.py`

**Interfaces:**
- `async def reconcile_deleted_activities(session, *, user_id, window: Window, payload: JSONValue) -> list[int]` — nur wenn `payload` eine Liste ist (eine Exception im Fetch erreicht den Hook nie). Lokale Tage = `window.start.date()` und `window.end.date()` (beide inklusive, AP 0 #8). Kandidaten: `deleted_at IS NULL`, `start_local::date` in diesen Tagen (Aktivitäten ohne `start_local` werden nie angefasst), `external_id` nicht in der Antwort → `deleted_at = now()`, `deleted_reason='garmin_sync'`. Rückgabe: IDs → Recompute der betroffenen Tage (Aufrufer).
- Alle Leser filtern `deleted_at IS NULL`: HF-Buckets, `list_activities`, `get_activity_detail` (404), Max-HF für den A.6-Hinweis.

- [ ] **Step 1: Failing tests:** Aktivität fehlt in Antwort → markiert; Aktivität außerhalb der beiden Tage → unberührt; Payload `{"error": …}` oder `None` → nichts markiert; Lauf 00:30 lokal am Tag `d+1` (UTC Tag `d`) wird über das lokale Datum gefunden; gelöschte Aktivität fehlt in `hr_bucket_seconds_daily` nach Recompute.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(activities): reconcile activities deleted in Garmin`.

### Task 12: Tagesgrenzen nach Ortszeit

**Files:**
- Modify: `src/kairos/repositories/metrics_recompute.py`, `src/kairos/repositories/metrics_data.py` (`sleep_hours_range`)
- Test: `tests/test_metrics_local_days_integration.py`

**Interfaces:**
- HF-Buckets: Tag = `activity.start_local::date` (Fallback `(activity.start_at AT TIME ZONE app_user.home_timezone)::date`, wenn `start_local` NULL); eine Aktivität über Mitternacht zählt ganz zum Starttag.
- Wellness: `(observed_at AT TIME ZONE u.home_timezone)::date` mit `JOIN app_user u`.
- Schlaf (`sleep_hours_range`): `(start_at AT TIME ZONE u.home_timezone)::date` (gleiche Regel; Aufwachtag bleibt offen, A.8).
- Kein `AT TIME ZONE 'UTC'` mehr in `src/` (Test per `grep` im Test: `Path("src").rglob("*.py")`).

- [ ] **Step 1: Failing tests:** Lauf 00:30 Ortszeit (22:30 UTC Vortag) → `hr_bucket_seconds_daily.day` = lokaler Tag; Lauf 23:30–00:30 lokal → alles am Starttag; Wellness-Sample 23:30 UTC im Sommer → nächster lokaler Tag; Nutzer mit `home_timezone='UTC'` → unverändert; grep-Test.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(metrics): cut days by local time instead of UTC`.

### Task 13: `GET/PUT /api/settings/profile` und Einstellungsseite

**Files:**
- Create: `src/kairos/routers/settings_profile.py`, `web/src/routes/settings/+page.server.ts`, `web/src/routes/settings/+page.svelte`
- Modify: `src/kairos/api.py`, `src/kairos/repositories/user_setting.py` (`upsert_profile`), Navigation (`web/src/routes/+layout.svelte`, Konto-Dropdown), `src/kairos/metrics/hr_zones.py` (neue reine Funktion `resolve_hr_max`, noch **nicht** von den Varianten genutzt)
- Test: `tests/test_settings_profile_router.py`, `web/tests/settings.test.ts`

**Interfaces:**
- `GET /api/settings/profile` → `{"birth_date": "YYYY-MM-DD"|null, "hr_max_override": int|null, "resting_hr_override": int|null, "hr_max_used": int|null, "hr_max_source": "eingetragen"|"aus Alter"|null, "hr_max_measured_12m": int|null, "hr_max_warning": str|null}`.
- `PUT` Body: `birth_date` (Vergangenheit, ≥ 1900), `hr_max_override` 120–230, `resting_hr_override` 30–100 (Q6); jedes Feld `null` = löschen; 422 bei Verstoß. Upsert in `user_setting` (Zeile ggf. anlegen).
- `def resolve_hr_max(birth_date, hr_max_override, *, as_of) -> tuple[int | None, Literal["eingetragen", "aus Alter"] | None]`.
- Hinweis: `max(activity.max_hr)` der letzten 12 Monate (nicht gelöscht) > verwendete HFmax → `"gemessen 219 bpm, eingetragen 214 – prüfen"`.
- Seite fragt ausdrücklich nach dem gemessenen HFmax-Wert, erklärt, dass 220 − Alter stark streut, zeigt verwendete HFmax + Herkunft + Hinweis.

- [ ] **Step 1: Failing tests:** GET ohne Zeile → alles `null`; PUT 214 → GET `hr_max_used=214`, Quelle „eingetragen“; PUT 250 → 422; nur Geburtsdatum → 220 − Alter, Quelle „aus Alter“; Hinweis bei gemessenem 219; RLS: Nutzer B sieht A nicht. Frontend-Test: Formular rendert Werte und zeigt Hinweis.
- [ ] **Step 2–4:** FAIL → implementieren → grün; `npm run check`, `npm run test:unit`, `eslint`.
- [ ] **Step 5:** Commit `feat(settings): profile settings API and page for HRmax, birth date, resting HR`.
- [ ] **Step 6: ⏸ H3.** Backend/Frontend neu starten, Max Bescheid geben: „Bitte jetzt unter Einstellungen HFmax 214 eintragen.“ Task 14 geht erst live, wenn `user_setting.hr_max_override = 214` für Max in der DB steht (Prüfung per SQL).

### Task 14: Neue HFmax-Regel

**Files:**
- Modify: `src/kairos/metrics/hr_zones.py` (`estimate_hr_max` → entfernt, Aufrufer nutzen `resolve_hr_max`), `src/kairos/metrics/variants/{edwards_trimp,banister_trimp,hr_zone_distribution}_variant.py`, `src/kairos/repositories/metrics_data.py` (`observed_max_hr_ever` entfernt bzw. nur noch für den Hinweis mit 12-Monats-Fenster), `src/kairos/agent/situation_brief.py` (Hinweiszeile, falls Warnung)
- Test: `tests/test_hr_zones.py`, `tests/test_metrics_variants_integration.py`, `tests/test_situation_brief.py`

**Interfaces:**
- Ohne HFmax: Varianten liefern `value=None`, `confidence="insufficient_data"` und `note="HFmax fehlt – bitte in den Einstellungen eintragen"` (neues optionales Feld `MetricResult.note: str | None = None`).
- Lagebild: bei Warnung eine Zeile „HFmax: gemessen 219 bpm, eingetragen 214 – prüfen“; bei fehlender HFmax „HFmax fehlt (Einstellungen)“.

- [ ] **Step 1: Failing tests:** Override 214 + gemessen 219 → 214 (früher 219); nur Geburtsdatum → 220 − Alter, auch wenn gemessen höher; nichts → `None` + Hinweis; Edwards-TRIMP mit Override identisch zu vorher bei gleicher HFmax.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(metrics)!: HRmax from user input or age, never from measured max`.

### Task 15: Betrieb 1c — Reprocess, Recompute, Abnahme

- [ ] **Step 1:** Migrationen anwenden (kein Job aktiv), Backend neu starten.
- [ ] **Step 2:** Reprocess ohne Garmin über die gesamte Historie → neue Spalten in allen 139 Aktivitäten; SQL-Prüfung: `sport_profile` aller 9 `sport`-Werte wie erwartet, `start_local` gefüllt.
- [ ] **Step 3:** Vorher-Snapshot: `hr_bucket_seconds_daily`, `wellness_daily_stats`, `metric_daily_value` (TRIMP Edwards, CTL/ATL) für die Historie in eine Scratch-Datei exportieren.
- [ ] **Step 4: ⏸ H4.** Recompute für 7 Tage (die letzten 7, plus der eine Tag mit Aktivität vor 2 Uhr Ortszeit, falls nicht darin) in einer Transaktion, Ergebnis lesen, **zurückrollen**; Tabelle vorher/nachher zeigen. **Auf OK warten.**
- [ ] **Step 5:** Recompute der gesamten Historie; Vergleich: TRIMP unverändert außer an Tagen mit Aktivitäten zwischen 0 und 2 Uhr Ortszeit (Liste der abweichenden Tage + Begründung).
- [ ] **Step 6:** Abnahme 1c dokumentieren (9 `typeKey`s, Abgleich-Test, 00:30-Test, TRIMP-Vergleich). Commit `chore(activities): 1c acceptance`.

---

## AP 2 — Abgeleitete Daten (Teil B)

### Task 16: Migration der vier Tabellen

**Files:**
- Create: `alembic/versions/<rev>_activity_derived_tables.py`
- Modify: `src/kairos/db/models.py` (`ActivityStats`, `ActivitySplit`, `ActivityBestEffort`, `ActivityStepResult`)
- Test: `tests/test_activity_derived_schema_integration.py`

**Interfaces:** Spalten exakt wie B.2, B.3, B.4, B.6 (inkl. CHECKs `quality`, `distance_source`, `kind`, `target_source`), alle `user_id` mit FK auf `app_user`, RLS forced, `ON DELETE CASCADE` von `activity`.

- [ ] **Step 1: Failing tests:** Tabellen + RLS + Cascade; CHECK lehnt `quality='bad'` ab.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(db): derived activity tables (stats, splits, best efforts, step results)`.

### Task 17: Gemeinsame Rechenregeln (B.1)

**Files:**
- Create: `src/kairos/activities/derive/__init__.py`, `src/kairos/activities/derive/common.py`
- Test: `tests/test_derive_common.py`

**Interfaces:**
```python
ACTIVITY_DERIVED_ALGO_VERSION = 1
@dataclass(frozen=True)
class Prepared:            # Eingabe aller Ableitungen
    t: list[float]         # Offsets in s
    weights: list[float]   # Abstand zum nächsten Sample, gedeckelt 10 s, 0 in Pausen
    moving: list[bool]     # False in Pausen
    timer_t: list[float]   # kumulative Timer-Zeit (Pausen ausgenommen)
    distance: list[float | None]   # kumulativ, negative Sprünge auf 0 geklemmt
    hr: list[float | None]         # < 25 / > 230 → None
    altitude_smooth: list[float | None]  # gleitender Median 5
    cadence_spm_or_rpm: list[float | None]
    power: list[float | None]
    gps_coverage_pct: float; hr_coverage_pct: float
def prepare(stream: LoadedStream, *, sport_profile: str, events: Sequence[Mapping], ) -> Prepared
def pause_intervals(t, distance, events) -> list[tuple[float, float]]  # timer stop/start aus event_mesgs, sonst Lücke > 10 s und v < 0,3 m/s
def weighted_mean(values, weights) -> float | None
def weighted_median(values, weights) -> float | None
def elevation_gain_loss(alt_smooth, hysteresis_m=2.0) -> tuple[float, float]
def distance_source(*, sport_profile, sub_sport, gps_coverage_pct, has_distance) -> str
def max_speed_10s(timer_t, distance) -> float | None   # gleitendes 10-s-Fenster
def interpolate_time_at_distance(timer_t, distance, target_m) -> float | None
```
Kadenz: Laufen × 2 (spm), Rad unverändert (rpm).

- [ ] **Step 1: Failing tests:** Gewichte mit Lücke 30 s → 10; Pause aus Events (timer stop 60 s) zählt nicht zur Timer-Zeit; Altbestand ohne Events: Lücke 20 s bei 0 m Distanzzuwachs → Pause, Lücke 20 s bei 50 m → keine Pause; Hysterese: Rauschen ±1 m → 0 Hm, Stufe +5 m → 5 Hm; negativer Distanzsprung → geklemmt; HF 240 → ignoriert; Distanzquelle für Laufband (`sub_sport='treadmill'`) → `watch_estimate`, Beckenschwimmen → `pool`, GPS 95 % → `gps`, GPS 70 % → `mixed`, ohne Distanz → `none`; Interpolation exakt in der Mitte zweier Samples.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): shared calculation rules for activity derivations`.

### Task 18: `activity_stats` inkl. Entkopplung und `sport_metrics`

**Files:**
- Create: `src/kairos/activities/derive/stats.py`, `tests/fixtures/activities/` (Q5, 4 Dateien + `README.md` zur Anonymisierung), `scripts/export_activity_fixture.py`
- Test: `tests/test_derive_stats.py`

**Interfaces:**
- `def compute_stats(prep: Prepared, *, activity: ActivitySummary, sessions, laps, lengths, splits: list[SplitRow], hr_max: int | None) -> StatsRow` — `StatsRow` hat genau die Spalten aus B.2. `ActivitySummary` = schmale Dataclass aus `activity` (Profil, `moving_duration_s`, Summary-Werte für den Fallback „Ohne Sekundendaten“).
- Pydantic-Modelle `CyclingMetrics`, `SwimmingMetrics`, `HikingMetrics` für `sport_metrics`.
- Zonen über `percent_max_zones(hr_max)` → `hr_zone_s`; ohne HFmax `hr_zone_s=None`, `trimp_edwards=None`.
- TRIMP: `edwards_trimp` über die HF-Reihe der Aktivität (zeitgewichtet in 5-bpm-Buckets, dieselbe Funktion wie die Tageslast).
- Entkopplung B.2 (erste 10 min verwerfen, Rest ≥ 40 min, `pace_cv_pct ≤ 8`, `EF = v/HF`, Hälften nach Zeit); Gründe als feste Texte („Intervalltraining – nicht anwendbar“, „zu kurz für Entkopplung (< 50 min)“, „ohne HF nicht berechenbar“).
- Laufleistung: `power_*` gesetzt, Hinweis entsteht im Tool (C.2), nicht hier.

- [ ] **Step 1: Failing tests:** synthetische Reihe 60 min konstant 5:00/km, HF 140 → Entkopplung ≈ 0; HF-Drift 140→150 in 2. Hälfte → positiver Wert; 30-min-Lauf → `NULL` + „zu kurz“; Ø-HF zeitgewichtet bei ungleichen Abständen; ohne Stream → `quality='partial'` aus Summary; Fixture-Lauf: Ø-HF ±1 gegen `activity.avg_hr` (V6), Ø-Kadenz ±2 spm gegen `averageRunCadence` (V5); Schwimm-Fixture → `quality='partial'`, `sport_metrics.pool_length_m` gesetzt.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): activity stats with decoupling and sport metrics`.

### Task 19: `activity_split` (Distanz und Runden)

**Files:**
- Create: `src/kairos/activities/derive/splits.py`
- Test: `tests/test_derive_splits.py`

**Interfaces:**
- `def distance_splits(prep, *, sport_profile, lengths) -> list[SplitRow]` — Splitlänge 1 km (running/hiking), 5 km (cycling), 100 m (swimming, nur mit `length_mesgs`), generic keine; Zeit an der Marke linear interpoliert; letzter Teil-Split ab 100 m / 1 km / 25 m mit `is_partial=True`.
- `def lap_splits(prep, *, laps) -> list[SplitRow]` — eine Zeile je `lap_mesg` mit `lap_intensity`, `lap_trigger`, `wkt_step_index`, Werte über das Zeitfenster der Runde aus den Arrays (Pace aus Distanz/Zeit, D11).
- `def pace_cv_pct(splits) -> float | None`, schnellster/langsamster nur volle Splits.

- [ ] **Step 1: Failing tests:** 8,02 km → 8 volle Splits, kein Teil-Split (20 m < 100 m); 8,37 km → Teil-Split `is_partial`; Interpolation: Marke zwischen zwei Samples; Pause innerhalb eines km zählt nicht; Rad 23 km → 4 × 5 km + Teil-Split 3 km; Fixture Auto-Lap-Lauf: km-Splits gegen Runden ≤ 1 s in ≥ 95 % (V1).
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): distance and lap splits`.

### Task 20: `activity_best_effort`

**Files:**
- Create: `src/kairos/activities/derive/best_efforts.py`
- Test: `tests/test_derive_best_efforts.py`

**Interfaces:**
- `BEST_EFFORT_DISTANCES: dict[str, float]` = 800, 1500, 3000, 5000, 10000, 21097.5, 42195, 50000, 100000.
- `def best_efforts(prep, *, sport_profile, distance_source) -> list[BestEffortRow]` — nur `running` + `gps`; Zwei-Zeiger über (Timer-Zeit, Distanz), Zieldistanz interpoliert, O(n) je Distanz; Fenster mit Schritt > 8,5 m/s verworfen; nicht als Pause erkannte Lücke > 10 s → `quality='partial'`.

- [ ] **Step 1: Failing tests:** konstante 4:00/km über 6 km → 5 km = 1.200 s; schnelles Stück km 2–3 in 3:30 → 1 km… (1500/800 korrekt verortet, `start_km`); GPS-Sprung 50 m in 1 s → Fenster verworfen; Laufband → keine Zeilen; 4,9 km Lauf → keine 5-km-Zeile; Fixture: 5 km gegen `fastestSplit_5000` ≤ max(2 s, 1 %) (V2).
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): running best efforts with two-pointer window`.

### Task 21: Soll/Ist pro Workout-Schritt (B.6)

**Files:**
- Create: `src/kairos/activities/derive/steps.py`
- Test: `tests/test_derive_steps.py` (Fixture Workout 272)

**Interfaces:**
- `def step_results(prep, *, workout_steps, laps, hr_targets: Mapping[int, tuple[float, float]] | None) -> list[StepResultRow]`
  - Ausführungen: aufeinanderfolgende Runden mit gleichem `wkt_step_index` = eine; neuer Durchlauf eines Wiederholungsblocks → nächste `repeat_iteration` (Zähler je Schritt-Index innerhalb des Repeat-Blocks aus `workout_step_mesgs` `duration_type='repeat_until_steps_cmplt'`, `duration_step` = Startindex); Runde ohne Index oder < 5 s → ignoriert.
  - Ziele: Pace/Speed (`custom_target_speed_low/high` bzw. `custom_target_value_*`, nach Wert sortiert), Kadenz, Leistung aus der FIT, `target_source='fit'`; HF: aus `hr_targets[step_index]` (`'api'`), sonst `'unclear'` (Q3: in AP 2 immer `None` übergeben).
  - Treffer nach Global Constraints; HF-Anteil zeitgewichtet aus `prep.hr`.
  - `planned_end` als Text (`time 360 s`, `distance 2000 m`, `lap_button`); `step_note` aus `notes`/`wkt_step_name`.
- [ ] **Step 1: Failing tests:** Fixture 272: Ausführungen = Schritte × Wiederholungen, Intervall über zwei Auto-Lap-Runden = eine Ausführung, Dauer = Summe der Runden ±1 s (V7); Pace-Ziel 4:35–4:45, Ø 4:39 → `hit=True`; Ø 4:52 (2,5 % langsamer als 4:45) → `False`; HF-Ziel ohne `hr_targets` → `target_source='unclear'`, `hit=None`; mit `hr_targets` und 85 % im Bereich → `True`, 64 % → `False`; Schritt 15 s → `hit=None`; Aktivität ohne `workout_mesgs` → `[]`.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): planned vs actual per workout step`.

### Task 22: Ableitungs-Service und Auslöser

**Files:**
- Create: `src/kairos/activities/derive/service.py`
- Modify: `src/kairos/activities/reprocess.py` (Schritt 3), `src/kairos/routers/sync.py` (nach `ingest_fit_files`; nach dem Lösch-Abgleich abgeleitete Zeilen löschen), `src/kairos/activities/reconcile.py`
- Test: `tests/test_derive_service_integration.py`

**Interfaces:**
- `async def derive_activity(session, *, user_id, activity_id) -> DeriveOutcome` — lädt Stream + FIT-Messages (`load_fit_messages`), HFmax (`resolve_hr_max`), rechnet, ersetzt alle vier Tabellen der Aktivität (delete + insert) in einem Savepoint; gelöschte Aktivität → nur löschen.
- `async def derive_pending(session, *, user_id, activity_ids: Sequence[int] | None = None) -> list[DeriveOutcome]` — ohne IDs: alle mit fehlender oder älterer `algo_version`.
- Auslöser: nach `activity_fit`-Commit für die berührten Aktivitäten; Reprocess; Lösch-Abgleich; `derive_pending` am Ende jedes Garmin-Syncs.

- [ ] **Step 1: Failing tests:** Ableitung schreibt alle vier Tabellen; zweimal → gleiche Zeilenzahlen; `algo_version` niedriger → wird neu gerechnet, gleich → übersprungen; gelöschte Aktivität → keine abgeleiteten Zeilen; Laufzeit für Fixture-Lauf < 200 ms ohne Dekodierung (Messung, kein harter Test-Fail unter CI-Last: Schwelle 1 s).
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(derive): derive service wired into sync, reprocess and deletion`.

### Task 23: Validierungsbericht V1–V7

**Files:**
- Create: `scripts/validate_activity_derivations.py`, `docs/validation/2026-10-xx-stufe1-ableitungen-v1-v7.md`

- [ ] **Step 1:** Skript: liest Max' Daten (nur DB), rechnet V1–V7 nach §12.3 (Garmin-Vergleichswerte aus den archivierten `activity_list`-Payloads: `fastestSplit_*`, `elevationGain`, `averageRunCadence`, PR-Werte aus der Spec), schreibt eine Markdown-Tabelle je Prüfung mit Quote, Kriterium, erfüllt ja/nein und Ausreißerliste.
- [ ] **Step 2:** `derive_pending` für alle 139, Laufzeit messen (Ziel < 2 min inkl. Dekodierung).
- [ ] **Step 3:** Bericht erzeugen, Abweichungen einzeln erklären (nicht wegdefinieren). Falls ein Kriterium verfehlt wird und die Ursache ein Rechenfehler ist → Fix in der betreffenden Task-Datei mit Regressionstest; ist es eine Datenfrage (z. B. GPS-Sprung) → im Bericht begründen. **⏸ H5**, falls ein Kriterium nicht erreichbar ist.
- [ ] **Step 4:** Commit `docs(validation): stufe 1 derivation report V1-V7`.

---

## AP 3 — Lese-Tools (Teil C)

### Task 24: Formatierung und Tool-Hülle

**Files:**
- Create: `src/kairos/agent/format.py`
- Modify: `src/kairos/agent/tools.py` (`_envelope` um `next`, `quality`, Spaltentabellen und Obergrenze)
- Test: `tests/test_agent_format.py`, `tests/test_agent_tools.py`

**Interfaces:**
```python
def fmt_distance(m: float) -> str            # "8,02 km"; < 1 km: "800 m"
def fmt_duration(s: float) -> str            # "41:30", "1:09:26"
def fmt_pace_km(s_per_km: float) -> str      # "5:10 /km"
def fmt_pace_100m(s_per_100m: float) -> str  # "2:05 /100 m"
def fmt_speed_kmh(kmh: float) -> str         # "28,4 km/h"
def fmt_datetime_local(dt: datetime, tz: str) -> str  # "Di 07.10.2026 07:12"
def fmt_date_short(dt, tz) -> str            # "Di 07.10. 07:12"
def fmt_diff(value: float, kind: Literal["pace","duration","distance","int"]) -> str  # "+0:25 /km", "−2,03 km", "−16"
def table(cols: list[str], rows: list[list[object]]) -> dict[str, object]
def cap_envelope(env: dict, *, max_tokens: int, shrink: Callable[[dict], dict | None]) -> dict
```
`cap_envelope`: misst `len(json.dumps(env, ensure_ascii=False)) / 3.7`; solange zu groß, ruft `shrink` (deterministisch, z. B. letzte Zeile weg) und setzt `meta.truncated=True`.

- [ ] **Step 1: Failing tests:** alle Formate aus C.0 inkl. Rundung (5:09,6 → „5:10 /km“), Minuszeichen U+2212, Sommer/Winterzeit im Datum; `cap_envelope` kürzt eine 200-Zeilen-Tabelle unter 600 Tokens und setzt `truncated`.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(agent): central formatting module and capped column tables`.

### Task 25: `activity_search` und `activity_get`

**Files:**
- Create: `src/kairos/agent/activity_tools.py`
- Modify: `src/kairos/agent/tools.py` (`CORE_TOOLS` += Specs)
- Test: `tests/test_agent_activity_tools_integration.py`

**Interfaces:** Schemas und Beschreibungen wörtlich aus C.1/C.2. Handler `activity_search_handler(session, *, user_id, from_date=None, to_date=None, sport_profile=None, name_contains=None, min_distance_km=None, max_distance_km=None, sort="newest", limit=10)`, `activity_get_handler(session, *, user_id, activity_id=None, sport_profile=None)`. Gelöschte unsichtbar; `fastest` ohne `sport_profile` → `ValueError` (geht als Fehler ans Modell); `meta.as_of` = `sync_state.last_success_at` für `activity_list`; `data.workout` aus `activity_step_result`; Profil-Abweichungen nach C.2-Tabelle; Laufleistung mit Hinweis „Handgelenk, eingeschränkt aussagekräftig“; Schwimmen mit HF-Hinweis; keine Kalorien (E12).

- [ ] **Step 1: Failing tests:** Seed mit 3 abgeleiteten Aktivitäten (aus Fixtures, Task 18): Suche newest/fastest/longest, Filter Distanz/Name; `activity_get()` ohne ID → letzte; `sport_profile="swimming"` → letzte Schwimmeinheit mit `/100 m` und Hinweis; gelöschte Aktivität nicht auffindbar; Workout-Aktivität → `data.workout` gefüllt, `meta.next` auf `kind="steps"`; Obergrenzen 600/700 eingehalten.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(agent): activity_search and activity_get tools`.

### Task 26: `activity_splits` und `activity_analyze`

**Files:**
- Modify: `src/kairos/agent/activity_tools.py`, `src/kairos/agent/tools.py`
- Test: `tests/test_agent_activity_tools_integration.py`

**Interfaces:** Schemas aus C.3/C.4. Spalten je Profil/Art exakt nach C.3-Tabelle; leere Spalten weglassen; Teil-Split als `"9 (0,37 km)"`; > 50 Zeilen ohne Bereich → Blöcke à 5 Splits, `truncated`, `meta.next` mit Bereichsbeispiel; `kind="steps"` ohne Workout → `ValueError`. `analyze`: `segment` (km **oder** Minuten, sonst Fehler), `compare` (gleiches Profil, sonst Fehler; Hinweis bei Distanzverhältnis > 1,5), `hr_drift` (Hälften, Einordnung < 5 / 5–10 / > 10 %), `curve` (≤ 60 Punkte, Pace je Bucket aus Distanz/Zeit, `y_unit` `s/km`).

- [ ] **Step 1: Failing tests:** km-Tabelle Fixture-Lauf (Spalten, `kum_zeit`); 100-km-Synthese → 20 Blöcke, `truncated`; Runden mit `typ` deutsch; `steps` für 272 (Ziel „4:35–4:45 /km“, `getroffen` ja/nein/–); `compare` Differenzen mit Vorzeichen; `curve` 60 Punkte; Lauf vs. Rad → Fehler; Obergrenzen 1.200/800.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(agent): activity_splits and activity_analyze tools`.

### Task 27: `best_efforts`, Systemprompt, Eval 17–21 und 26

**Files:**
- Modify: `src/kairos/agent/activity_tools.py`, `src/kairos/agent/tools.py`, `src/kairos/agent/prompt.py`, `scripts/agent_eval_suite.py`
- Test: `tests/test_agent_activity_tools_integration.py`, `tests/test_agent_prompt.py`, `tests/test_agent_tools.py` (Registry: 17 Tools, Schema-Summe < 18.000 Zeichen als Vorgriff auf G.3)

**Interfaces:** Schema aus C.5; Perioden `all/ytd/12m/90d/custom` in Heimatzeitzone; fehlende Distanzen mit `—` und Grund; `partial` gekennzeichnet. Prompt-Zeilen G.5 Punkt 1 und 2 (siehe Abweichungen). Eval: Fälle 17–21, 26 mit `expected_tools` aus §12.1; neue Prüfung `numbers_match`: alle Zahlen-Tokens aus `summary` des erwarteten Tools, die in der Antwort vorkommen sollen (Distanz, Pace, HF bzw. Zeit/Datum), erscheinen wörtlich in der Antwort; Option `--cases 17,18,19,20,21,26 --user-id <uuid>` (Q4) für Lesefälle gegen echte Daten, ohne Seed und ohne Schreibzugriff.

- [ ] **Step 1: Failing tests:** `best_efforts(["5k"], "ytd")` liefert die schnellste 5 km des Jahres mit Datum und Abschnitt; HM ohne Lauf → `—`; Prompt enthält die zwei Zeilen; Registry-Test.
- [ ] **Step 2–4:** FAIL → implementieren → grün.
- [ ] **Step 5:** Commit `feat(agent): best_efforts tool, prompt hints, eval cases 17-21 and 26`.
- [ ] **Step 6:** Eval live laufen lassen (`LLM_API_KEY` ist gesetzt): Fälle 17–21, 26 gegen Max' Daten, 1–16 gegen den Seed (Regression). Ergebnis (Tool-Accuracy, Zahlenprüfung, TTFT) in HANDOVER. **⏸ H5**, falls ein Fall dauerhaft scheitert.

---

## Abschluss

### Task 28: Doku

**Files:** `docs/HANDOVER.md`, `CLAUDE.md`, `docs/adr/ADR-0002-*.md`, `docs/01-architektur.md`, `docs/02-datenmodell-und-volumen.md`, `docs/07-deployment-und-betrieb.md`, `README.md`, Spec (Korrekturen mit Datum, Status AP 1a–3)

- [ ] HANDOVER: Stand Stufe 1 (AP 1a–3), Abweichungen, Runbook A.7 (aus Task 9), Migrationskette, Gotcha „Testcontainer-Image timescale“ und „TimescaleDB + RLS“ ersetzt durch Hinweis „kein TimescaleDB mehr“, Tech-Stack-Zeile DB, Liste der menschlichen Entwickler um `haenel@igmr.rwth-aachen.de` ergänzt.
- [ ] CLAUDE.md: Testzahl, Testcontainer-Image `postgres:16`, Timescale-Gotcha entfernen.
- [ ] AP 8, soweit 1a–1c: ADR-0002 (TimescaleDB entfernt), `01`, `02` (Speicherrechnung mit Arrays + FIT-Archiv), `07` (Images, SSD-Bedarf 40 GB), `README.md`.
- [ ] Commit `docs: stufe 1 data foundation and read tools`.
- [ ] Abschluss-Review des ganzen Branches (frischer Reviewer, stärkstes Modell; Lehre aus HANDOVER: Nahtstellen-Fehler), Funde beheben, dann Zusammenfassung an Max. Kein Push ohne OK.
