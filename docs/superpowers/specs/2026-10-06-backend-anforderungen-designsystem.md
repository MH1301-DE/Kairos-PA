# Backend-Anforderungen aus dem Designsystem „Ruhe“

**Stand:** 2026-10-06 · **Quelle:** claude.ai/design-Projekt „Kairos“ (`Kairos Designsystem.dc.html`, `Kairos Kachel.dc.html`, `kairos-tokens.json`) · **Frontend-Stand:** `main` @ Kachel-Commit `1884d9d` + Fixes

Das Frontend setzt die Kachel-Komponente mit allen fünf Zuständen um (vollständig, teilweise, laden, leer, fehler). Von den neun Kacheltypen im Design sind vier mit heutigen Daten gebaut: Rundanzeige, Kennzahl, Belastung und Verteilung. Diese Liste beschreibt, was das Backend liefern muss, damit der Rest des Designs mit echten Daten funktioniert. Die Prioritäten sind:

- **P1:** Fehler oder Widersprüche, die man heute schon sieht.
- **P2:** Fehlende Daten für bereits gebaute Kacheln.
- **P3:** Neue Kacheltypen und Agent-Funktionen.

Pfade und Feldnamen sind Vorschläge. Maßgeblich ist der beschriebene Inhalt.

---

## P1 · Widersprüche, die heute im Dashboard sichtbar sind

Beobachtet am 2026-10-06 mit einem echten Konto auf dem laufenden Backend.

### 1.1 ACWR und Monotonie melden „0 von 7 Tagen“, CTL dagegen 24 von 90

- **Beobachtung:**
  - `GET /api/metrics/acwr` und `.../monotony_strain` liefern `coverage_days: 0, coverage_required_days: 7, confidence: insufficient_data`.
  - `training_load` liefert für denselben Tag `coverage_days: 24` und Werte (CTL 19, ATL 1).
- **Erwartung:** Alle drei beruhen auf derselben Edwards-TRIMP-Tagesreihe. Entweder zählt `coverage_days` bei ACWR und Monotonie etwas anderes, z. B. nur Tage mit Last > 0 in den letzten 7 Tagen, oder der Wert ist falsch.
- **Anforderung:** `coverage_days` hat bei allen Metriken dieselbe Bedeutung: Tage mit Messgrundlage im Fenster der Metrik. Ein Ruhetag mit Uhr am Arm zählt als abgedeckt. Fehlt der Grund für `insufficient_data`, soll er in `reason` stehen (siehe 2.3).

### 1.2 HRV-Baseline: `insufficient_data` trotz 32 Nächten Historie

- **Beobachtung:** `coverage_days: 32, coverage_required_days: 20`, trotzdem `value: null` und `confidence: insufficient_data`. Ursache ist, dass die heutige Nachtmessung fehlt; sie kommt oft erst morgens.
- **Anforderung:** Wenn die Baseline steht und nur der heutige Wert fehlt:
  - Den letzten verfügbaren Wert mit Datum liefern (`value.today` plus `value.measured_at`).
  - Dazu `confidence: medium` setzen.
  - Im Frontend erscheint das dann als „teilweise · vorläufig“.
  
  „Leer“ ist nur richtig, wenn die Baseline selbst noch nicht berechenbar ist.

### 1.3 TRIMP an Ruhetagen: `coverage_days: 0` und `confidence: low`

- **Beobachtung:** Ein Ruhetag liefert `value: 0, coverage_days: 0, coverage_required_days: 1`. Das Frontend fängt das inzwischen ab („keine Aktivität im Zeitraum“). Fachlich lassen sich aber zwei Fälle nicht unterscheiden:
  - Kein Training (der Wert 0 ist echt).
  - Uhr nicht getragen, keine Daten (der Wert ist unbekannt).
- **Anforderung:** Ein Feld, das beide Fälle trennt, z. B. `coverage_days` = Tage *mit Uhr getragen* (aus `hr_intraday` oder `daily_summary`) und `active_days` = Tage mit Aktivität. Dasselbe gilt für `hr_zone_distribution`. Dort liefert ein Tag ohne Pulsmessung heute ein Dictionary voller Nullen statt `null`.

