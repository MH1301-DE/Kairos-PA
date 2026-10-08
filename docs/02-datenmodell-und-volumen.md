# 02 — Datenmodell & Volumenanalyse

> **Stand 2026-10-08.** Abschnitt 1 enthält jetzt Messwerte aus der Entwicklungs-DB
> (1 Nutzer). Abschnitt 2 beschreibt die tatsächlich existierenden Tabellen; nicht
> gebaute Teile des ursprünglichen Entwurfs sind als **Zielbild (nicht umgesetzt)**
> markiert.

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
| Datensätze je Aktivität (1 Hz, ⌀ 55 min) | ~3.300 Zeitpunkte | — |
| Kanäle je Zeitpunkt | 7 befüllt (HR, Speed, Höhe, Lat, Lon, Kadenz, Power); mit `distance_m` 8 | — |
| `activity_record`-Zeilen je Aktivität (narrow, eine Zeile je Kanal) | **gemessen ≈ 15.800** (2,15 Mio. / 136) | ~3,9 Mio./Jahr |
| FIT-Dateien | werden **nicht** gespeichert; nur dekodiertes gzip-JSON, gemessen ⌀ 155 KB je Aktivität | ~39 MB/Jahr |

Die ursprüngliche Annahme „eine Zeile je Zeitpunkt“ (wide) trifft nicht zu:
`activity_record` ist narrow, jede Zeile trägt **einen** Kanal. Dadurch entstehen pro
Aktivität rund 5× so viele Zeilen wie ursprünglich gerechnet.

### 1.2 Hochrechnung

**Pro Nutzer und Jahr**

```
Wellness-Zeitreihen :   gemessen ≈ 1.600/Tag × 365   ≈    580.000 Zeilen
                        (Annahme oben: 3.000/Tag    ≈  1.095.000 Zeilen)
Aktivitäts-Records  :   250 × 15.800                ≈  3.950.000 Zeilen
                                                    ─────────────────────
                                                    ≈  4,5 – 5,0 Mio. Zeilen/Jahr
```

**Für 5 Nutzer über 5 Jahre: ≈ 115–125 Mio. Zeilen**, davon ≈ 100 Mio.
`activity_record` (mit `distance_m` ≈ 110 Mio.).

### 1.3 Speicherbedarf

**Messung (2026-10-08, Entwicklungs-DB, 1 Nutzer).** `pg_total_relation_size`
liefert für Hypertables nur die leere Elterntabelle, daher `hypertable_size`:

| Tabelle | Größe inkl. Indizes | Zeilen | Bytes/Zeile | Bezug |
|---|---:|---:|---:|---|
| `activity_record` | 480,5 MB | 2.145.493 | **224** | 136 Aktivitäten → **3,5 MB je Aktivität** |
| `wellness_sample` | 65,5 MB | 254.543 | 257 | 160 Tage → ≈ 410 KB je Tag |
| `raw_payload` | 32,9 MB | 7.488 | — | davon `activity_fit` 21,0 MB (≈ 155 KB je Aktivität); Rest ≈ 16 KB je Tag |
| Datenbank gesamt | 599 MB | | | |

