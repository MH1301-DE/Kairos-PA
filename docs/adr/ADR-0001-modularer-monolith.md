# ADR-0001 — Modularer Monolith statt Microservices

**Status:** Akzeptiert  
**Datum:** 2026-08-01  
**Entscheider:** Betreiber

---

## Kontext

Kairos braucht eine Deployment-Architektur für eine Anwendung mit 5 Nutzern,
einem Betreiber und einem einzelnen Entwickler. Die Frage war: separate Services
je Domäne (Microservices) oder ein einzelnes Deployment (Monolith)?

---

## Entscheidung

**Modularer Monolith:** Ein FastAPI-Prozess mit klar getrennten internen
Packages (`kairos/identity/`, `kairos/health/`, `kairos/calendar/`,
`kairos/planning/`, `kairos/agent/`, `kairos/metrics/`). Modulgrenzen werden
durch Import-Linter in CI erzwungen, nicht durch Prozess- oder Netzwerkgrenzen.

---

## Begründung

| Argument für Microservices | Gewicht hier |
|---|---|
| Unabhängiges Skalieren einzelner Services | ❌ bei 5 Nutzern kein Bedarf |
| Teams können Services unabhängig deployen | ❌ ein Entwickler |
| Fault Isolation zwischen Services | ❌ Postgres-Ausfall = Totalausfall sowieso |
| Unabhängige Tech-Stacks je Service | ❌ alles Python, kein Grund |

Microservices bringen bei diesem Use Case ausschließlich Kosten:
- Verteilte Transaktionen (Saga-Pattern) statt lokaler DB-Transaktionen
- Service Discovery, Health-Checks, Netzwerk-Timeouts zwischen Services
- N separate Build-Pipelines, N Docker-Images, N Deployment-Zyklen
- Erhöhte Debugging-Komplexität (verteiltes Tracing nötig)

**Modularer Monolith liefert dieselben logischen Grenzen** ohne diese Kosten:
Import-Linter verhindert verbotene Cross-Module-Importe. Ein Modul kommuniziert
mit einem anderen ausschließlich über definierte Service-Interfaces (`kairos/core/`).

---

## Konsequenzen

### Positiv
- Ein `docker-compose.yml`, ein Build, ein Deployment.
- Lokale Transaktionen über Modulgrenzen hinweg — kein Distributed-Commit.
- Einfaches lokales Development (`uvicorn kairos.api:app --reload`).

### Einschränkungen
- Ein Prozessabsturz betrifft alle Domänen. In der Praxis: Python-Prozesse
  crashen nicht auf Exceptions; der API-Server wird via `restart: unless-stopped`
  neu gestartet.
- Geteilter Speicher und Dependency-Raum. Mitigation: strenge Dependency-Reviews.

### Upgrade-Pfad
Ein Modul kann herausgeschnitten werden, wenn es je nötig ist. Die Service-Interface-
Grenze ist dann bereits die API-Grenze. Der Import-Linter stellt sicher, dass
keine versteckten Abhängigkeiten existieren.

**Ausnahme (bewusst):** Connectoren laufen als in-process Module hinter dem
`Connector`-Protocol ([ADR-0003](ADR-0003-connector-architektur.md)), nicht als
separate Services — aber auch nicht direkt im API-Modul verdrahtet.
