# 01 — Architektur

> **Stand 2026-10-08.** Dieses Dokument beschreibt den Ist-Stand im Code. Nicht
> gebaute Teile des ursprünglichen Entwurfs sind als **Zielbild (nicht umgesetzt)**
> markiert.

## 1. Architekturprinzipien

Diese fünf Prinzipien entscheiden im Zweifel jede Detailfrage:

1. **Determinismus vor Intelligenz.** Alles, was berechenbar ist, wird berechnet.
   Das LLM interpretiert Ergebnisse, es erzeugt sie nicht.
2. **Eine Datenbank.** Postgres deckt Relationen und Zeitreihen (TimescaleDB) ab.
   Kein zweites Datensystem ohne zwingenden Grund. *Zielbild (nicht umgesetzt):*
   Vektoren über `pgvector` — die Extension ist heute nicht installiert.
3. **Die Integrationsgrenze ist ein Modul, nicht eine Funktion.** Jede externe
   Anbindung implementiert ein einheitliches `Connector`-Protocol und lebt in einem
   eigenen Package; kein externer Prozess nötig. *Zielbild (nicht umgesetzt):* ein
   Import-Linter in CI, der die Grenze erzwingt — heute gilt sie nur per Konvention.
4. **Der Kontext ist die knappste Ressource.** Jede Komponente, die etwas in den
   Agentenkontext schreibt, hat ein Token-Budget und hält es ein.
5. **Rohdaten sind unantastbar.** Was importiert wurde, wird nie überschrieben.
   Normalisierung ist eine Ableitung und jederzeit wiederholbar.

## 2. Systemkontext (C4 Level 1)

```
                 ┌───────────────────────────────────────────┐
   Nutzer (5) ──▶│                                           │
   PWA / Chat    │        Kairos  (eigene VM, HTTPS)         │
                 │                                           │
                 └───┬───────────┬───────────┬───────────┬───┘
                     │           │           │           │
                     ▼           ▼           ▼           ▼
                ┌────────┐ ┌──────────┐ ┌────────┐ ┌───────────────┐
                │ Garmin │ │  Google  │ │ Apple  │ │    LLM-API    │
                │Connect │ │ Calendar │ │CalDAV *│ │ (über litellm,│
                │        │ │          │ │        │ │ Anbieter frei)│
                └────────┘ └──────────┘ └────────┘ └───────────────┘
                  Pull     Pull + Write    Pull      Request/Resp

  * Apple CalDAV und Gmail: Zielbild (nicht umgesetzt).
```

**Vertrauensgrenzen:** Alles innerhalb der VM ist vertrauenswürdig. Alles außerhalb
ist nicht vertrauenswürdig — insbesondere Inhalte aus Gmail und Kalendereinladungen,
die als potenzielle Prompt-Injection behandelt werden ([06](06-sicherheit-und-datenschutz.md)).

## 3. Containerdiagramm (C4 Level 2)

**Ist-Stand:** `deploy/docker-compose.yml` enthält Caddy, Web (SvelteKit), API
(FastAPI), Postgres (TimescaleDB) und Redis. Syncs laufen als FastAPI-
`BackgroundTasks` im API-Prozess. Mit `*` markierte Teile sind **Zielbild (nicht
umgesetzt)**: kein Worker/Scheduler (kein `arq` in den Dependencies), kein Object
Store, kein CalDAV-Connector, kein Rate-Limit in Caddy, kein `pgvector`.

