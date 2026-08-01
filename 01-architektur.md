# 01 — Architektur

## 1. Architekturprinzipien

Diese fünf Prinzipien entscheiden im Zweifel jede Detailfrage:

1. **Determinismus vor Intelligenz.** Alles, was berechenbar ist, wird berechnet.
   Das LLM interpretiert Ergebnisse, es erzeugt sie nicht.
2. **Eine Datenbank.** Postgres deckt Relationen, Zeitreihen (TimescaleDB), Volltext
   und Vektoren (`pgvector`) ab. Kein zweites Datensystem ohne zwingenden Grund.
3. **Die Integrationsgrenze ist ein Prozess, nicht eine Funktion.** Jede externe
   Anbindung ist ein eigener MCP-Server. Das erzwingt saubere Schnitte und macht
   Austausch/Ausfall beherrschbar.
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
                ┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐
                │ Garmin │ │  Google  │ │ Apple  │ │ LLM-API  │
                │Connect │ │ Cal/Mail │ │ CalDAV │ │(Anthropic)│
                └────────┘ └──────────┘ └────────┘ └──────────┘
                  Pull       Push+Pull      Pull      Request/Resp
```

**Vertrauensgrenzen:** Alles innerhalb der VM ist vertrauenswürdig. Alles außerhalb
ist nicht vertrauenswürdig — insbesondere Inhalte aus Gmail und Kalendereinladungen,
die als potenzielle Prompt-Injection behandelt werden ([06](06-sicherheit-und-datenschutz.md)).

## 3. Containerdiagramm (C4 Level 2)

```
┌─────────────────────────────────────────────────────────────────────┐
│ VM (Docker Compose)                                                 │
│                                                                     │
│  ┌───────────┐                                                      │
│  │  Caddy    │  TLS-Terminierung, Reverse Proxy, Basic Rate Limit   │
│  └─────┬─────┘                                                      │
│        │                                                            │
│  ┌─────▼──────────┐        ┌──────────────────┐                     │
│  │  Web (PWA)     │        │  Auth (OIDC)     │                     │
│  │  React/Svelte  │◀──────▶│  Authentik       │                     │
│  └─────┬──────────┘        └──────────────────┘                     │
│        │ REST / SSE                                                 │
│  ┌─────▼──────────────────────────────────────────┐                 │
│  │  API + Domain  (FastAPI, modularer Monolith)   │                 │
│  │  ┌──────────┬──────────┬──────────┬─────────┐  │                 │
│  │  │ identity │  health  │ calendar │planning │  │                 │
│  │  ├──────────┼──────────┼──────────┼─────────┤  │                 │
│  │  │ metrics  │  agent   │ registry │ modules │  │                 │
│  │  └──────────┴──────────┴──────────┴─────────┘  │                 │
│  └───┬───────────────────────┬─────────────┬──────┘                 │
│      │                       │             │                        │
│      │  MCP (stdio/HTTP)     │             │                        │
│  ┌───▼────┬────────┬─────────▼──┐    ┌─────▼──────┐                 │
│  │ mcp-   │ mcp-   │  mcp-      │    │  Worker    │  arq / Celery   │
│  │ garmin │ google │  caldav    │    │  Scheduler │                 │
│  └────────┴────────┴────────────┘    └─────┬──────┘                 │
│                                            │                        │
│  ┌──────────────────────┐  ┌───────────────▼─────┐  ┌────────────┐  │
│  │ Postgres 16          │  │ Redis               │  │ Object     │  │
│  │ + TimescaleDB        │  │ Queue, Cache, Locks │  │ Store      │  │
│  │ + pgvector           │  │                     │  │ (FIT/Raw)  │  │
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

**Ausnahme:** Connectors laufen als eigene Prozesse (MCP-Server). Das ist bewusst,
weil sie die instabilste, am häufigsten geänderte und sicherheitskritischste
Komponente sind. Siehe [ADR-0003](adr/ADR-0003-mcp-als-integrationsgrenze.md).

## 4. Schichten

### 4.1 Ingestion Layer

Zuständig für: Auth gegen externe Dienste, Abholen, Rate-Limiting, Retry,
Idempotenz, Ablage im Raw-Store.

```
Scheduler ──▶ SyncJob(user, connector, window)
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
- **Backfill als eigener Jobtyp** mit niedrigerer Priorität und aggressiverem
  Rate-Limit, damit der Erstimport (12 Monate Historie) den laufenden Betrieb nicht
  blockiert.
- **Verlustfreie Fehlerbehandlung.** Fehlgeschlagene Fenster landen in einer
  `sync_failure`-Tabelle und werden mit Backoff wiederholt, nicht stillschweigend
  übersprungen.

### 4.2 Storage Layer

Drei Zonen, klar getrennt:

| Zone | Inhalt | Mutabilität | Zweck |
|---|---|---|---|
| **Raw** | Original-API-Antworten (JSONB/gzip), FIT-Dateien | append-only | Wahrheit, Reprocessing |
| **Canonical** | Normalisierte Domänenobjekte | upsert | Abfragen, Joins |
| **Derived** | Berechnete Kennzahlen, Aggregate | rebuildbar | Performance, Agent-Antworten |

Die Derived-Zone ist **jederzeit vollständig aus Canonical rekonstruierbar**. Damit
ist ein Fehler in der Metrikberechnung kein Datenverlust, sondern ein Recompute.

### 4.3 Domain / Metrics Layer

Reine Python-Funktionen ohne I/O, gut testbar:

```python
def training_load(sessions: list[Session], *, tau_ctl=42, tau_atl=7) -> LoadState:
    """Banister-Impulse-Response. Liefert CTL, ATL, TSB je Tag."""
