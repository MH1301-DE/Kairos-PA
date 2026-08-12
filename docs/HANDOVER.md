# Kairos-PA — Agent Handover Document

**Zweck:** Dieses Dokument wird von jedem neuen Coding Agent zu Beginn einer Session gelesen,  
um den vollständigen Projektkontext herzustellen. Es ersetzt kein git-Wissen — es ergänzt es.

---

## Curated Human Developers

Commits von diesen Personen stammen vom menschlichen Entwickler und müssen nicht als
Agent-Änderungen geprüft werden:

| Name | E-Mail |
|---|---|
| Maximilian Haenel | mhaenel@deloitte.de |
| Maximilian Haenel | max.haenel@t-online.de |

Commits von anderen Autoren sind Agent-Commits. Lies deren Diffs, bevor du weitermachst.

---

## Projektziel

**Kairos** ist ein persönlicher KI-Gesundheitsassistent für 1–5 Nutzer (kein SaaS-Produkt).  
Primärquelle: Garmin Connect (Fitness, Schlaf, HRV). Später: Google Calendar, Gmail.  
Der Agent soll Trainingslast erkennen, Erholung bewerten und Termine vorschlagen/schreiben.

**Aktueller Bearbeiter:** Maximilian Haenel (Betreiber = Nutzer 0)  
**Zielgruppe:** ~4 Freunde/Familie, gestaffelt nach Phase 6

---

## Tech Stack

| Schicht | Technologie |
|---|---|
| Backend | Python 3.14.6, FastAPI, SQLAlchemy[asyncio], asyncpg, Alembic |
| DB | PostgreSQL + TimescaleDB + pgvector |
| Cache/Sessions | Redis |
| Auth | Google OIDC (kein eigenes Passwort-Management) |
| Garmin-API | garminconnect 0.3.8, curl_cffi 0.16.0 (TLS-Fingerprint-Impersonation) |
| FIT-Decode | garmin-fit-sdk 21.212.0 |
| Verschlüsselung | AES-256-GCM (cryptography >=42), Envelope-Encryption |
| Linter/Typen | ruff, mypy (strict) |
| Tests | pytest + pytest-asyncio, testcontainers[postgres] |
| venv | `.venv/` mit Python 3.14.6, `pip` via `.venv/bin/python -m pip` |

---

## Kritisches Wissen: Garmin-Auth

### garth ist deprecated (März 2026)

Garmin hat `/mobile/api/login` global geblockt (HTTP 429 via Cloudflare).  
Wir nutzen **python-garminconnect >= 0.3.5** mit curl_cffi für TLS-Impersonation.

### Token-Flow

```
Erstanmeldung (einmalig):
  GarminConnectBackend.login(email, password) 
  → Garmin(email, password, return_on_mfa=True).login(tmpdir)
  → falls "needs_mfa": garmin.resume_login(state, mfa_code)
  → garmin.client.dump(tmpdir) → liest garmin_tokens.json
  → Token-JSON-String verschlüsselt in connection.credentials_enc

Danach automatisch:
  GarminConnectBackend.refresh_token(token_json)
  → Garmin().login(token_json)  # inline wenn len > 512 Zeichen
  → garmin.client.dump(tmpdir) → frischer Token zurück

Reauth erst nach Monaten (Refresh-Token abgelaufen):
  connection.status = 'reauth_required'
  connection.reauth_since = now()
```

### Wichtige garminconnect-Details

- `return_on_mfa=True` → login() gibt `("needs_mfa", state)` zurück, OHNE Token zu speichern
- Nach MFA-Resume IMMER `garmin.client.dump(tmpdir)` aufrufen
- `len(token_json) > 512` → garminconnect behandelt den String als Inline-Token-Daten
- garminconnect 0.3.x hat kein `.garth`-Attribut mehr

---

## Datenmodell (Kerntabellen)

### `connection` — zentrale Account-Verwaltung