```
┌─────────────────────────────────────────────────────────────────────┐
│ VM (Docker Compose)                                                 │
│                                                                     │
│  ┌───────────┐                                                      │
│  │  Caddy    │  TLS-Terminierung, Reverse Proxy (Rate Limit *)      │
│  └─────┬─────┘                                                      │
│        │                                                            │
│  ┌─────▼──────────┐        ┌──────────────────┐                     │
│  │  Web (PWA)     │        │  Auth            │                     │
│  │  SvelteKit     │◀──────▶│  Google OIDC     │                     │
│  └─────┬──────────┘        └──────────────────┘                     │
│        │ REST / SSE                                                 │
│  ┌─────▼──────────────────────────────────────────┐                 │
│  │  API + Domain  (FastAPI, modularer Monolith)   │                 │
│  │  ┌──────────┬──────────┬──────────┬─────────┐  │                 │
│  │  │ identity │  health  │ calendar │planning │  │                 │
│  │  ├──────────┼──────────┼──────────┼─────────┤  │                 │
│  │  │ metrics  │  agent   │ registry │ modules │  │                 │
│  │  └──────────┴──────────┴──────────┴─────────┘  │                 │
│  └───┬───────────────────────────────────────────────┬──────┘         │
│      │  (Connector-Protocol, Import-Linter-Grenze)  │               │
│  ┌───▼──────────────────────────────────────┐  ┌────▼───────┐       │
│  │  kairos/connectors/                      │  │  Worker *  │       │
│  │  ┌──────────┬───────────┬─────────────┐  │  │ Scheduler *│ arq * │
│  │  │  garmin  │  google   │   caldav *  │  │  └────┬───────┘       │
│  │  └──────────┴───────────┴─────────────┘  │       │               │
│  └──────────────────────────────────────────┘       │               │
│                                            │                        │
│  ┌──────────────────────┐  ┌───────────────▼─────┐  ┌────────────┐  │
│  │ Postgres 16          │  │ Redis               │  │ Object     │  │
│  │ + TimescaleDB        │  │ Sessions,           │  │ Store *    │  │
│  │ (+ pgvector *)       │  │ OAuth-State         │  │ (FIT/Raw)  │  │
│  └──────────────────────┘  └─────────────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Warum modularer Monolith und nicht Microservices?

Bei 5 Nutzern und einem Betreiber sind verteilte Transaktionen, Service-Discovery
und N Deployment-Pipelines reiner Overhead. Die Modulgrenzen werden stattdessen
**im Code erzwungen** (eigene Packages, keine Cross-Imports außer über definierte
Service-Interfaces, Import-Linter in CI). Ein Modul lässt sich später
herausschneiden, wenn es je nötig wird. Siehe
[ADR-0001](adr/ADR-0001-modularer-monolith.md).

**Connectors** sind in-process Python-Module (`kairos/connectors/`), die das
`Connector`-Protocol implementieren. Keine eigenen Prozesse, kein Netzwerk-Hop.
Die Grenze ist eine Package-Konvention (ein Import-Linter ist Zielbild, siehe oben),
keine Prozessgrenze. `Connector.write_back()` ist für Garmin ein No-op und für Google
Calendar zwar implementiert, wird aber nirgends aufgerufen: Schreibzugriffe laufen
über Domänen-Funktionen (`routers/calendar.py`), die den Client direkt nutzen.
Begründung und Upgrade-Pfad: [ADR-0003](adr/ADR-0003-connector-architektur.md).

## 4. Schichten

### 4.1 Ingestion Layer

Zuständig für: Auth gegen externe Dienste, Abholen, Rate-Limiting, Retry,
Idempotenz, Ablage im Raw-Store.

```
POST /api/sync/garmin/backfill bzw. /google_calendar/sync (manuell)
              ──▶ SyncJob(user, connector, kind) als BackgroundTask
                  │
                  ├─▶ Connector.fetch()      → Raw-Payload
                  ├─▶ RawStore.put()          → unveränderlich, gzip
                  ├─▶ Connector.normalize()   → Canonical Records
                  └─▶ Repository.upsert()     → Postgres