```

Kennzahlen V1: TRIMP (Banister/Edwards), CTL/ATL/TSB, ACWR (7:28, gleitend),
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
   ├─▶ Situation Brief Builder   (DB → ~600 Tokens, deterministisch)
   ├─▶ Memory Retrieval          (pgvector → ~400 Tokens)
   ├─▶ Tool Router               (Intent → Tool Pack vorladen)
   │
   ▼
LLM-Loop ──▶ search_tools / load_tools ──▶ Domain-Tools ──▶ Antwort
   │
   └─▶ Write-Proposals → Confirmation Queue → Ausführung
```

### 4.5 Presentation Layer

- **Chat** (SSE-Streaming) — Primärinterface
- **Dashboard** — Grid aus Modulen, pro Nutzer konfigurierbar
- **Detailansichten** — Aktivitätsdetail, Schlafnacht, Kalenderwoche

Module sind deklariert, nicht hartcodiert:

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

### 5.1 Nächtlicher Health-Sync

```
03:15  Scheduler emittiert SyncJob je Nutzer
       └─ mcp-garmin: Login via gespeicherte Tokens (garth)
          └─ fetch dailies, sleep, hrv, stress, bb, spo2, respiration
          └─ fetch activity list seit Watermark
             └─ je neue Aktivität: Summary + FIT-Download
       └─ RawStore.put(gzip)
       └─ normalize → Canonical
04:00  Metrics-Recompute für betroffene Nutzer/Tage
04:15  Insight-Generator: Auffälligkeiten erkennen → Notification-Queue
```

### 5.2 Kalendersynchronisation

Google: **Push** über Watch-Channels (erfordert öffentliches HTTPS — vorhanden).
Der Webhook trägt keine Nutzdaten, sondern triggert nur einen inkrementellen Sync
per `syncToken`. Fallback und Sicherheitsnetz: Poll alle 15 min.

Apple/CalDAV: kein Push. Poll alle 15 min über `getctag`; nur bei Änderung werden
Events geholt.

### 5.3 Schreibvorgang (Write-Back)

```
Agent  ──▶ propose_calendar_event(...)  → Proposal-Objekt, KEINE Ausführung
        ──▶ Antwort an Nutzer mit Vorschlagskarte
Nutzer ──▶ bestätigt (UI-Button oder "ja, mach")
        ──▶ commit_proposal(proposal_id, idempotency_key)
        ──▶ Connector schreibt extern
        ──▶ Canonical-Update + Audit-Log-Eintrag
```

Diese Zweistufigkeit ist nicht verhandelbar. Sie ist gleichzeitig
Halluzinationsschutz, Injection-Schutz und Bedienkomfort (der Nutzer sieht, was
passieren wird).

## 6. Technologieentscheidungen

| Bereich | Wahl | Begründung (Kurz) |
|---|---|---|
| Sprache Backend | Python 3.12 | Ökosystem für Garmin/FIT/Analyse; Kompetenz vorhanden |
| Web-Framework | FastAPI | Async, Pydantic-Schemas → direkt als Tool-Schemas nutzbar |
| DB | Postgres 16 + TimescaleDB + pgvector | Eine Engine für alles; Kompression; Continuous Aggregates |
| Queue | Redis + `arq` | Deutlich schlanker als Celery bei gleichem Nutzen hier |
| Migrationen | Alembic | Standard, plugin-fähig via Branch-Labels |
| Frontend | SvelteKit **oder** Next.js | PWA, Web Push; Entscheidung offen ([08](08-roadmap.md)) |
| Charts | uPlot (Zeitreihen) + ECharts | uPlot skaliert auf 100k Punkte im Browser |
| Auth | Authentik (OIDC) | Self-hosted, MFA, 5 Nutzer trivial verwaltbar |
| Reverse Proxy | Caddy | Automatisches TLS, minimale Konfiguration |
| Agent-Tools | MCP | Standardisierte Grenze, prozessisoliert, austauschbar |
| Tests | pytest + testcontainers | Echte Postgres-Instanz in Tests statt SQLite-Lüge |

## 7. Was bewusst *nicht* gebaut wird

- **Kein eigenes Vektor-DB-Deployment.** `pgvector` reicht für < 100k Embeddings um
  Größenordnungen.
- **Kein Kafka / Event-Bus.** Postgres-Tabelle + Redis-Queue decken das Volumen ab.
- **Kein eigenes Auth-System.** Authentik übernimmt; die App kennt nur JWTs.
- **Kein GraphQL.** Der Hauptkonsument ist der Agent, und der bekommt Tools, keine
  Query-Sprache.
- **Kein Feature-Flag-Service.** Konfiguration in der DB, pro Nutzer.

## 8. Fehler- und Ausfallverhalten

| Ausfall | Verhalten |
|---|---|
| Garmin nicht erreichbar / Login abgelaufen | Sync pausiert, Nutzer erhält Reauth-Hinweis im Dashboard; alte Daten bleiben nutzbar; Agent kennzeichnet Datenstand als veraltet |
| LLM-API nicht erreichbar | Dashboard und Datenabfragen funktionieren weiter; Chat zeigt Störung |
| MCP-Server abgestürzt | Betroffene Tools verschwinden aus der Registry; Agent sagt ehrlich, dass die Fähigkeit gerade fehlt |
| Postgres weg | Vollausfall — akzeptiert; abgesichert über Backup + Restore-Test |
| Kalender-Schreibfehler | Proposal bleibt im Status `failed`, Nutzer wird informiert, Retry manuell |

Leitregel: **Der Agent darf nie so tun, als wären Daten aktuell, wenn sie es nicht
sind.** Der Situation Brief enthält immer die Datenaktualität pro Quelle.