---

## P2 · Daten für die bereits gebauten Kacheln

### 2.1 Persönlicher Normalbereich pro Metrik („Lage-Leiste“, Band im Bogen)

Designregel: *Jeder Wert steht neben dem persönlichen Normalbereich.* Das Band ist der Bereich, in dem 80 % der Werte der letzten 60 Tage liegen.

- **Anforderung:** `MetricResult` bekommt ein optionales Feld:
  ```json
  "normal_range": { "low": 55, "high": 68, "days_used": 60, "days_needed": 14,
                    "scale_min": 40, "scale_max": 80 }
  ```
  - `low` und `high` sind das 10. und 90. Perzentil der letzten 60 Tage.
  - Liegen weniger als `days_needed` Tage vor, kommt `low`/`high` als `null` mit `days_used`. Das Frontend zeigt dann „Band entsteht · 9 von 14 Tagen“.
  - `scale_min` und `scale_max` geben eine sinnvolle Achse vor, z. B. das 2. und 98. Perzentil mit etwas Rand.
- **Betroffen:** Schlafschuld, Ruhepuls, TRIMP (Band der Einzeleinheiten), Monotonie, HRV. Bei HRV ersetzt das die heutige Ableitung aus `baseline_low`/`baseline_high`, die mit Mittelwert ± SD rechnet statt mit Perzentilen.
- **Frontend-Bauteil:** `RangeBar.svelte` existiert bereits und wartet nur auf diese Werte.

### 2.2 Lückenmaske pro Fenster

Designregel: *Lücken werden gezeigt, nicht geglättet.* Die Fußzeile zeigt im Design pro Nacht oder Tag einen Punkt, gefüllt oder hohl.

- **Anforderung:** `MetricResult.coverage_mask: boolean[]`, ein Eintrag pro Tag des Metrikfensters, ältester zuerst. Damit kann das Frontend die Punkte zeichnen und Lücken in Kurven schraffieren.

### 2.3 Grund für „leer“ und „teilweise“

Die Leer-Texte im Design sind konkret: „Bisher: eine Nacht“, „Die Uhr misst HRV nur im Schlaf“, „Ruhetage sind keine Lücke“. Heute rät das Frontend den Grund aus `coverage_days`.

- **Anforderung:** `MetricResult.reason` als Enum, z. B. `no_history`, `today_missing`, `no_activity`, `watch_not_worn`, `source_unavailable`, optional mit `reason_detail`. Damit lassen sich die Texte fachlich korrekt wählen.

### 2.4 Datenstand pro Kachel

Designregel: *Ein alter Wert sieht nie aus wie ein frischer.* Veraltete Kacheln zeigen die Uhrzeit der Daten in der Fußzeile.

- **Anforderung:** `MetricResult.data_as_of` ist der Zeitstempel der jüngsten Messung, die in den Wert eingeflossen ist. `as_of` ist nur ein Datum und reicht dafür nicht.

### 2.5 Anzeige-Einheiten

- **Beobachtung:** `unit` enthält interne Kürzel wie `trimp_pt`, `hours`, `ratio` oder `ctl_atl_tsb`. Das Frontend übersetzt sie heute selbst in `modules.ts`.
- **Anforderung (niedrig):** Ein zusätzliches Feld `display_unit` (`TRIMP`, `h`, `ms`, `bpm`, `""`) oder eine dokumentierte, feste Liste.

### 2.6 Status-Schwellen an einer Stelle

Die Stufen neutral, Aufmerksamkeit und Abweichung (z. B. TSB < −20 → Abweichung, Schlafschuld 2–5 h → Aufmerksamkeit) stehen heute in `web/src/lib/modules.ts`. Der Agent formuliert im Chat dieselben Einordnungen. Das sollte nicht auseinanderlaufen.

