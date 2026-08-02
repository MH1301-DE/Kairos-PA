# ADR-0003 — Connector-Architektur: In-process Module statt MCP-Server

**Status:** Akzeptiert  
**Datum:** 2026-08-01  
**Entscheider:** Betreiber

---

## Kontext

Kairos muss Daten von drei externen Diensten abrufen: Garmin Connect, Google
Calendar und Apple/CalDAV. Die Frage war, wie die Grenze zwischen dem Kern und diesen
Integrationspunkten gezogen werden soll.

**Ursprünglicher Entwurf:** Jede Integration als eigener MCP-Server-Prozess —
separater Container, HTTP-Transport, eigenständige Build-Pipeline.

**Alternativen bewertet:**

| Option | Beschreibung |
|---|---|
| A — MCP-Server | Je Connector ein eigener Prozess + Docker-Container |
| **B — In-process Module** | Connector als Python-Package, `Connector`-Protocol, Import-Linter-Grenze |
| C — Hybrid | Garmin als MCP, Google + CalDAV in-process |

---

## Entscheidung

**Option B — In-process Module** wird umgesetzt.

Connectoren leben unter `kairos/connectors/{garmin,google,caldav}/` und
implementieren das gemeinsame `Connector`-Protocol:

```python
class Connector(Protocol):
    connector_id: str

    async def fetch(self, user_id: UUID, kind: str,
                    window: tuple[datetime, datetime]) -> RawPayload: ...
    async def normalize(self, payload: RawPayload) -> list[CanonicalRecord]: ...
    async def write_back(self, user_id: UUID, proposal: Proposal) -> WriteResult: ...
```

Die Modulgrenze wird durch den **Import-Linter** in CI erzwungen:
`kairos.api` und `kairos.agent` dürfen niemals direkt in `kairos.connectors`
importieren — nur über `kairos.connectors.registry` (Dependency-Injection).

---

## Begründung

### Warum nicht MCP-Server?

1. **Kein Mehrwert bei einem einzigen Agent-Konsumenten.** Der Hauptnutzen von MCP
   ("beliebige Clients können sich verbinden") trifft hier nicht zu.

2. **Operative Komplexität ist das realistischste Projektrisiko** (R6 im
   Risikoregister). Drei zusätzliche Container, Build-Pipelines und Health-Checks
   erhöhen die Wahrscheinlichkeit, dass das Projekt versandet.

3. **Crash-Isolation ist schwächer als sie klingt.** Python-Exceptions crashen
   keinen Prozess; ein Connector-Fehler wirft eine Exception, die normal behandelt
   wird. Echter Prozessabsturz ist bei `garth`, `google-auth` und `icalendar`
   (alles stabile, reife Bibliotheken) kein realistisches Szenario.

4. **Dependency-Konflikte sind beherrschbar.** Die drei Connector-Bibliotheken haben
   keine strukturellen Versionskonflikte; ein einzelnes `pyproject.toml` reicht.

5. **Kein Netzwerk-Overhead.** Jeder Tool-Call spart einen HTTP-Roundtrip (lokal,
   aber messbar bei vielen Calls pro Turn).

### Was In-process Module leisten

- Dieselbe **logische Grenze** wie ein externer Prozess — erzwungen durch Linter
  statt durch das Netzwerk.
- **Identisches Interface** (`Connector`-Protocol) — ein späteres Herausschneiden zu
  MCP ändert nur den Transport-Layer, nicht die Connector-Logik.
- **Einfacheres Deployment** — ein `docker-compose.yml` mit 6 statt 9 Services.

---

## Konsequenzen

### Positiv

- Weniger Container, weniger CI-Komplexität, schnellere Iteration in Phase 1.
- Kein HTTP-Overhead zwischen Scheduler und Connector.
- Gemeinsame Transaktionsgrenze: Connector und Repository laufen in derselben
  DB-Verbindung; kein verteiltes Commit nötig.

### Einschränkungen / Risiken

- **Kein unabhängiges Deployment** eines einzelnen Connectors ohne App-Neustart.
  Bei 5 Nutzern und nächtlichem Sync ist das akzeptabel (Downtime < 30 s).
- **Geteilter Dependency-Raum.** Zukünftige Bibliotheken mit strukturellen
  Konflikten müssten via virtualenv oder Subprocess isoliert werden — kein
  Automatismus mehr.
- **Fehlgeschlagener Connector blockiert Thread** (nicht Prozess). Lösung:
  `asyncio.wait_for` mit Timeout per Connector-Call.

---

## Upgrade-Pfad

Wenn eine der folgenden Bedingungen eintritt, kann die Entscheidung revidiert werden:

- Ein zweiter Agent oder ein externer Client soll dieselben Tools nutzen.
- Ein Connector hat wiederholt Dependency-Konflikte verursacht.
- Deployment-Frequenz eines einzelnen Connectors übersteigt 1×/Woche.

Da das `Connector`-Protocol in beiden Varianten identisch ist, bedeutet das
Herausschneiden zu MCP nur die Implementierung eines neuen Transport-Adapters
— die Connector-Logik selbst bleibt unverändert.
