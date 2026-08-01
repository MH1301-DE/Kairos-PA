# 02 — Datenmodell & Volumenanalyse

## 1. Die Kernfrage: Wie viele Garmin-Datenpunkte sind es wirklich?

### 1.1 Erhebungsraster pro Datentyp

Garmin liefert über die Connect-API pro Tag und Nutzer im Wesentlichen folgende
Zeitreihen. Die Raster stammen aus der beobachteten Praxis moderner Geräte
(Forerunner/Fenix/Venu-Klasse); ältere oder sparsamer konfigurierte Geräte liefern
weniger.

| Datentyp | Typisches Raster | Punkte/Tag |
|---|---|---|
| Herzfrequenz (ganztägig) | ~2 min | ~720 |
| Stress-Level | ~3 min | ~480 |
| Body Battery | ~3 min | ~480 |
| Atemfrequenz | ~2 min | ~720 |
| SpO₂ (v. a. nachts) | ~1–2 min über ~8 h | ~300 |
| Schritte | 15-min-Buckets | 96 |
| Schlafphasen (Level-Events) | Ereignisbasiert | ~40 |
| HRV (nächtlich) | 5 min über ~8 h | ~96 |
| Tages-Summaries | 1×/Tag, ~40 Felder | ~40 |
| Training Status / Readiness / VO₂max | 1–3×/Tag | ~10 |
| **Summe Wellness** | | **≈ 2.980** |

**≈ 3.000 Messpunkte pro Nutzer und Tag.**

Hinzu kommen Aktivitäten:

| Element | Annahme | Volumen |
|---|---|---|
| Aktivitäten pro Jahr | 250 | — |
| Datensätze je Aktivität (1 Hz, ⌀ 55 min) | ~3.300 Records | ~825.000/Jahr |
| Felder je Record | 8–14 (HR, Kadenz, Pace, Alt, Lat/Lon, Power, Temp) | — |
| FIT-Dateigröße | ⌀ 200 KB | ~50 MB/Jahr |

### 1.2 Hochrechnung

**Pro Nutzer und Jahr**

```
Wellness-Zeitreihen :   3.000/Tag × 365      ≈  1.095.000 Zeilen
Aktivitäts-Records  :   250 × 3.300          ≈    825.000 Zeilen
                                             ─────────────────────
                                             ≈  1.920.000 Zeilen/Jahr
```

**Für 5 Nutzer über 5 Jahre: ≈ 48 Mio. Zeilen.**

### 1.3 Speicherbedarf

Narrow-Schema (`user_id, ts, metric_id, value`) belegt in Postgres inkl.
Tupel-Header und Index grob 90–110 Byte pro Zeile.

```
Roh (unkomprimiert) : 48 Mio × 100 B                    ≈  4,8 GB
Nach Timescale-Kompression (typ. Faktor 10–20 bei
gleichförmigen numerischen Zeitreihen)                  ≈  0,3 – 0,5 GB
FIT-Dateien         : 5 Nutzer × 5 J × 50 MB            ≈  1,3 GB
Raw-JSON-Archiv gzip: ~0,4 MB/Nutzer/Tag × 5 × 1.825    ≈  3,7 GB
Derived / Aggregate / Indizes / Overhead                ≈  2   GB
                                                        ──────────
Gesamt über 5 Jahre                                     ≈  7 – 9 GB
```

### 1.4 Fazit

> **Alles speichern. Ohne Einschränkung, ohne Downsampling, ohne Retention-Regel.**

Die kompletten Rohdaten aller 5 Nutzer über 5 Jahre passen in unter 10 GB. Eine
Standard-VM mit 160 GB SSD ist damit zu ca. 6 % belegt. Die Frage nach selektiver
Speicherung stellt sich schlicht nicht.

**Die relevanten Grenzen liegen woanders:**

| Scheinbare Grenze | Tatsächliche Grenze |
|---|---|
| Speicherplatz | ✅ unkritisch |
| Query-Performance über 48 Mio. Zeilen | ⚠️ relevant → Timescale Hypertables + Continuous Aggregates |
| **Garmin-Rate-Limits beim Erstimport** | 🔴 **der eigentliche Engpass** |
| Kontextfenster des Agenten | 🔴 **der zweite eigentliche Engpass** |

