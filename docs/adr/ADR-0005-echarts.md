# ADR-0005 — Visualisierungsbibliothek: ECharts

**Status:** Akzeptiert  
**Datum:** 2026-08-02  
**Entscheider:** Betreiber

---

## Kontext

Das Dashboard zeigt Zeitreihen (HR, HRV, CTL/ATL, Stress …) mit bis zu 365
Datenpunkten pro Metrik im Standardfall, bei Aktivitätsdetails bis zu ~3.300 Punkten
(1-Hz-Aufzeichnung). Events (Trainingseinheiten, Kalendertermine) sollen als
Overlays auf denselben Zeitachsen darstellbar sein.

Bewertet wurden: **ECharts**, **uPlot**, **Chart.js**, **Recharts**, **Victory**.

---

## Entscheidung

**ECharts** (`echarts` + `echarts-for-react` bzw. direkte Instanziierung).

---

## Begründung

| Kriterium | ECharts | uPlot | Chart.js |
|---|---|---|---|
| Performance (100k+ Punkte) | ✅ Canvas-Renderer | ✅ sehr schnell | ⚠️ ab ~10k langsam |
| Overlay mehrerer Serien + Event-Marker | ✅ nativ | ⚠️ eingeschränkt | ✅ |
| Scatter, Gauge, Heatmap, Bar | ✅ alles eingebaut | ❌ nur Zeitreihen | ✅ |
| TypeScript-Typen | ✅ vollständig | ⚠️ Community-Types | ✅ |
| Deklarative Konfiguration (JSON) | ✅ | ❌ imperative API | ⚠️ |
| Bundelgröße (gzip) | ~500 KB (tree-shaking möglich) | ~15 KB | ~200 KB |

**Ausschlaggebend:** ECharts ist die einzige Bibliothek, die Zeitreihen, Gauges,
Scatter-Plots und Event-Marker auf einer gemeinsamen Zeitachse in einem einheitlichen
deklarativen Konfigurationsmodell abdeckt. Das ist für das agent-gesteuerte
Dashboard-Building wichtig: Der Agent kann eine Chart-Spezifikation als JSON
zurückgeben, die das Frontend direkt als ECharts-Option interpretiert.

**Bundelgröße:** Mit Tree-Shaking (nur verwendete Chart-Typen importieren) sinkt
die Größe auf ~150–200 KB gzip — akzeptabel für eine PWA.

---

## Konsequenzen

- Das `render`-Tool des Agenten gibt eine ECharts-kompatible `option`-Spezifikation
  zurück — kein eigenes Zwischen-Format nötig.
- Neue `component`-Typen im Dashboard sind ECharts-Konfigurationen, kein Custom-Code.
- uPlot wird **nicht** eingesetzt (war im ursprünglichen Architekturentwurf erwähnt
  — dieser Eintrag überschreibt ihn).
