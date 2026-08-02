# 05 — Erweiterbarkeit

Kairos ist bewusst erweiterbar gebaut: Neue Datenquellen, neue Visualisierungen und
neue Domänen sollen hinzukommen können, ohne den Kern zu ändern. Das gilt für
Dashboard-Module, Connectoren und zukünftige Domänen (Ernährung, Lernen, Stimmung).

---

## 1. Zwei Erweiterungspunkte

| Erweiterungspunkt | Beschreibung | Scope V1 |
|---|---|---|
| **Dashboard-Modul** | Neue Visualisierung oder Kennzahlenkachel im Dashboard | ✅ Phase 2 |
| **Connector** | Neue externe Datenquelle (z. B. Apple Health, Oura, Withings) | ✅ Phase 1+ |
| **Agent-Tool** | Neue Fähigkeit für den Agenten | ✅ Phase 4+ |
| **Domäne** | Vollständig neue fachliche Domäne (Ernährung, Lernen …) | 🔜 Phase 6+ |

---

## 2. Dashboard-Module

### 2.1 Grundprinzip

Jedes Dashboard-Modul ist **deklarativ** — ein Registry-Eintrag beschreibt, was
dargestellt wird, und ein zugehöriger API-Endpoint liefert die Daten. Das Frontend
rendert das Modul generisch auf Basis des `component`-Typs.

```json
{
  "module_id":   "readiness_gauge",
  "title":       "Bereitschaft",
  "component":   "Gauge",
  "data_endpoint": "/api/modules/readiness_gauge",
  "refresh":     "15m",
  "size":        {"w": 1, "h": 1},
  "config_schema": {}
}
```

Ein neues Modul entsteht durch:
1. Endpoint in `kairos/api/modules/{module_id}.py`
2. Eintrag in `module_registry` (per Alembic-Datenmigration)
3. Kein Frontend-Code nötig, wenn der `component`-Typ bereits existiert

### 2.2 Komponenten-Typen

| Typ | Beschreibung | Visualisierungsbibliothek |
|---|---|---|
| `Gauge` | Einzelwert mit Skala (Bereitschaft, Body Battery) | ECharts |
| `TimeSeriesChart` | Zeitreihen mit optionalen Event-Overlays | ECharts |
| `BarChart` | Balkendiagramm (z. B. Wochenvolumen, HR-Zonen) | ECharts |
| `ScatterChart` | Korrelation zweier Metriken | ECharts |
| `StatCard` | Einzelkennzahl mit Trend-Indikator | — (reines HTML) |
| `Table` | Tabellarische Ansicht von Zeitreihen oder Aktivitäten | — |
| `ActivityList` | Scrollbare Aktivitätsliste mit Kennzahlen | — |

**Visualisierungsbibliothek: ECharts.** Gilt einheitlich für alle chart-basierten
Komponenten. Begründung: skaliert auf große Datenpunktmengen (100k+ Punkte im
Browser), unterstützt Overlay mehrerer Serien und Event-Marker auf einer Zeitachse,
gute TypeScript-Typen. Siehe [ADR-0005](adr/ADR-0005-echarts.md).

### 2.3 Zeitreihen und Event-Overlays

`TimeSeriesChart` unterstützt das Übereinanderlegen von:
- **Metriken** (HR, HRV, Stress, Body Battery, CTL/ATL …) — beliebig viele Serien
- **Events** (Trainingseinheiten, Kalendertermine, manuelle Marker) — als vertikale
  Linien oder Marker-Pins auf der Zeitachse

Das ist die zentrale Designentscheidung für die Analyse-Ansicht: ein Nutzer soll
z. B. seinen HRV-Verlauf über 4 Wochen sehen und dabei erkennen, nach welchen
Trainingseinheiten er besonders stark abfällt. Die Konfiguration erfolgt über den
`config_schema` des Moduls:

```json
{
  "series": ["hrv_night_ms", "hr_rest"],
  "event_overlays": ["activity", "calendar_event"],
  "time_range": "28d"
}
```

### 2.4 Nutzer-Dashboard: manuelle und agent-gesteuerte Konfiguration

**Manuell:** Jeder Nutzer hat eine persönliche `user_dashboard`-Tabelle
(Reihenfolge, Modulauswahl, Pro-Modul-Config). Das Dashboard ist ein
Drag-and-Drop-Grid; Module können hinzugefügt, entfernt und konfiguriert werden.