```
user_id       → FK app_user
connector     = 'garmin' | 'google_calendar' | ...
external_account  z.B. Garmin-E-Mail
status        = 'active' | 'reauth_required' | 'disabled' | 'error'
credentials_enc  AES-256-GCM verschlüsselt mit DEK des Nutzers
token_refreshed_at  → für proaktive Reauth-Warnung
reauth_since    → seit wann im reauth_required-Status
```

### Aktivitäts-Speicher (3 Schichten)

```
Download (ZIP, ~125 KB)
  │
  ├─ raw_payload          gzip-JSON der decoded FIT-Messages (Archiv)
  ├─ activity (1 Zeile)   Name, Sport, Distanz, Dauer, ⌀HR, max HR, Höhenmeter, Kalorien
  └─ activity_record      Hypertable: 1 Zeile/Sekunde/Metrik
       recorded_at | metric     | value
       08:07:21    | hr         | 142.0
       08:07:21    | speed_mps  | 3.1
```

**Wichtig:** `activity_list` muss vor `activity_fit` laufen — `activity_record` braucht FK auf `activity.id`.

### FIT-Datei-Handling

```python
# ORIGINAL-Format liefert ZIP, keine rohe FIT-Datei
zip_bytes = garmin.download_activity(id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
# → in fit_decoder.py: _extract_fit() → ZipFile → erste .fit-Datei
# → garmin-fit-sdk: Decoder(Stream.from_byte_array(fit_bytes)).read() → (messages, errors)
# GPS-Koordinaten in Semicircles: degrees = val * 180.0 / 2_147_483_648
```

### Verschlüsselung (Envelope)

```
app_user.dek_wrapped = AES-GCM-Wrap(DEK, KEK)   # KEK aus Settings (KAIROS_KEK env var)
connection.credentials_enc = AES-GCM-Encrypt(token_json, DEK)
```

---

## Implementierter Code (Stand: 2026-08-05)

### Quellstruktur

```
src/kairos/
  api.py                          FastAPI-App (health, auth, sync)
  config.py                       Pydantic Settings
  auth/
    crypto.py                     AES-256-GCM wrap/unwrap/encrypt/decrypt
    deps.py                       current_user FastAPI-Dependency
    google.py                     Google OIDC Login/Callback
    session.py                    Redis-Session (create/get/delete)
  connectors/
    base.py                       Connector Protocol: fetch(kind,window), normalize(kind,payload), write_back()
    types.py                      Window, RawPayloadEnvelope, CanonicalRecord, WriteResult
    registry.py                   ConnectorRegistry
    garmin/
      client.py                   GarminConnectBackend + GarminClient (MFA-Retry-Layer)
      connector.py                GarminConnector — mappt kinds → garminconnect-API
      normalize.py                normalize_payload(kind, payload) für alle 10 Kinds
      fit_decoder.py              decode_fit_zip() + records_to_json()
  db/
    models.py                     SQLAlchemy ORM (alle Tabellen)
    rls.py                        install_rls_listener() — SET LOCAL per Transaktion
    session.py                    async_session_factory, get_session
  ingestion/
    hash.py                       payload_sha256()
    job_registry.py               SyncJobRegistry + SyncJob (asyncio.Lock per kind)
    service.py                    SyncService.run_backfill() + run_window()
  repositories/
    canonical.py                  SqlCanonicalRepository — schreibt in alle Ziel-Tabellen
    raw_payload.py                SqlRawPayloadRepository
    sync_state.py                 SqlSyncStateRepository
  routers/
    health.py                     GET /healthz
    sync.py                       POST /api/sync/garmin/backfill, GET /api/sync/status
```

### 10 Garmin Kinds (in Ausführungsreihenfolge)

```python
_ALL_KINDS = (
    "hr_intraday",    # get_heart_rates(date)
    "sleep",          # get_sleep_data(date)
    "stress",         # get_all_day_stress(date)
    "body_battery",   # get_body_battery(start, end)
    "hrv",            # get_hrv_data(date)
    "respiration",    # get_respiration_data(date)
    "spo2",           # get_pulse_ox_data(date)
    "daily_summary",  # get_stats(date)
    "activity_list",  # get_activities_by_date(start, end) → muss vor activity_fit laufen
    "activity_fit",   # download_activity(id, ORIGINAL) + decode_fit_zip()
)
```

