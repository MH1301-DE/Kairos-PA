# Lifestyle Personal Assistant (Arbeitstitel: **Kairos**)

Self-hosted, agentengesteuerter Lifestyle-Assistent für eine kleine geschlossene
Nutzergruppe (5 Personen). Zwei Kerndomänen:

1. **Health & Training** — Garmin-Daten sammeln, normalisieren, analysieren, beraten.
2. **Zeit & Planung** — Kalender pflegen, Aktivitäten (Sport, Lernen, Sonstiges) planen.

Primäres Interface ist ein **LLM-Agent** (Chat), ergänzt um ein **Dashboard mit
konfigurierbaren Modulen**.

---

## Dokumentenübersicht

| Dok | Inhalt |
|---|---|
| [00 – Vision & Scope](docs/00-vision-und-scope.md) | Ziele, Nicht-Ziele, Use Cases, Erfolgskriterien |
| [01 – Architektur](docs/01-architektur.md) | Systemkontext, Container, Datenflüsse, Komponenten |
| [02 – Datenmodell & Volumen](docs/02-datenmodell-und-volumen.md) | Schema, **Garmin-Volumenanalyse**, Retention |
| [03 – Agent-Design](docs/03-agent-design.md) | Kontextbudget, Tool-Registry, Tool-Search, Memory |
| [04 – Integrationen](docs/04-integrationen.md) | Garmin, Google Calendar/Gmail, Apple/CalDAV |
| [05 – Erweiterbarkeit](docs/05-erweiterbarkeit.md) | Plugin-Contract, Manifest, Migrationen |
| [06 – Sicherheit](docs/06-sicherheit-und-datenschutz.md) | Secrets, RLS, Auth, Netzwerk, Prompt Injection, Audit |
| [07 – Deployment & Betrieb](docs/07-deployment-und-betrieb.md) | VM-Sizing, Compose, Backup, Monitoring, Kosten |
| [08 – Roadmap](docs/08-roadmap.md) | Phasen, Meilensteine, Risiken, offene Punkte |
| [ADRs](docs/adr/) | ADR-0001 Monolith · ADR-0002 Eine DB · ADR-0003 Connector-Architektur · ADR-0004 Garmin · ADR-0005 ECharts · ADR-0006 Google OIDC |
| [db/schema.sql](db/schema.sql) | Früher Schema-Entwurf (vor Phase 1, mit TimescaleDB); maßgeblich ist die Alembic-Kette |
| [deploy/docker-compose.yml](deploy/docker-compose.yml) | Deployment-Skizze |

---

## Die wichtigste offene Frage ist beantwortet

> *"Ich weiß nicht, über wie viele Datenpunkte wir bei Garmin sprechen, daher weiß
> ich nicht, ob es möglich ist, diese komplett zu speichern."*

**Ja — vollständig speicherbar, ohne Nachdenken.**
Größenordnung: ca. **3.000 Messpunkte pro Nutzer und Tag** (≈ 1,1 Mio./Jahr).
Für 5 Nutzer über 5 Jahre sind das gemessen **≈ 4–5,5 GB** inklusive
Sekundendaten aller Aktivitäten (als Arrays in `activity_stream`) und der
Original-FIT-Dateien (Stand Stufe 1, 2026-10-17).

Eine VM mit 40 GB SSD reicht dafür. Die Empfehlung ist
daher: **alles roh archivieren und zusätzlich normalisiert ablegen.** Details und
Rechenweg in [02 – Datenmodell & Volumen](docs/02-datenmodell-und-volumen.md).

---

## Architektur in drei Sätzen

Ein **modularer Monolith in Python (FastAPI)** hält API, Domänenlogik und
Metrikberechnung; **Postgres 16** ist die einzige Datenbank
(Zeitreihen und Relationen, ohne Extensions; Vektoren via `pgvector` sind Zielbild); **Integrationen sind als
in-process Module** (`kairos/connectors/`) hinter einem gemeinsamen Protocol
implementiert — saubere Grenze ohne Prozess-Overhead.

Der Agent bekommt **nie Rohdaten** in den Kontext, sondern nur deterministisch
berechnete Kennzahlen und beschränkte Tool-Ergebnisse. Tools werden nicht statisch
geladen, sondern über ein **`search_tools` / `load_tools`-Paar** zur Laufzeit
nachgezogen ([03 – Agent-Design](docs/03-agent-design.md)).

---

## Getroffene Kernannahmen

Diese Annahmen wurden gesetzt, um handlungsfähig zu bleiben. Sie sind bewusst
markiert und sollten vor Baubeginn bestätigt oder korrigiert werden:

1. Deployment auf einer **einzelnen Linux-VM** (angenommen: Hetzner Cloud, Docker
   Compose). Kein Kubernetes.
2. **Kein GPU / kein lokales LLM.** Der Agent nutzt eine LLM-API. Alle
   Gesundheitsdaten werden dabei nur als aggregierte Kennzahlen übertragen, nie roh.
3. **Garmin-Zugriff über die inoffizielle Connect-API** (`garth` / `garminconnect`),
   da die offizielle Health API eine B2B-Partnerschaft voraussetzt. Siehe
   [ADR-0004](docs/adr/ADR-0004-garmin-zugang.md) inkl. ToS-Bewertung.
4. **Geschlossene Nutzergruppe, kein öffentliches Signup.** Alle 5 Nutzer sind
   einander bekannt; Datentrennung erfolgt logisch (RLS), nicht physisch.
5. Backend **Python**, Frontend **PWA** (React/Next.js oder SvelteKit).

## Nächster Entscheidungsbedarf

Siehe [08 – Roadmap, Abschnitt "Offene Punkte"](docs/08-roadmap.md#offene-punkte).