Timescale-Kompression ist **nicht** einsetzbar: Sie ist mit Row-Level-Security
inkompatibel (timescale/timescaledb#6827). Die ursprüngliche Rechnung mit Faktor
10–20 entfällt damit.

**Hochrechnung** (5 Nutzer, 5 Jahre; `activity_record` mit `distance_m` als achtem
Kanal ≈ 4,0 MB je Aktivität):

```
                                   Doku-Szenario         reale Rate
                                   250 Akt./Jahr         ≈ 96 Akt./Jahr
activity_record                    6.250 × 4,0 MB ≈ 25 GB    2.400 × 4,0 MB ≈ 9,6 GB
wellness_sample                    25 Nutzerjahre × 150 MB ≈ 3,7 GB (in beiden)
raw_payload (gzip-JSON)            ≈ 1,1 GB              ≈ 0,5 GB
Derived, Agent, Kalender, Rest     < 0,5 GB              < 0,5 GB
                                   ─────────             ─────────
Gesamt über 5 Jahre                ≈ 30 GB               ≈ 14 GB
```

Die frühere Angabe „7–9 GB gesamt“ ist damit um den Faktor 2–4 zu niedrig. Die
Wellness-Rate ist gemessen (≈ 1.600 Zeilen/Tag); mit dem Rasteransatz aus §1.1
(3.000/Tag) kämen ≈ 3,3 GB hinzu. Die geplanten Tabellen `activity_stats`,
`activity_split` und `activity_best_effort` ([Spec]({SPEC}) Teil B) sind
im Vergleich vernachlässigbar.

### 1.4 Fazit

> **Alles speichern. Ohne Einschränkung, ohne Downsampling, ohne Retention-Regel —
> aber die VM entsprechend dimensionieren.**

Die kompletten Daten aller 5 Nutzer über 5 Jahre brauchen **≈ 14 GB (reale Rate)
bis ≈ 30 GB (Doku-Szenario)**, dominiert von `activity_record`. Auf einer VM mit
40 GB SSD (Hetzner CX22, siehe [07](07-deployment-und-betrieb.md#22-empfehlung))
bleibt im Doku-Szenario nach Betriebssystem, Docker-Images und lokalen Backups kein
Puffer; mit 80 GB oder mehr ist Speicher unkritisch. Falls Platz knapp wird, ist der
naheliegende Hebel `activity_record` (z. B. Kanäle `lat_deg`/`lng_deg` nur für
Karten, oder ein Wide-Schema), nicht die Wellness-Daten.

**Die relevanten Grenzen liegen woanders:**

| Scheinbare Grenze | Tatsächliche Grenze |
|---|---|
| Speicherplatz | ⚠️ unkritisch bei passender VM-Größe (siehe oben) |
| Query-Performance über ≈ 120 Mio. Zeilen | ⚠️ relevant → Timescale Hypertables + plain Derived-Tabellen (Continuous Aggregates sind mit RLS nicht nutzbar) |
| **Garmin-Rate-Limits beim Erstimport** | 🔴 **der eigentliche Engpass** |
| Kontextfenster des Agenten | 🔴 **der zweite eigentliche Engpass** |

Der Backfill (Default 24 Monate) läuft in Tagesfenstern je Kind: 730 Fenster × 10
Kinds ≈ **7.300 Fenster je Nutzer**, plus ein FIT-Download je Aktivität. Bei 1,5 s
Pause zwischen Fenstern sind das ≈ 3 h reine Wartezeit je Nutzer, zuzüglich der
Request-Zeiten. Der Backfill ist ein manuell ausgelöster, gedrosselter,
fortsetzbarer Job (Cursor in `sync_state`); einen nächtlichen Zeitplan gibt es nicht.
Details in [04 — Integrationen](04-integrationen.md#garmin).

---

## 2. Datenmodell

### 2.1 Überblick

**Ist-Stand** (alle Tabellen im Schema `public`, Stand Migration `7a1c2e9d4b30`):

```
identity             health                          calendar / planning
──────────           ──────────────────────────      ────────────────────
app_user             activity                        calendar_event
user_setting         activity_record    (hyper)      plan
connection           wellness_sample    (hyper)      plan_block
data_source          sleep_session                   goal
                     daily_summary
                     metric_def
                     custom_metric_definition
agent                derived                         platform / UI
──────────           ──────────────────────────      ────────────────────
conversation         metric_daily_value              raw_payload
conversation_message wellness_daily_stats            sync_state
agent_memory         hr_bucket_seconds_daily         sync_failure (ungenutzt)
                                                     user_dashboard_tile
```

- **OAuth-Tokens** (Garmin, Google) liegen verschlüsselt in
  `connection.credentials_enc`, nicht in einer eigenen `oauth_token`-Tabelle.
- **Existieren nicht** (Zielbild bzw. ersetzt): `proposal` (ersetzt durch
  `conversation_message.tool_calls` + `tool_call_id`), `tool_registry`,
  `metric_daily` (ersetzt durch die drei Derived-Tabellen), `memory (vector)`
  (ersetzt durch `agent_memory` ohne Embeddings), `load_state` (CTL/ATL/TSB werden
  zur Abfragezeit berechnet), `hr_zone_daily` (ersetzt durch
  `hr_bucket_seconds_daily`), `calendar_account`, `body_composition`, `audit_log`.
- **Geplant** laut [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md): `activity_stats`,
  `activity_split`, `activity_best_effort`, `garmin_workout`,
  `garmin_workout_schedule`, `proposal_snapshot`.

### 2.2 Zentrale Entscheidung: Narrow vs. Wide für Zeitreihen

**Ist-Stand: Narrow für beides** — `wellness_sample` (`metric_id`, `value`) und
`activity_record` (`metric` als Text-Code, `value`; `src/kairos/db/models.py:320-346`).

Der ursprüngliche Entwurf sah *Wide* für Aktivitäts-Records vor; gebaut wurde narrow.

| | Narrow | Wide |
|---|---|---|
| Neue Metrik hinzufügen | Zeile in `metric_def` | Schema-Migration |
| Speicher | +30 % | Baseline |
| Query über eine Metrik | sehr gut | sehr gut |
| Query über 10 Metriken gleichzeitig | Pivot nötig | trivial |

Wellness-Metriken kommen ständig neu hinzu (jedes Garmin-Update bringt etwas) →
Narrow gewinnt klar, weil Erweiterbarkeit eine Kernanforderung ist. Für
Aktivitäts-Records wurde aus demselben Grund narrow gebaut (ein neuer FIT-Kanal wie
`distance_m` ist ein `metric_def`-Seed statt einer Migration). Der Preis ist der
Speicher: gemessen 224 B je Zeile und ≈ 15.800 Zeilen je Aktivität (§1.3). Gelesen
wird `activity_record` nur von Ableitungen, nie direkt von Agent-Tools.

### 2.3 Kanonische Kernobjekte

**`wellness_sample`** — Hypertable, partitioniert nach `observed_at`, **ohne
Kompression** (mit RLS nicht nutzbar).

```
id              bigint
user_id         uuid
metric_id       integer  → FK metric_def (hr, stress, body_battery, spo2, …)
data_source_id  integer  → FK data_source (nullable; heute nicht befüllt)
observed_at     timestamptz
value           double precision
quality         varchar(16), Default 'ok'
raw_payload_id  integer  → FK raw_payload
```

Primärschlüssel `(id, observed_at)` (Timescale verlangt die Partitionsspalte im PK),
Unique `(user_id, metric_id, observed_at)`. Die Quelle ist **nicht** Teil des Keys;
`data_source` ist heute leer.

**`activity`** — eine Zeile pro Trainingseinheit, Summary-Felder aus Garmins
`activity_list`: `external_id` (Garmin-`activityId`), `name`, `sport` (Garmin-
`typeKey`), `start_at`, `end_at`, `distance_m`, `duration_s`, `avg_hr`, `max_hr`,
`elevation_gain_m`, `calories`. Unique `(user_id, external_id)`. Bekannte Mängel
(Ist): `activity_type` ist immer NULL, Zeitzone/lokale Startzeit fehlen, der Upsert
aktualisiert `start_at`/`end_at` nicht, `fit_object_key` ist ungenutzt. Geplant
([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) A.1): `sport_profile`, `garmin_type_id`, `garmin_parent_type_id`,
`description`, `start_local`, `utc_offset_min`, `moving_duration_s`, `avg_speed_mps`,
`lap_count`, `garmin_training_load`, `garmin_vo2max`, `deleted_at`, `deleted_reason`;
`activity_type` entfällt.

**`activity_record`** — Hypertable mit den Sekundendaten, narrow (`metric`, `value`),
**ohne Kompression**. PK `(id, recorded_at)`, Unique
`(user_id, activity_id, recorded_at, metric)`. Wird nur selten gelesen.

**`sleep_session`** — eine Zeile pro Nacht: `external_id`, `start_at`, `end_at`,
`duration_seconds`. Phasen, Score und Level-Events liegen nur im `raw_payload`.

**`calendar_event`** — Unique `(user_id, connector, external_id)`. `source`
markiert, ob das Event von Kairos angelegt wurde (`kairos`) — relevant für den
Schutz vor Rückschreib-Schleifen und für das Löschen. `etag`/`sequence` gibt es nicht.

**Proposals** — keine eigene Tabelle. Ein bestätigungspflichtiger Tool-Call bleibt
in `conversation_message.tool_calls` (JSONB) stehen und wird über `tool_call_id`
bestätigt oder abgelehnt (Agent-Harness v2, siehe [03](03-agent-design.md)). Geplant
ist `proposal_snapshot` mit Vorschau-Karte und Zustandsmaschine
([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) G.1).

### 2.4 Derived Layer

Drei **plain** Tabellen (keine Continuous Aggregates — mit RLS nicht nutzbar),
gepflegt von `src/kairos/repositories/metrics_recompute.py`:

| Tabelle | Inhalt | Schlüssel |
|---|---|---|
| `wellness_daily_stats` | Tages-Ø/Min/Max/Anzahl je Wellness-Metrik | `(user_id, metric_id, day)` |
| `hr_bucket_seconds_daily` | Sekunden je bpm-Bucket pro Tag (Basis für Zonen und TRIMP) | `(user_id, day, bpm_bucket)` |
| `metric_daily_value` | Tageswert je Kennzahl und Variante, z. B. TRIMP, Schlafschuld | `(user_id, metric_id, variant_id, day)` |

Neu berechnet werden sie nach jedem Garmin-Backfill für den geholten Zeitraum und
per `POST /api/metrics/recompute`; einen nächtlichen Job gibt es nicht. CTL/ATL/TSB,
ACWR u. a. werden zur Abfragezeit aus diesen Tabellen berechnet und nicht
gespeichert. Alles ist vollständig aus der Canonical-Zone rekonstruierbar.

**Geplant** ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) Teil B): Aktivitäts-Ableitungen `activity_stats`
(Steckbrief je Aktivität), `activity_split` (km-Splits und Uhr-Runden),
`activity_best_effort` (schnellste Abschnitte über Standarddistanzen, nur Laufen).

### 2.5 Raw-Zone

```
raw_payload(
  id, user_id, connector, kind, fetched_at,
  window_start, window_end,
  payload_gzip bytea,      -- gzip-JSON, immer in der DB
  object_key   text,       -- ungenutzt (kein Object Store)
  content_hash bytea       -- dedupliziert wiederholte identische Antworten
)
-- Unique (user_id, connector, kind, window_start, content_hash)
```

Es gibt **keinen Object Store** und es werden **keine FIT-Dateien** gespeichert —
bei `activity_fit` nur die dekodierten Messages `record`, `session`, `lap` als JSON.
`activity.fit_object_key` und `raw_payload.object_key` sind ungenutzt (0 von 136
Aktivitäten befüllt).

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
- Jeder Nutzer hat eine `home_timezone` (`app_user`, Default `Europe/Berlin`).
  Aktivitäten speichern heute **keine** lokale Zeit. Geplant ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) A.1):
  `start_local` + `utc_offset_min`, weil Garmin die Zeitzone (`timeZoneId`) nur als
  Zahl liefert; der Offset ergibt sich aus `startTimeLocal − startTimeGMT`.