### Metric Codes in metric_def (Seeds in Migration c4d2e3f5a6b7)

`hr`, `stress`, `body_battery`, `hrv_5min`, `respiration`, `spo2`, `cadence`, `speed_mps`, `power_w`, `altitude_m`, `lat_deg`, `lng_deg`, `temp_c`

### Sync-API

```
POST /api/sync/garmin/backfill
  Body: { "from_date": "2025-05-01",  # optional, default: -15 Monate
          "to_date": "2026-08-05",    # optional, default: heute
          "kinds": ["hr_intraday"]    # optional, default: alle 10
        }
  → 202 sofort, läuft als BackgroundTask
  → 409 wenn alle angeforderten Kinds bereits laufen

GET /api/sync/status
  → Job-Liste mit Status/Fortschritt
```

### Concurrency-Modell

```
asyncio.Lock per (user_id, connector, kind) in SyncJobRegistry
  - Zwei User: unabhängig, laufen parallel
  - Gleicher User, gleiche Kind: zweite Anfrage → 409
  - Gleicher User, verschiedene Kinds: laufen sequenziell (Rate-Limit-Schutz)

connector.fetch() läuft via asyncio.to_thread() → blockiert den Event Loop NICHT
Throttle: 2 s Delay zwischen Fenstern beim Backfill
```

---

## Alembic-Migrationskette

```
2d0beb5f2474  initial_schema
  └─ dd1f10a99d35  force_rls_on_tenant_tables
       └─ a7f9f3d1c2b4  phase1_garmin_tables
            └─ b3c1e2f4a5d6  connection_token_refresh_tracking
                 └─ c4d2e3f5a6b7  activity_fields_metric_seeds
                      └─ 6bf30be597a0  hypertables_wellness_activity_record
                           └─ f67b0560a2ad  user_setting
                                └─ 339358b313ef  metrics_raw_tables  ← HEAD
```