**Agent-gesteuert:** Der Agent hat Zugriff auf Write-Tools für das Dashboard:

```
Nutzer: "Leg mir ein Chart an, das meinen HRV-Verlauf
         der letzten 60 Tage mit meinen Laufeinheiten überlagert."

Agent → dashboard.add_module(
          component="TimeSeriesChart",
          config={series:["hrv_night_ms"], event_overlays:["activity"], time_range:"60d"}
        )
     → Proposal-Objekt (Write-Operation, braucht Bestätigung)
     → Nutzer bestätigt → Modul erscheint im Dashboard
```

Dieses Muster gilt auch für Umkonfigurieren, Entfernen und Neuordnen von Modulen.
Alle Dashboard-Writes laufen über den Proposal-Mechanismus ([03](03-agent-design.md#6-schreibvorgänge-und-sicherheit)).

---

## 3. Connector-Erweiterungen

Ein neuer Connector (z. B. Oura, Apple Health) entsteht durch Implementierung des
`Connector`-Protocols unter `kairos/connectors/{name}/`:

```python
# Pflichtfelder laut Protocol
class OuraConnector:
    connector_id = "oura"

    async def fetch(self, user_id, kind, window) -> RawPayload: ...
    async def normalize(self, payload) -> list[CanonicalRecord]: ...
    async def write_back(self, user_id, proposal) -> WriteResult: ...
```

Zusätzlich erforderlich:
- Eintrag in `data_source`-Tabelle (per Datenmigration)
- Neue `metric_def`-Einträge für Metriken, die noch nicht existieren
- Kein Kern-Code ändert sich; Import-Linter stellt sicher, dass der Connector
  nicht direkt aus `kairos.api` importiert wird

### 3.1 Alembic-Migrationsstrategie für Plugins

Plugins bringen eigene Migrationen mit. Alembic unterstützt **Branch Labels**:

```
alembic revision --rev-id oura_001 --branch-label oura \
  --depends-on base -m "oura: add metric_defs"
```

Der Hauptzweig (`heads`) schließt alle aktiven Plugin-Zweige ein. Eine
Plugin-Migration kann nie den Kern-Zweig beschädigen, weil sie im eigenen Branch
lebt.

---

## 4. Agent-Tool-Erweiterungen

Neue Tools werden in der `tool_registry`-Tabelle registriert:

```sql
INSERT INTO tool_registry (tool_id, name, pack, version,
  one_liner, when_to_use, json_schema, risk_class, is_core)
VALUES (
  'weather.forecast',
  'Wettervorhersage',
  'weather',
  '1.0.0',
  'Wettervorhersage für einen Ort und Zeitraum.',
  'Nutzen wenn der Nutzer nach Wetter fragt oder eine Outdoor-Einheit plant.',
  '{"type":"object","properties":{"location":{"type":"string"},"date":{"type":"string"}}}',
  'read',
  false
);
```

Das Embedding über `one_liner + when_to_use` wird automatisch beim Einfügen
berechnet (Trigger oder Migrations-Job). Das Tool steht sofort für `search_tools`
zur Verfügung — kein Restart, kein Deployment.

### 4.1 Referenz-Plugin: Wetter (Phase 6)

Nachweisaufgabe für das Plugin-System: Ein vollständiges externes Plugin in
< 150 Zeilen Python. Umfang:
- Ein `WeatherConnector` (fetch von Open-Meteo, kostenlos, kein API-Key)
- Zwei Tools: `weather.forecast`, `weather.history`
- Zwei Dashboard-Module: `WeatherCard` (heute), `WeatherTimeSeriesChart` (7-Tage)
- Eine Alembic-Migration im eigenen Branch

Wenn das funktioniert, ist das Plugin-System nachgewiesen.

---

## 5. Grenzen der Erweiterbarkeit

Was bewusst nicht möglich ist ohne Kern-Änderung:

| Nicht möglich ohne Kern-Änderung | Begründung |
|---|---|
| Eigene Auth-Methoden | Auth läuft über Google OIDC; kein self-hosted IdP |
| Direktzugriff auf `wellness_sample` aus einem Plugin | Nur über definierte Repository-Interfaces |
| Eigene Datenbank-Verbindungen | Eine Datenbank, kein zweites Datensystem |
| Überschreiben bestehender `metric_def` | Metriken sind append-only; Breaking Changes erfordern neue IDs |
| Frontend-Komponenten-Typen ohne Kern-Deployment | Neue `component`-Typen erfordern einen Frontend-Build |