Der Backfill von 12 Monaten Historie erzeugt bei 5 Nutzern etwa 1.800
Tages-Abrufe × 8 Endpunkte ≈ **14.000 API-Requests**. Bei einem konservativen
Limit von 1 Request alle 2 s sind das ~8 Stunden reine Laufzeit. Deshalb: Backfill
als eigener, gedrosselter, unterbrechbarer Jobtyp, verteilt über mehrere Nächte.
Details in [04 — Integrationen](04-integrationen.md#garmin).

---

## 2. Datenmodell

### 2.1 Überblick

```
identity          health                        calendar / planning
─────────         ──────────────────────        ────────────────────
app_user          activity                      calendar_account
user_setting      activity_record  (hyper)      calendar_event
connection        wellness_sample  (hyper)      plan
oauth_token       sleep_session                 plan_block
                  daily_summary                 proposal
                  body_composition
agent             derived                       platform
─────────         ──────────────────────        ────────────────────
conversation      metric_daily                  raw_payload
message           load_state                    sync_state
memory (vector)   hr_zone_daily                 sync_failure
tool_registry                                   audit_log
```

### 2.2 Zentrale Entscheidung: Narrow vs. Wide für Zeitreihen

**Gewählt: Narrow (`metric_id`, `value`) für Wellness, Wide für Aktivitäts-Records.**

| | Narrow | Wide |
|---|---|---|
| Neue Metrik hinzufügen | Zeile in `metric_def` | Schema-Migration |
| Speicher | +30 % | Baseline |
| Query über eine Metrik | sehr gut | sehr gut |
| Query über 10 Metriken gleichzeitig | Pivot nötig | trivial |

Wellness-Metriken kommen ständig neu hinzu (jedes Garmin-Update bringt etwas) →
Narrow gewinnt klar, weil Erweiterbarkeit eine Kernanforderung ist.
Aktivitäts-Records dagegen haben ein stabiles, breites Feldset und werden fast immer
gemeinsam gelesen → Wide.

### 2.3 Kanonische Kernobjekte

**`wellness_sample`** — Hypertable, partitioniert nach Zeit, komprimiert ab 7 Tagen.

```
user_id     uuid
ts          timestamptz
metric_id   smallint   → FK metric_def (hr, stress, body_battery, spo2, …)
value       real
source      smallint   → FK data_source (garmin, manual, apple_health, …)
```

Primärschlüssel `(user_id, metric_id, ts, source)`. `source` ist Teil des Keys,
damit dieselbe Metrik aus zwei Quellen koexistieren kann, ohne sich zu überschreiben.

**`activity`** — eine Zeile pro Trainingseinheit, denormalisierte Summary-Felder für
schnelle Abfragen (Distanz, Dauer, ⌀HF, max HF, Höhenmeter, TRIMP, Typ, Ort).

**`activity_record`** — Hypertable mit den Sekundendaten. Wird selten gelesen,
deshalb aggressive Kompression ab 1 Tag.

**`sleep_session`** — eine Zeile pro Nacht mit Phasen-Dauern, Score, ⌀HRV, ⌀Atmung,
plus die Level-Events als JSONB (klein genug, keine eigene Tabelle wert).

**`calendar_event`** — anbieterunabhängig; `external_id` + `calendar_account_id`
als Unique-Key. `etag`/`sequence` für Konfliktauflösung. `origin` markiert, ob das
Event vom System erzeugt wurde (relevant für Rückschreib-Schleifenschutz).

**`proposal`** — vorgeschlagene, noch nicht ausgeführte Schreibaktion.
Status: `pending → confirmed → executed | rejected | expired | failed`.
Enthält `idempotency_key` und den vollständigen geplanten Payload.

### 2.4 Derived Layer

`metric_daily` — eine Zeile pro `(user_id, date, metric)`, materialisiert:
Ruhepuls, HRV-Nachtmittel, Schlafdauer/-score, Stressmittel, Body-Battery-Min/Max,
Schritte, Trainings-TRIMP, CTL/ATL/TSB, ACWR.

Das ist die Tabelle, aus der **fast alle Agent-Antworten kommen** — eine Zeile pro
Tag, ~25 Spalten, für 5 Jahre und 5 Nutzer nur ~9.000 Zeilen. Damit sind
Jahresvergleiche eine Millisekunden-Query und passen als Ergebnis in wenige hundert
Tokens.

`hr_zone_daily` — Sekunden je HR-Zone pro Tag.

Beide werden über Timescale **Continuous Aggregates** bzw. nächtliche Recompute-Jobs
gepflegt und sind vollständig aus der Canonical-Zone rekonstruierbar.

### 2.5 Raw-Zone

```
raw_payload(
  id, user_id, connector, endpoint, fetched_at,
  window_start, window_end,
  payload_gzip bytea,      -- oder Pfad in den Object Store bei > 1 MB
  content_hash text        -- dedupliziert wiederholte identische Antworten
)
```

`content_hash` verhindert, dass ein täglicher Re-Fetch derselben unveränderten
Woche das Archiv aufbläht.

### 2.6 Mandantenfähigkeit

**Jede** fachliche Tabelle trägt `user_id`. Durchsetzung über Postgres
Row-Level-Security:

```sql
ALTER TABLE wellness_sample ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON wellness_sample
  USING (user_id = current_setting('app.current_user_id')::uuid);
```

Die Anwendung setzt `SET LOCAL app.current_user_id` beim Transaktionsbeginn. Ein
vergessener `WHERE user_id = …` im Code führt damit zu **null Zeilen**, nicht zu
einem Datenleck. Das ist der Grund, warum RLS trotz kleiner Nutzerzahl gesetzt wird:
Der Agent generiert dynamische Abfragen, und dort ist ein vergessener Filter eine
realistische Fehlerquelle.

### 2.7 Zeit und Zeitzonen

- **Alles in der DB ist `timestamptz` in UTC.** Ausnahmslos.
- Jeder Nutzer hat eine `home_timezone`; jede Aktivität zusätzlich die
  `local_timezone` zum Zeitpunkt der Aufzeichnung (Reisen!).
- Tagesgrenzen für Aggregate richten sich nach der lokalen Zeitzone, nicht nach UTC —
  sonst wandern Schlafnächte über Zeitzonenwechsel in den falschen Tag.
- Schlaf wird dem **Aufwachtag** zugeordnet (Konvention wie bei Garmin), explizit
  dokumentiert, weil es sonst zu unerklärlichen Off-by-one-Effekten führt.

### 2.8 Datenqualität

Jeder Canonical-Record trägt:

- `source` — woher
- `ingested_at` — wann importiert
- `quality` — `ok | partial | suspect`

`suspect` wird gesetzt bei physiologisch unplausiblen Werten (HF < 25 oder > 230,
SpO₂ < 70 %, Schlaf > 16 h). Diese Werte werden **nicht gelöscht**, aber aus
Aggregaten ausgeschlossen und dem Agenten gegenüber als solche gekennzeichnet.

### 2.9 Retention

Da Volumen kein Argument ist, gilt:

| Zone | Retention |
|---|---|
| Canonical | unbegrenzt |
| Derived | unbegrenzt (rebuildbar) |
| Raw-Payloads | unbegrenzt, komprimiert; optional Prune nach 24 Monaten |
| FIT-Dateien | unbegrenzt |
| Agent-Konversationen | 24 Monate, danach nur die extrahierten Memories |
| Audit-Log | 24 Monate |

Der einzige echte Löschfall ist der **Nutzerlöschwunsch** — dann kaskadierend über
`user_id`, inkl. Object Store und Backups-Vermerk ([06](06-sicherheit-und-datenschutz.md)).

---

## 3. Performance-Leitplanken

| Query | Zielzeit | Mittel |
|---|---|---|
| Tagesübersicht heute | < 50 ms | `metric_daily`, PK-Lookup |
| 12-Monats-Trend einer Metrik | < 150 ms | `metric_daily`, 365 Zeilen |
| HR-Kurve einer Aktivität | < 300 ms | `activity_record`, Zeitbereichs-Scan |
| Ganzjahres-Zonenverteilung | < 200 ms | `hr_zone_daily` |
| Korrelationsanalyse 2 Metriken/2 Jahre | < 1 s | `metric_daily` in Pandas |

**Regel für Tool-Implementierungen:** Kein Agent-Tool liest je direkt aus
`wellness_sample` oder `activity_record` ohne enge Zeitbegrenzung. Der Default ist
immer die Derived-Zone.