```

Eigenschaften:
- **Watermark-basiert.** Pro (user, connector, datentyp) wird ein
  `last_synced_through` gehalten. Kein Vollabzug im Normalbetrieb.
- **Idempotent.** Jeder Record hat einen stabilen `external_id`; Upsert per
  `ON CONFLICT`.
- **Backfill** (Default 24 Monate) läuft tageweise rückwärts. Statt einer
  Prioritätsstufe gilt: ein Lock je (Nutzer, Connector, Kind)
  (`ingestion/job_registry.py`), 300 s Cooldown zwischen zwei Garmin-Backfill-
  Auslösungen und 1,5 s Pause zwischen Tagesfenstern.
- **Fehlerbehandlung — offen.** Die Tabelle `sync_failure` existiert, wird aber nie
  geschrieben: `SyncService` wird ohne `sync_failure_repo` gebaut
  (`routers/sync.py:221`). Es gibt keine automatische Wiederholung mit Backoff;
  ein fehlgeschlagenes Fenster wird nur geloggt und erst beim nächsten manuell
  ausgelösten Sync erneut versucht.

### 4.2 Storage Layer

Drei Zonen, klar getrennt:

| Zone | Inhalt | Mutabilität | Zweck |
|---|---|---|---|
| **Raw** | Original-API-Antworten als gzip-JSON (`raw_payload`). Keine FIT-Dateien: bei `activity_fit` nur die dekodierten Messages `record`, `session`, `lap` (laut [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) A.2 künftig zusätzlich `length`, `event`, `workout`, `workout_step`) | append-only | Wahrheit, Reprocessing |
| **Canonical** | Normalisierte Domänenobjekte | upsert | Abfragen, Joins |
| **Derived** | `wellness_daily_stats`, `hr_bucket_seconds_daily`, `metric_daily_value` (plain Tabellen, gepflegt von `repositories/metrics_recompute.py`) | rebuildbar | Performance, Agent-Antworten |

Die Derived-Zone ist **jederzeit vollständig aus Canonical rekonstruierbar**. Damit
ist ein Fehler in der Metrikberechnung kein Datenverlust, sondern ein Recompute.

### 4.3 Domain / Metrics Layer

Formeln sind reine Python-Funktionen (`src/kairos/metrics/formulas/`), registriert
in einer `MetricRegistry` (`src/kairos/metrics/registry.py`) und zur Abfragezeit
berechnet. CTL/ATL/TSB, ACWR und Monotonie/Strain nutzen **immer Edwards-TRIMP**
als kanonische Trainingslast; Banister ist nur eine wählbare TRIMP-Variante
(`MetricRegistry.default_variant()`: `trimp → edwards`).

Kennzahlen V1: TRIMP (Edwards kanonisch, Banister als Variante), CTL/ATL/TSB, ACWR (7:28, gleitend),
HR-Zonen-Zeitverteilung, Foster-Monotonie & -Strain, HRV-Baseline (60 d) mit
Normalband, Schlafschuld ggü. Sollschlaf, Ruhepuls-Trend.

**Wichtig:** Jede Kennzahl liefert neben dem Wert auch `confidence` und
`data_coverage` (z. B. "basiert auf 5 von 7 Tagen"). Der Agent ist angewiesen,
Kennzahlen mit niedriger Coverage entsprechend zu qualifizieren.

### 4.4 Agent Layer

Ausführlich in [03 — Agent-Design](03-agent-design.md). Kurzfassung:

```
User-Nachricht
   │
   ├─▶ Systemprompt: Persona + Kennzahlen-Katalog + aktive Erinnerungen
   │                 (agent_memory, ≤ ~1.500 Tokens) + Lagebild (situation_brief.py)
   ├─▶ Historie: token-budgetiert (12.000), herausfallende Turns → Erinnerungen
   │
   ▼
LLM-Loop (SSE-Streaming) ──▶ 12 Core-Tools (immer alle geladen) ──▶ Antwort
   │
   └─▶ bestätigungspflichtige Tools → Proposal (gebunden an tool_call_id)
                                    → Bestätigen/Ablehnen → Ausführung