- **Anforderung:** `MetricResult.status: { tone: "neutral"|"attention"|"deviation", label: str } | null`, berechnet im Backend, von Agent und Frontend gemeinsam genutzt. Das Frontend fällt auf seine eigenen Regeln zurück, solange das Feld fehlt.

### 2.7 Kachel-Layout: Größe und Kacheln ohne Metrik

- **Anforderung:** `PUT/GET /api/dashboard/layout` speichert pro Kachel zusätzlich `size: { w: 1|2, h: 1|2 }`. Das Design zeigt dafür „1 × 1“ und einen Griff zum Größe-Ändern in der Bearbeiten-Ebene; das ist im Frontend schon vorbereitet.
- **Anforderung:** `module_id` muss auch Kacheln ohne Metrik-Endpunkt akzeptieren: `activities_table`, `calendar_next`, `weekly_outlook`, `training_heatmap` (siehe P3).

### 2.8 Garmin-Ablaufzeit im Fehlertext

Das Design formuliert: „Seit Samstag, 14:10 kommen keine neuen Werte.“

- **Status:** `connection.reauth_since` ist vorhanden. Bitte sicherstellen, dass es bei `GET /api/connections` mit Uhrzeit (UTC, ISO) mitkommt. Dann zieht das Frontend nach. *Kein neuer Endpunkt nötig.*

---

## P3 · Neue Kacheltypen

### 3.1 Verlaufskurve (Sparkline), z. B. HRV der letzten 30 Nächte

- **Vorhanden:** `GET /api/data/wellness/{metric}` liefert Rohpunkte mit `observed_at`, `value` und `quality`.
- **Fehlt:** eine *Tagesreihe* mit expliziten Lücken. Die Kachel braucht einen Wert pro Nacht oder Tag, und `null` für fehlende Tage, damit die Linie dort unterbrochen und schraffiert wird.
  ```
  GET /api/metrics/{metric_id}/series?days=30
  → { "points": [{ "date": "2026-09-06", "value": 61 | null }, …],
      "normal_range": { …wie 2.1… } }
  ```
- Messwerte mit `quality = 'suspect'` gehören nicht in die Reihe. Das deckt sich mit dem offenen Punkt aus der Phase-1-Härtung.

### 3.2 Zeitreihe mit Achsen: Trainingsbelastung über 6 Wochen

- **Fehlt:** CTL, ATL und TSB als Tagesreihe. Laut HANDOVER liefert `training_load` nur Tages-Snapshots.
  ```
  GET /api/metrics/training_load/series?days=42
  → { "points": [{ "date": "…", "ctl": 48.1, "atl": 55.0, "tsb": -6.9 } | { "date": "…", "ctl": null, … }] }
  ```
- Lücken sind `null` (z. B. „12.–18. Sep ohne Aktivitätsdaten“).

### 3.3 Zeitreihe Ruhepuls über 6 Monate

- **Fehlt:** wöchentliche Ruhepuls-Mittelwerte mit Band. Gleiches Format wie 3.1, nur mit `bucket=week`.

### 3.4 Kennzahl Schlaf: Nächte der Woche

- **Vorhanden:** `GET /api/data/sleep` liefert Sitzungen.
- **Fehlt:** eine Nacht-Zusammenfassung pro Kalendertag, inklusive Nächten ohne Uhr als `null`. Dazu der Wochenschnitt und das Band.
  ```
  GET /api/metrics/sleep_duration/series?days=7 → { points: [{ date, hours | null }], avg, normal_range }
  ```

### 3.5 Rundanzeige „Bereitschaft“ (0–100)

- **Fehlt komplett:** ein Gesamtwert aus Schlaf, HRV und Belastung.
- **Anforderung:**
  - Neue Metrik `readiness` mit `value` 0–100 und `normal_range`.
  - Dazu `sources: [{ name: "hrv", available: false }, …]` für die Fußzeile („aus 2 von 3 Quellen · HRV fehlt heute Nacht“).
  - Leer-Zustand erst nach drei Nächten.