- **Ziel:** Tagesgrenzen für Aggregate nach der lokalen Zeitzone. **Ist (offen):**
  `metrics_recompute.py` und `metrics_data.py` schneiden Tage nach **UTC**
  (`(… AT TIME ZONE 'UTC')::date`). Für Europe/Berlin landen Werte zwischen 0 und
  1/2 Uhr Ortszeit damit im Vortag.
- **Ziel:** Schlaf wird dem **Aufwachtag** zugeordnet (Konvention wie bei Garmin).
  **Ist (offen):** `sleep_hours_range()` ordnet nach dem UTC-Datum des
  Schlafbeginns zu.

### 2.8 Datenqualität

Jeder Canonical-Record trägt:

- `raw_payload_id` — aus welchem Abruf (Herkunft; `data_source_id` existiert,
  ist aber nicht befüllt)
- `created_at` — wann importiert
- `quality` (nur `wellness_sample`, `varchar(16)`, Default `ok`) — `ok | suspect`

**Ist:** `suspect` wird nur für Herzfrequenz gesetzt (HF < 25 oder > 230,
`normalize.py:34-35,57`). Live sind alle 254.543 Zeilen `ok`. Diese Werte werden
nicht gelöscht. **Offen:** Die Tagesaggregate filtern `quality` noch **nicht** —
`suspect`-Werte fließen in `wellness_daily_stats` ein.