**Wichtig:** `6bf30be597a0` enthält **keine** Compression Policy mehr — TimescaleDB kann
Columnstore-Compression nicht auf Tabellen mit Row-Level-Security aktivieren (permanente
Timescale-Einschränkung, siehe timescale/timescaledb#6827). Aus demselben Grund sind
`hr_bucket_seconds_daily`/`wellness_daily_stats` (Migration `339358b313ef`) **normale**
Postgres-Tabellen, keine Timescale Continuous Aggregates (timescale/timescaledb#5787) —
gepflegt durch `src/kairos/repositories/metrics_recompute.py`, nicht durch eine
Timescale-Refresh-Policy.

---

## Tests

```bash
# Alle Tests — Windows-venv: .venv/Scripts/python (nicht .venv/bin/)
.venv/Scripts/python -m pytest -q

# main-Branch-Baseline (Stand nach Metrics-Backend-Merge, 2026-08-11): 98 passed, 0 skipped
# mit laufendem Docker durchgehend. Ohne Docker sind die Docker-gated Tests skipped (siehe
# tests/test_metrics_recompute_integration.py, tests/test_metrics_repositories_integration.py,
# tests/test_metrics_variants_integration.py, tests/test_garmin_repositories_integration.py)
# Skipped = testcontainers-Tests ohne laufenden Docker (POSTGRES_IMAGE ist jetzt
# timescale/timescaledb:latest-pg16, nicht mehr reines postgres:16 — nötig seit den
# TimescaleDB-Migrationen)

# Wichtige Test-Dateien
tests/test_garminconnect_backend.py   # GarminConnectBackend (15 Tests)
tests/test_garmin_auth_flow.py        # GarminClient MFA-Retry-Layer (11 Tests)
tests/test_garmin_normalize.py        # normalize_payload für hr + sleep
tests/test_connector_contract.py      # Connector-Protocol-Konformität
tests/test_sync_service.py            # SyncService (mock Repos)
tests/test_backfill_cursor.py         # run_backfill Cursor-Logik
tests/test_garmin_repositories_integration.py  # DB-Integration (benötigt Docker)
tests/test_metrics_*.py                # Phase-2 Metrics-Backend (siehe unten)
```

### Smoke-Test (reales Garmin-Konto)

```bash
.venv/bin/python scripts/garmin_smoke_test.py
# Token-Wiederverwendung aus garmin_tokens_smoke.json (steht in .gitignore)
```

---

## Phase-Status (Roadmap aus docs/08-roadmap.md)

| Phase | Status |
|---|---|
| Phase 0 — Fundament | ✅ `v0.0.1-phase0` getaggt |
| Phase 1 — Garmin-Pipeline | ~90% — API-Endpoint ✅, Hypertables ✅ (RLS-kompatibel, ohne Compression), Quality-Flag fehlt, echter Backfill-Lauf ausstehend |
| Phase 2 — Kennzahlen & Dashboard | ✅ beide Teilpläne (Metrics-Backend, Dashboard-Frontend) auf `main` gemergt und gepusht (siehe unten) — nur echte Google-OAuth-Credentials + Produktions-Deployment-Topologie fehlen noch für einen vollen Live-Test |
| Phase 3 — Kalender | ❌ nicht gestartet |
| Phase 4 — Agent | ❌ nicht gestartet |

### Was für Phase-1-Abnahme noch fehlt

1. ~~Hypertables + Compression Policies~~ — ✅ erledigt (`6bf30be597a0`, Compression aus RLS-Gründen entfernt, siehe Migrationskette oben)
2. **Quality-Flag** — Plausibilitätsprüfung im Normalizer (HR < 25 oder > 230 → `suspect`)
3. **Echter Backfill-Lauf** — 12 Monate importieren, Stichprobenvergleich mit Garmin Connect

### Phase 2 — Fortschritt (Stand 2026-08-12)

Phase 2 wurde in zwei unabhängige Pläne aufgeteilt, um nicht auf der Frontend-Framework-
Entscheidung zu blockieren:

1. **Metrics-Backend** — ✅ **fertig, alle 15 Tasks + finales Whole-Branch-Review +
   Fix-Welle + Re-Review + ein Restfund gemergt nach `main`** (Commit `04d6744`, Branch
   `phase-2-metrics-backend` nach Merge gelöscht). Plan-Dokument (als Referenz erhalten):
   `docs/superpowers/plans/2026-08-10-phase-2-metrics-backend.md`.
   - Architektur: zwei plain RLS-Tabellen (`hr_bucket_seconds_daily`, `wellness_daily_stats`)
     statt Timescale Continuous Aggregates (RLS-inkompatibel, siehe Migrationskette),
     befüllt durch `src/kairos/repositories/metrics_recompute.py`. Formeln laufen als reine
     Python-Funktionen zur Abfragezeit (`src/kairos/metrics/formulas/`), registriert in einer
     `MetricRegistry` (`src/kairos/metrics/registry.py`, Muster wie `ConnectorRegistry`).
     Nutzer können zwischen TRIMP-Varianten (Edwards/Banister) wählen; CTL/ATL/TSB/ACWR/
     Monotonie-Strain nutzen aber **immer** Edwards-TRIMP als kanonische Trainingslast
     (Entscheidung vom 2026-08-10, verhindert Sprünge in der Langzeitkurve).
   - **Wichtige Lektion aus dem finalen Whole-Branch-Review:** Die einzelnen Task-Reviews
     (Diff gegen Brief) fanden keine Fehler, aber das abschließende Review auf dem
     leistungsfähigsten Modell deckte zwei echte, durch Codeausführung bewiesene Bugs auf,
     die genau an der **Nahtstelle zwischen zwei einzeln korrekten Tasks** lagen:
     `edwards_daily_load_series()` lieferte eine **sparse** Tagesreihe (nur Tage mit echten
     Trainingsdaten). Dadurch blieben CTL/ATL/TSB am letzten Trainingstag stehen (ATL sank
     nie ab, TSB kam vorzeichenverkehrt raus), und Foster-Monotonie/-Strain lieferte für
     jeden realistischen Trainingsplan mit Ruhetagen `None`. Fix: dichte (nullgefüllte)
     Tagesreihe + separater Zähler für Tage mit echten Daten — ACWR musste dabei explizit
     gegen dieses Muster abgesichert werden, sonst hätte die Umstellung dessen
     Unzureichende-Daten-Erkennung für neue Nutzer stillschweigend kaputt gemacht. Ein
     Nachzügler-Fund (`training_load` verlor sein `insufficient_data`-Gate für Nutzer ganz
     ohne Trainingsdaten) kam erst im Re-Review ans Licht und wurde in einer dritten,
     minimalen Runde geschlossen. **Lehre:** Bei mehrteiligen Plänen mit vielen kleinen,
     einzeln reviewten Tasks das abschließende Whole-Branch-Review nicht überspringen —
     genau dort tauchen Kompositionsfehler auf, die kein Einzel-Review sieht.
   - Zusätzlich behoben: fehlende ORM-Modelle für die zwei neuen Tabellen (hätte beim
     nächsten `alembic revision --autogenerate` zum Löschvorschlag geführt), ein
     `::date`-Cast-Verstoß in `sleep_debt_variant.py` (jetzt über
     `metrics_data.sleep_hours_range()`, UTC-determinsitisch), sowie ein Ruhepuls-Fallback
     für Banister-TRIMP/Karvonen-Zonen (beobachtetes Tages-Minimum als Ersatz, solange es
     keine `user_setting`-Schreib-API gibt).
   - **Bekannte, bewusst offene Restpunkte** (nicht blockierend, für später vermerkt):
     `WellnessSample`/`ActivityRecord`-Modelle kennen die von Timescale automatisch
     angelegten Hypertable-Indizes nicht — nächstes `autogenerate` würde deren Löschung
     vorschlagen (vorbestehend, nicht durch Phase-2-Arbeit verursacht); uneinheitliche
     Confidence-Abstufung zwischen Varianten (manche hart auf `"high"`, andere abgestuft);
     `sleep_debt_variant.py` u.ä. sind nur teilweise End-to-End getestet.
2. **Dashboard-Frontend** — ✅ **fertig, alle 14 Tasks + finales Whole-Branch-Review +
   Fix-Welle (2 parallele Agenten, Backend/Frontend getrennt) + Re-Review gemergt nach
   `main` und gepusht** (Commit `aa88219`, Branch `phase-2-dashboard-frontend` nach Merge
   gelöscht, SDD-Workspace aufgeräumt). **Autonome Session** (Nutzer zeitweise nicht
   verfügbar, volle Entscheidungsfreigabe für alle 14 Tasks + Review-Zyklus).
   Framework-Entscheidung: **SvelteKit** (statt Next.js) + ECharts, entschieden am
   2026-08-10 (PWA/Web-Push-Reife wichtiger als React-Grid-Layout-Ökosystem für dieses
   Projekt). Plan-Dokument (als Referenz erhalten):
   `docs/superpowers/plans/2026-08-11-dashboard-frontend.md`.

   Kein einziger formaler Task-Fix-Loop über alle 14 Tasks nötig — aber das finale
   Whole-Branch-Review (opus) fand trotzdem 1 Critical + 9 Important, ausschließlich
   Kompositionsfehler zwischen einzeln korrekten Tasks, die kein Einzel-Review sehen
   konnte (gleiche Lektion wie beim Metrics-Backend-Plan, siehe oben — bestätigt sich
   zum zweiten Mal in Folge):
   - **Critical:** PWA-Plugin generierte Manifest/Service-Worker, aber nichts in der App
     hat sie verlinkt/registriert — nie installierbar, SW lief nie. Fix:
     `virtual:pwa-info`/`virtual:pwa-register` in `+layout.svelte` verdrahtet; beim
     Verifizieren einen ZWEITEN echten Bug gefunden (relative statt absolute
     Manifest/SW-URLs, 404 auf jeder Nicht-Root-Route) — behoben mit `base:'/'`+`scope:'/'`.
   - Ungültiges/abgelaufenes `session_id`-Cookie brachte die App ohne Rückweg zum
     Stillstand (Guard prüft nur Präsenz, Backend prüft Gültigkeit) — Fix: 401 gezielt
     abfangen und zu `/auth/login` redirecten.
   - `/auth/logout` gab rohes JSON zurück statt zu redirecten — Nutzer landete auf
     `{"ok":true}` ohne Rückweg.
   - Garmin-Passwort wurde beim MFA-Retry im Klartext ins DOM zurückgespiegelt (verstecktes
     Formularfeld) — Fix: Passwort wird nicht mehr zurückgegeben, Nutzer tippt es beim
     Retry neu ein.
   - Erneutes Onboarding mit anderem Garmin-Konto legte eine zweite aktive
     `connection`-Zeile an (Unique-Constraint ist `(user_id, connector, external_account)`,
     nicht `(user_id, connector)`) — `MultipleResultsFound` wurde von einem `bare except`
     verschluckt, Sync schlug danach dauerhaft und ohne Diagnose fehl. Fix (nur
     Anwendungsebene, keine Migration): alte Garmin-Zeilen vor dem Upsert deaktivieren
     (`is_distinct_from` für NULL-Sicherheit), Lesepfad tolerant gegen Altbestände
     (`order_by(connected_at.desc())`).
   - E2E-Test-Stub belegte Port 8000 fest — Kollision mit dem echten lokalen Backend.
     Fix: konfigurierbares `KAIROS_API_PROXY_TARGET`, Test-Stub auf Port 8791.
   - Das Ledger hatte fälschlich behauptet, es gäbe kein docker-compose — tatsächlich
     existiert `deploy/docker-compose.dev.yml` (nur Postgres+Redis, kein `web`/`caddy`).
     Dadurch wurden 4 Tasks' manuelle Verifikationsschritte übersprungen, am teuersten für
     den ungetesteten Logout-Fix.
   - `apiPost` parste JSON ungeschützt (Backend-Ausfall → Crash statt Fehlermeldung);
     Charts hatten kein Resize; mehrere Minor-Funde (echarts `^6` statt `^5`, `lang="en"`,
     GaugeTile Div-durch-Null-Risiko, u.a.).
   Alle Findings unabhängig im Re-Review bestätigt behoben (nicht nur den Fix-Reports
   vertraut) — inklusive Live-Verifikation der PWA-Fix gegen einen echten
   `npm run preview`-Server auf einer verschachtelten Route, nicht nur `/`.

   **Bewusst offen gelassen** (dokumentiert, nicht übersehen): Bestehende
   Garmin-Doppel-Zeilen in einer realen DB werden nicht automatisch repariert (kein
   Migrations-Versuch); `_build_garmin_client`s `bare except Exception` verschluckt
   weiterhin den echten Fehlertyp (nächster sinnvoller Folge-Fix: `logger.exception(...)`
   statt stillem `return None`); 401→Redirect-Fix hat keinen automatisierten Test (nur
   Code-Lesen + eine manuelle Live-Prüfung); **Produktions-Deployment (Caddyfile,
   `web/Dockerfile`, `api`-Dockerfile, `ORIGIN`-Env-Wiring) existiert noch nicht** —
   `deploy/docker-compose.yml` referenziert sie, aber die Dateien selbst fehlen. Braucht
   einen eigenen Folge-Task/Plan, bevor die Same-Origin-Cookie-Architektur produktiv
   getestet werden kann.

   Bemerkenswerte Funde während der einzelnen Task-Reviews (vor dem finalen Review,
   alle bereits damals behoben): eine SvelteKit-Serialisierungs-Falle (Funktionen können
   nicht über die server→client `load()`-Grenze), ein Svelte-`{#each}`-Duplicate-Key-Risiko
   bei
   Sync-Jobs (jetzt auf `job_id` statt `kind` geschlüsselt), ein echter
   Backend-Sicherheitsbug (`/auth/logout` invalidierte die Session serverseitig nie,
   da `session_id` implizit als Query-Parameter statt aus dem Cookie gelesen wurde —
   auf das etablierte `Cookie(default=None)`-Muster aus `deps.py` korrigiert), und ein
   grundlegend fehlerhafter E2E-Mocking-Ansatz (`page.route()` kann serverseitig
   ausgelöste Fetches aus einer SvelteKit-Form-Action nicht abfangen — durch einen
   `node:http`-Stub-Server auf Port 8000 ersetzt).

   Design-Korrekturen gegenüber dem ursprünglichen Spec-Dokument (autonom entschieden,
   siehe Plan-Global-Constraints): `training_load`/`hrv_baseline` sind **keine** Liniendia-
   gramme (Backend liefert nur Tages-Snapshots, kein Zeitreihen-Endpoint) — `training_load`
   ist eine Multi-Stat-Value-Tile (CTL/ATL/TSB), `hrv_baseline` eine Gauge (heutiger Wert
   gegen Baseline-Band, gleiche Komponente wie ACWR). ECharts-Wrapper ist handgeschrieben
   (`EChartsBase.svelte`) statt der `svelte-echarts`-Fremdbibliothek (Svelte-5-Kompatibi-
   litätsrisiko vermieden).

   **Wiederkehrende technische Stolpersteine, gelöst und für spätere Tasks dokumentiert:**
   - Aktuelle SvelteKit-Toolchain (`sv create` v0.17.0) hat **kein** `svelte.config.js`
     mehr — Adapter/Preprocessor-Config liegt direkt in `vite.config.ts` als Optionen des
     `sveltekit()`-Plugin-Aufrufs.
   - `web/vite.config.ts`s "server"-Vitest-Projekt hatte anfangs `include: ['src/**/*...']`
     — Tests unter `web/tests/**` (wie vom Plan vorgesehen) wurden nicht gefunden. Fix
     (Task 4): `tests/**/*.{test,spec}.{js,ts}` zum Include hinzugefügt.
   - Komponenten-Tests mit `@testing-library/svelte` liefen unter `environment: 'node'`
     ins Leere (`document is not defined`). Fix (Task 6, empirisch verifiziert, nicht
     geraten): `environment: 'jsdom'` **plus** `resolve: { conditions: ['browser'] }` (sonst
     löst Vite Sveltes SSR-Build statt Client-Build auf) **plus** top-level `globals: true`
     (sonst registriert sich `@testing-library/svelte`s Auto-Cleanup nicht über
     `beforeEach`/`afterEach`). Alle drei zusammen nötig, einzeln nicht ausreichend.
   - `EChartsBase.svelte` crasht unter jsdom mit dem Standard-Canvas-Renderer
     (`TypeError: Cannot set properties of null (setting 'dpr')` — jsdom hat keinen echten
     2D-Canvas-Kontext, das `canvas`-npm-Paket ist nicht installiert). Fix (Task 7): optionaler
     `renderer?: 'canvas' | 'svg'`-Prop auf `EChartsBase` (Default `'canvas'`, abwärtskompa-
     tibel), `BarTile`/`GaugeTile` übergeben `renderer="svg"`. **Für jede künftige
     EChartsBase-Nutzung nötig** (in diesem Plan sind BarTile/GaugeTile die einzigen
     Verbraucher, aber Phase 3 o.ä. sollte das nicht neu entdecken müssen).
   - Node.js/npm-PATH-Reibung in der Bash-Tool-Session: `export PATH="/c/Program
     Files/nodejs:$PATH"` bleibt session-intern nötig (Shell-Prozess wird einmalig beim
     Session-Start initialisiert, `~/.bash_profile` wird von späteren Tool-Aufrufen
     innerhalb derselben Session nicht automatisch neu eingelesen). Statt des PATH-Fixes
     selbst wurde die **Freigabe-Reibung** behoben: Wildcard-Permission-Regeln in
     `.claude/settings.local.json` für den Export-Präfix sowie für die SDD-Helper-Skripte
     (`task-brief`/`review-package`/`sdd-workspace`) — vorher pro Task-Nummer/Commit-Hash-
     Paar einzeln freigegeben, jetzt eine Wildcard-Regel je Skript.

Minimum für User-Test (unverändert aus ursprünglicher Phase-2-Definition):
1. Onboarding-Seite: Garmin-E-Mail + Passwort → `connection` anlegen
2. Sync-Status-Seite: Fortschritt des Backfills
3. Ein einfacher Chart (Ruhepuls letzte 30 Tage)

---

## Wichtige Architektur-Entscheidungen (ADRs)

| ADR | Entscheidung | Begründung |
|---|---|---|
| ADR-0001 | Modularer Monolith | Kein Micro-Service-Overhead für 5 Nutzer |
| ADR-0002 | Eine Datenbank (Postgres+Timescale) | Kein verteiltes System nötig |
| ADR-0003 | Connector-Abstraktion | Garmin-Wechsel nur in einem Modul |
| ADR-0004 | garminconnect statt garth | garth deprecated März 2026 (Cloudflare-Block) |
| ADR-0005 | ECharts für Frontend | — |
| ADR-0006 | Google OIDC | Kein eigenes Passwort-/MFA-Management |

---

## Gotchas & Fallstricke

- **`return_on_mfa=True` in garminconnect**: Login gibt `("needs_mfa", state)` zurück, OHNE Token zu speichern — immer `garmin.client.dump(tmpdir)` danach aufrufen
- **FIT-Download = ZIP**: `ActivityDownloadFormat.ORIGINAL` liefert ein ZIP-Archiv, keine rohe .fit-Datei
- **Semicircle-GPS**: position_lat/position_long aus FIT-Decoder in Semicircles → Umrechnung: `° = val * 180 / 2_147_483_648`
- **metric_def-Seeds**: Müssen existieren bevor `wellness_sample`-Rows geschrieben werden (Migration c4d2e3f5a6b7)
- **activity_list vor activity_fit**: activity_record braucht FK auf activity.id
- **RLS + Background Tasks**: `install_rls_listener(session, user_id)` auf jeder Session aufrufen, die in RLS-geschützte Tabellen schreibt
- **Python 3.14**: Einzige verfügbare Version auf diesem Mac; `pyproject.toml` sagt `>=3.12`
- **hatchling**: Wird für `pip install -e ".[dev]"` benötigt — bei venv-Rebuild zuerst `pip install hatchling`
- **Windows-venv**: Unter Windows liegt der Interpreter unter `.venv/Scripts/python`, nicht
  `.venv/bin/python` (macOS-Konvention aus diesem Dokument). Auf einer Windows-Session mit
  Python 3.13 statt 3.14 getestet — funktioniert, da `pyproject.toml` nur `>=3.12` verlangt.
- **TimescaleDB + RLS sind für zwei Features inkompatibel**: (1) Columnstore-Compression
  kann nicht auf Tabellen mit RLS aktiviert werden (timescale/timescaledb#6827); (2)
  Continuous Aggregates können nicht auf RLS-Hypertables erstellt werden
  (timescale/timescaledb#5787). Beides sind dauerhafte Timescale-Einschränkungen, kein
  Versionsbug. Da RLS laut dieser Datei nicht verhandelbar ist: Compression einfach weglassen
  (Datenvolumen ist ohnehin trivial, siehe 02-datenmodell-und-volumen.md), Continuous
  Aggregates durch plain Tabellen + expliziten Python-Recompute ersetzen.
- **Testcontainer-Image**: `tests/conftest.py`s `POSTGRES_IMAGE` muss
  `timescale/timescaledb:latest-pg16` sein (nicht reines `postgres:16`), sonst schlägt
  `CREATE EXTENSION timescaledb` in den Migrationstests fehl.

---

## Laufende Infrastruktur

```bash
# Lokale Dev-Umgebung starten
docker compose up -d        # Postgres+Timescale, Redis

# Alembic-Migrationen anwenden
.venv/bin/alembic upgrade head

# API starten
.venv/bin/uvicorn kairos.api:app --reload
```

**Garmin-Tokens-Smoke-Test** (lokal, nicht committen):
```
garmin_tokens_smoke.json  # .gitignore — Token für Smoke-Tests
```