- **Hinweis:** Die Formel ist eine fachliche Entscheidung und braucht eine eigene Spezifikation.

### 3.6 Tabelle „Letzte Aktivitäten“ (7 Tage)

- **Vorhanden:** `GET /api/data/activities` mit `name`, `sport`, `start_at`, `distance_m`, `duration_s` und `avg_hr`. Das reicht fast aus.
- **Fehlt:**
  - Filter `from_date`/`to_date`; heute gibt es nur Cursor-Paginierung.
  - Ein deutscher Anzeigename für `sport`.
  - `avg_hr: null` muss klar „ohne Herzfrequenz“ bedeuten. Laut Design heißt die Fußzeile dann „2 Aktivitäten ohne Herzfrequenz“.

### 3.7 Verteilung: HF-Zonen der Woche mit Pulsgrenzen

- **Vorhanden:** `hr_zone_distribution` pro Tag in Sekunden, mit Prozent-Grenzen.
- **Fehlt:**
  - Wochen-Aggregat (`window=7d`).
  - Zonengrenzen in bpm aus HFmax bzw. Nutzereinstellung, z. B. `zones: [{ id: "z1", lower_bpm: null, upper_bpm: 128, seconds }]`.
  - Die Zeit *ohne* Pulsmessung (`seconds_without_hr`); das Design zeigt sie als schraffierte Zeile.
  - Die Zahl der Aktivitäten als Grundlage.

### 3.8 Heatmap „Trainingsjahr“ (12 Monate)

- **Fehlt:** Trainingsminuten pro Tag über 365 Tage, mit Unterscheidung von *0 Minuten trainiert* und *keine Daten*. Im Design wird „keine Daten“ als hohler Kreis gezeichnet.
  ```
  GET /api/data/training_days?days=365 → { days: [{ date, minutes | null }], sessions: 184 }
  ```
- Während eines laufenden Backfills soll die Fußzeile „Import läuft · 5 von 12 Monaten“ zeigen können. Der Fortschritt kommt aus `/api/sync/status`; der Bezug von Kind zu Zeitraum sollte dort ablesbar sein.

### 3.9 Kalenderausschnitt „Als Nächstes“ (heute, morgen)

- **Vorhanden:** `GET /api/calendar/events` (Google) und die Planblöcke aus Phase 5.
- **Fehlt:** ein zusammengeführter Endpunkt für die nächsten 48 Stunden, der Kalendertermine und Kairos-Planblöcke gemeinsam liefert, jeweils mit `source: "google" | "apple" | "kairos"` und `kind: "plan" | "external"`. Das Design unterscheidet Plan (offener Kreis) und fremden Termin (gefüllter Punkt).
- Teilweise-Fall: „nur Google · Apple nicht verbunden“. Dafür braucht es eine Liste der verbundenen Kalenderquellen. Apple oder CalDAV ist laut Phase 3 bewusst noch nicht umgesetzt.

### 3.10 Textblock „Wochenausblick“

- **Fehlt komplett:** ein vom Agenten erzeugter Text, sonntags um 18:00 automatisch oder auf Knopfdruck („Jetzt erstellen lassen“).
- **Format** mit Belegen, damit das Frontend Zahlen als Beleg-Chips mit gepunkteter Unterstreichung darstellen kann:
  ```json
  { "created_at": "…", "segments": [
      { "text": "Letzte Woche: " },
      { "text": "5:22 h Training", "evidence": { "metric": "training_time", "from": "…", "to": "…" } }
    ],
    "missing_sources": ["calendar"] }
  ```
- `missing_sources` steuert die Fußzeile („ohne Kalender erstellt · Google nicht erreichbar“).

---

## P3 · Agent und Chat

### 4.1 Beleg-Chips in Agent-Antworten

Designregel: *Jede Zahl in Agent-Antworten trägt eine gepunktete grüne Unterstreichung.* Beim Darüberfahren erscheinen Quelle und Zeitraum, ein Klick öffnet den Verlauf.