*Zielbild (nicht umgesetzt):* weitere Plausibilitätsgrenzen (SpO₂ < 70 %, Schlaf
> 16 h), Status `partial`, Ausschluss aus Aggregaten und Kennzeichnung gegenüber dem
Agenten. Die geplanten Aktivitäts-Ableitungen ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) B.1) filtern von
Beginn an.

### 2.9 Retention

Da Volumen kein Argument ist, gilt:

| Zone | Retention |
|---|---|
| Canonical | unbegrenzt |
| Derived | unbegrenzt (rebuildbar) |
| Raw-Payloads | unbegrenzt, gzip; optional Prune nach 24 Monaten (nicht gebaut) |
| Agent-Konversationen | Ziel 24 Monate, danach nur die extrahierten Memories — **nicht gebaut**, heute unbegrenzt |
| Agent-Gedächtnis | Einträge mit `expires_at` werden beim Turn-Aufbau gelöscht; ohne `expires_at` dauerhaft |

FIT-Dateien und ein Audit-Log gibt es nicht (siehe §2.5 bzw.
[06](06-sicherheit-und-datenschutz.md)).

Der einzige echte Löschfall ist der **Nutzerlöschwunsch** — dann kaskadierend über
`user_id` (`ON DELETE CASCADE`) plus Backups-Vermerk
([06](06-sicherheit-und-datenschutz.md)).

---

## 3. Performance-Leitplanken

| Query | Zielzeit | Mittel |
|---|---|---|
| Tagesübersicht heute | < 50 ms | `wellness_daily_stats` / `metric_daily_value`, PK-Lookup |
| 12-Monats-Trend einer Metrik | < 150 ms | `metric_daily_value`, 365 Zeilen |
| HR-Kurve einer Aktivität | < 300 ms | `activity_record`, Zeitbereichs-Scan |
| Ganzjahres-Zonenverteilung | < 200 ms | `hr_bucket_seconds_daily` |
| Korrelationsanalyse 2 Metriken/2 Jahre | < 1 s | Derived-Tabellen (nicht gebaut) |

Die Zielzeiten sind Planwerte und nicht gemessen.

**Regel für Tool-Implementierungen:** Kein Agent-Tool liest je direkt aus
`wellness_sample` oder `activity_record` ohne enge Zeitbegrenzung. Der Default ist
immer die Derived-Zone.