```

*Zielbild (nicht umgesetzt):* Memory Retrieval per Embedding (`pgvector`), ein Tool
Router sowie `search_tools`/`load_tools` für zweistufiges Laden. Heute filtert
`recall` per Substring über `agent_memory`.

### 4.5 Presentation Layer

- **Chat** (SSE-Streaming) — Primärinterface
- **Dashboard** — Grid aus Modulen, pro Nutzer konfigurierbar
- **Weitere Seiten (Ist):** Kalender, Ziele, Gedächtnis, Sync, Konto, Onboarding.
  *Zielbild (nicht umgesetzt):* Detailansichten für Aktivität und Schlafnacht.

**Ist-Stand Module:** Die Modul-Registry steckt im Frontend
(`web/src/lib/modules.ts`, gerendert als `<Kachel>`); die Nutzerkonfiguration
(Reihenfolge, Größe) liegt in der Tabelle `user_dashboard_tile`. Eine
`module_registry`- oder `user_dashboard`-Tabelle gibt es nicht. Der ursprüngliche
Entwurf (Zielbild) sah serverseitig deklarierte Module vor:

```json
{
  "module_id": "readiness_gauge",
  "title": "Bereitschaft",
  "data_endpoint": "/api/modules/readiness_gauge",
  "component": "Gauge",
  "refresh": "15m",
  "size": {"w": 1, "h": 1}
}
```

Ein neues Modul = ein Endpoint + ein Registry-Eintrag. Die Nutzerkonfiguration ist
nur eine Liste von `module_id` mit Position.

## 5. Wesentliche Datenflüsse

### 5.1 Health-Sync

**Ist-Stand:** Es gibt **keinen Scheduler**. Syncs werden manuell über die UI bzw.
`POST /api/sync/garmin/backfill` ausgelöst und laufen als BackgroundTask. Nach jedem
Garmin-Backfill werden `wellness_daily_stats`, `hr_bucket_seconds_daily` und
`metric_daily_value` für den geholten Zeitraum neu berechnet
(`routers/sync.py:269-285`); zusätzlich per `POST /api/metrics/recompute`.
Login nur per gespeichertem Token über `garminconnect`.

*Zielbild (nicht umgesetzt)* — nächtlicher Ablauf:

```
03:15  Scheduler emittiert SyncJob je Nutzer
       └─ connectors.garmin: Login via gespeicherte Tokens (garminconnect)
          └─ fetch dailies, sleep, hrv, stress, bb, spo2, respiration
          └─ fetch activity list seit Watermark
             └─ je neue Aktivität: Summary + FIT-Download
       └─ RawStore.put(gzip)
       └─ normalize → Canonical
04:00  Metrics-Recompute für betroffene Nutzer/Tage
04:15  Insight-Generator: Auffälligkeiten erkennen → Notification-Queue
```

### 5.2 Kalendersynchronisation

**Ist-Stand:** Google Calendar wird nur manuell abgerufen
(`POST /api/sync/google_calendar/sync`, 60 s Cooldown). Jeder Abruf holt das Fenster
heute −7 bis +83 Tage vollständig; ein `syncToken` wird nicht genutzt (der Connector
übergibt immer `None`). Watch-Channels, Push und automatisches Polling sind nicht
gebaut; CalDAV ebenfalls nicht.

*Zielbild (nicht umgesetzt):* Google **Push** über Watch-Channels (erfordert
öffentliches HTTPS). Der Webhook trägt keine Nutzdaten, sondern triggert nur einen
inkrementellen Sync per `syncToken`; Fallback Poll alle 15 min. Apple/CalDAV: Poll
alle 15 min über `getctag`.

### 5.3 Schreibvorgang (Write-Back)

```
Agent  ──▶ propose_calendar_event(...)  → Tool-Call wird NICHT ausgeführt,
                                          sondern als offenes Proposal gespeichert
                                          (conversation_message.tool_calls + tool_call_id)
        ──▶ SSE-Event `proposal` → Vorschlagskarte im Chat
Nutzer ──▶ bestätigt (UI-Button)
        ──▶ POST /api/agent/conversations/{id}/proposals/{tool_call_id}/confirm
            (Tool-Name und Argumente aus der gespeicherten Nachricht, nie vom Client;
             FOR UPDATE bis zum Commit, Doppelklick → 409 proposal_already_resolved)
        ──▶ Domänen-Funktion schreibt extern (z. B. Google Calendar)
        ──▶ Canonical-Update im selben Commit