- **Anforderung:** Assistant-Nachrichten kommen zusätzlich zu `content` als `segments` im Format aus 3.10, mit Evidence pro Zahl: Metrik, Zeitraum und Aggregation (z. B. „Ø aus 28 Nächten“).
- Dazu eine Zeile „nicht mitgerechnet“: `excluded: ["2 Nächte ohne Uhr"]`.
- Werkzeug-Hinweise: Die Tool-Calls sollen den abgefragten Zeitraum in lesbarer Form mitliefern (z. B. „Schlaf · 15.08.–13.09.“), damit das Frontend „abgeschlossen/laufend“ anzeigen kann.

### 4.2 Streaming

Das Design zeigt eine Antwort, die während des Erzeugens erscheint („Antwort · streamt“). Heute antwortet `send` erst nach der vollständigen Antwort.

- **Anforderung:** SSE- oder Streaming-Endpunkt für Assistant-Antworten.

### 4.3 Kontext-Chips beim Fragen

„Dazu fragen →“ übergibt heute nur eine Textfrage (`/chat?q=…`). Das Design zeigt einen Kontext-Chip im Eingabefeld, z. B. „HRV · letzte 30 Tage“.

- **Anforderung:** Der Sende-Endpunkt nimmt optional `context: [{ metric, from, to }]` an, das der Agent als gesetzten Bezug behandelt.

### 4.4 Vorschlagskarte: bestätigt, verworfen, rückgängig

Das Design zeigt nach der Entscheidung einen Protokolleintrag mit Uhrzeit und „Rückgängig“. Eine verworfene Karte sagt ausdrücklich, dass nichts gespeichert wurde.

- **Anforderung:**
  - Der Entscheidungsstatus einer Proposal wird pro Konversation gespeichert (`proposed | confirmed | discarded`, `decided_at`).
  - Die Karte zeigt das Ziel als Pflichtangabe (z. B. „Google Kalender · privat“).
  - Für bestätigte Kalendereinträge gibt es einen Rückgängig-Weg; `DELETE /api/calendar/events/{id}` reicht, wenn die Event-ID in der Bestätigung zurückkommt.

### 4.5 Gedächtnis-Notizen

Die Notizkarten im Design haben Ablaufdatum, Kategorie und Herkunft, und abgelaufene Notizen werden eigens angezeigt.

- **Anforderung:**
  - `MemoryEntry` bekommt `expires_at` (optional), `category` (z. B. „Einschränkungen“) und `status: active | proposed | expired`.
  - Agent-Vorschläge („Vorschlag des Agenten“) sind *vorgeschlagen*, bis der Nutzer sie annimmt.
- **Hinweis:** `agent-harness-v2` ändert gerade Gedächtnis-Code. Bitte dort mit abstimmen.

---

## Bereits vorhanden, kein Handlungsbedarf

- `GET /api/connections` mit `status`, `last_ok_at` und `reauth_since`: Daraus berechnet das Frontend den Aktualitätsindikator im Kopf (aktuell, Abgleich läuft, veraltet, abgelaufen).
- `GET /api/sync/status` mit `windows_processed` und `windows_total`: liefert „Abgleich läuft · 2 von 4“.
- `GET /api/metrics/{id}` für die acht Module, `POST /api/metrics/recompute`, `GET/PUT /api/dashboard/layout` (ohne Größe, siehe 2.7).

## Vorgeschlagene Reihenfolge

1. **P1.1–1.3:** sichtbare Widersprüche, klein und unabhängig.
2. **2.1 Normalbereich + 2.2 Lückenmaske:** trägt die Kernregel des Designs und schaltet die Lage-Leiste frei.
3. **3.1 Tagesreihen-Endpunkt:** ein generischer Endpunkt deckt 3.1, 3.3 und 3.4 ab; 3.2 folgt mit demselben Muster.
4. **2.3, 2.4, 2.6:** feinere Zustände und eine gemeinsame Status-Logik mit dem Agenten.
5. **3.5–3.10 und 4.x:** neue Kacheln und Agent-Funktionen, jeweils mit eigener Spezifikation.