```

Eine `proposal`-Tabelle mit `idempotency_key` und ein Audit-Log gibt es nicht. Die
[Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) (G.1) ersetzt die Sperre durch eine Tabelle
`proposal_snapshot` mit Vorschau-Karte und Zustandsmaschine (geplant).

Diese Zweistufigkeit ist nicht verhandelbar. Sie ist gleichzeitig
Halluzinationsschutz, Injection-Schutz und Bedienkomfort (der Nutzer sieht, was
passieren wird).

## 6. Technologieentscheidungen

| Bereich | Wahl | Begründung (Kurz) |
|---|---|---|
| Sprache Backend | Python ≥ 3.12 (CI 3.12) | Ökosystem für Garmin/FIT/Analyse; Kompetenz vorhanden |
| Web-Framework | FastAPI | Async, Pydantic-Schemas → direkt als Tool-Schemas nutzbar |
| DB | Postgres 16 + TimescaleDB | Eine Engine für alles. Hypertables ja; Kompression und Continuous Aggregates sind mit Row-Level-Security **nicht nutzbar** (timescale/timescaledb#6827, #5787) und daher nicht im Einsatz. `pgvector`: Zielbild |
| Queue | — (nicht eingesetzt) | Syncs laufen als FastAPI-`BackgroundTasks`; Redis + `arq` war geplant, ist aber nicht gebaut (Zielbild) |
| Migrationen | Alembic | Standard, plugin-fähig via Branch-Labels |
| Frontend | SvelteKit | PWA; entschieden am 2026-08-10 (PWA-/Web-Push-Reife) |
| Charts | ECharts | Einheitliche Bibliothek für Zeitreihen, Gauges, Scatter + Event-Overlays; deklarative JSON-Konfiguration; siehe [ADR-0005](adr/ADR-0005-echarts.md) |
| Auth | Google OIDC | Self-hosted IdP entfällt; 0 MB Overhead; MFA Google-seitig; siehe [ADR-0006](adr/ADR-0006-google-oidc.md) |
| Reverse Proxy | Caddy | Automatisches TLS, minimale Konfiguration |
| Agent-Tools | Python-Funktionen in `src/kairos/agent/tools.py` (`ToolSpec`), **nicht** hinter dem `Connector`-Protocol | Kein externer Prozess nötig bei einem Agent; Schreibzugriffe über Domänen-Funktionen |
| Tests | pytest + testcontainers | Echte Postgres-Instanz in Tests statt SQLite-Lüge |

## 7. Was bewusst *nicht* gebaut wird

- **Kein eigenes Vektor-DB-Deployment.** Falls Embeddings kommen, reicht `pgvector`
  für < 100k Embeddings um Größenordnungen (heute nicht installiert).
- **Kein Kafka / Event-Bus.** Postgres-Tabelle + Redis-Queue decken das Volumen ab.
- **Kein eigenes Auth-System.** Google OIDC übernimmt den Login; danach gilt ein
  Session-Cookie (`session_id`, Session in Redis), keine JWTs in der App.
- **Kein GraphQL.** Der Hauptkonsument ist der Agent, und der bekommt Tools, keine
  Query-Sprache.
- **Kein Feature-Flag-Service.** Konfiguration in der DB, pro Nutzer.

## 8. Fehler- und Ausfallverhalten

| Ausfall | Verhalten |
|---|---|
| Garmin nicht erreichbar / Login abgelaufen | Lehnt Garmin den Token ab, wird die Verbindung `reauth_required`; der Nutzer verbindet unter Konto & Sync neu. Alte Daten bleiben nutzbar; das Lagebild zeigt den Datenstand je Quelle |
| LLM-API nicht erreichbar | Dashboard und Datenabfragen funktionieren weiter; Chat zeigt Störung |
| Postgres weg | Vollausfall — akzeptiert; abgesichert über Backup + Restore-Test |
| Kalender-Schreibfehler | Die Bestätigung schlägt mit Fehler fehl (z. B. 503 ohne aktive Google-Verbindung), nichts wird committet, der Nutzer kann erneut bestätigen. Einen Proposal-Status `failed` gibt es nicht |

Leitregel: **Der Agent darf nie so tun, als wären Daten aktuell, wenn sie es nicht
sind.** Der Situation Brief enthält immer die Datenaktualität pro Quelle.
