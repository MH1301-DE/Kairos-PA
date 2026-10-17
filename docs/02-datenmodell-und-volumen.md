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
| Kanäle je Zeitpunkt | bis zu 9 (HR, Kadenz, Speed, Distanz, Höhe, Leistung, Lat, Lon, Temperatur) | — |
| `activity_stream`-Zeilen je Aktivität (eine Zeile je Kanal, Werte als Array) | **gemessen ≈ 7** (969 / 139) | ~1.750/Jahr |
| FIT-Dateien | Original-ZIP als eigene `raw_payload`-Zeile (`payload_format='fit_zip'`), gemessen ⌀ 86 KB je Aktivität | ~22 MB/Jahr |

Seit Stufe 1 (2026-10-14) liegt jede Sekundenreihe als **ein Array je Kanal** in
`activity_stream` mit gemeinsamer Zeitachse in `activity_stream_axis`. Das frühere
`activity_record` (eine Zeile je Zeitpunkt und Kanal, ≈ 15.800 Zeilen je Aktivität)
ist gelöscht.

### 1.2 Hochrechnung

**Pro Nutzer und Jahr**

```
Wellness-Zeitreihen :   gemessen ≈ 1.600/Tag × 365   ≈    580.000 Zeilen
                        (Annahme oben: 3.000/Tag    ≈  1.095.000 Zeilen)
Aktivitäts-Streams  :   250 × ≈ 7 Kanal-Zeilen      ≈      1.750 Zeilen (Arrays)
```

**Für 5 Nutzer über 5 Jahre: ≈ 15–27 Mio. Zeilen**, fast alle in `wellness_sample`.

### 1.3 Speicherbedarf

**Messung (2026-10-17, Entwicklungs-DB nach Stufe 1, 1 Nutzer, 139 Aktivitäten
vom 11.05.2025 bis 13.10.2026, Ø 63 min).** `pg_total_relation_size` inkl. Indizes
und TOAST:

| Tabelle | Größe | Bezug |
|---|---:|---|
| `activity_stream` + `activity_stream_axis` | 14,0 MB + 2,7 MB | **≈ 0,13 MB je Aktivität** (vorher `activity_record` ≈ 3,5 MB) |
| `raw_payload` | 44 MB | davon `fit_zip` 12 MB (≈ 86 KB je Aktivität); `json_gzip` 27 MB, darin noch die dekodierten FIT-JSON-Archive aus der Zeit vor Stufe 1 (Rückfall, wenn ein ZIP fehlt) |
| `wellness_sample` | 46 MB | 163 Tage → ≈ 280 KB je Tag |
| abgeleitete Aktivitätstabellen | < 1,5 MB | `activity_stats`, `activity_split`, `activity_best_effort`, `activity_step_result` |
| Datenbank gesamt | 123 MB | vorher 599 MB (2026-10-08) |

**Hochrechnung** (5 Nutzer, 5 Jahre):

```
                                   Doku-Szenario         reale Rate
                                   250 Akt./Jahr         ≈ 98 Akt./Jahr
activity_stream + axis             6.250 × 0,13 MB ≈ 0,8 GB   2.450 × 0,13 MB ≈ 0,3 GB
FIT-Archiv (fit_zip)               6.250 × 0,09 MB ≈ 0,6 GB   2.450 × 0,09 MB ≈ 0,2 GB
wellness_sample                    25 Nutzerjahre × 103 MB ≈ 2,6 GB (in beiden)
raw_payload (gzip-JSON)            ≈ 1,1 GB              ≈ 0,5 GB
Derived, Agent, Kalender, Rest     < 0,5 GB              < 0,5 GB
                                   ─────────             ─────────
Gesamt über 5 Jahre                ≈ 5,5 GB              ≈ 4 GB
```

Die Rechnung vom 2026-10-08 (≈ 14–30 GB, dominiert von `activity_record`) ist
damit überholt. Mit dem Rasteransatz aus §1.1 (3.000 Wellness-Zeilen/Tag) kämen
≈ 2,3 GB hinzu.

### 1.4 Fazit

> **Alles speichern. Ohne Einschränkung, ohne Downsampling, ohne Retention-Regel.**

Die kompletten Daten aller 5 Nutzer über 5 Jahre brauchen **≈ 4 GB (reale Rate)
bis ≈ 5,5 GB (Doku-Szenario)**, dominiert von `wellness_sample`. Eine VM mit 40 GB
SSD (Hetzner CX22, siehe [07](07-deployment-und-betrieb.md#22-empfehlung)) reicht
mit Puffer für Betriebssystem, Docker-Images und lokale Backups.

**Die relevanten Grenzen liegen woanders:**

| Scheinbare Grenze | Tatsächliche Grenze |
|---|---|
| Speicherplatz | ⚠️ unkritisch bei passender VM-Größe (siehe oben) |
| Query-Performance | ✅ unkritisch: Sekundendaten einer Aktivität sind ein Array je Kanal, Agent-Tools lesen abgeleitete Tabellen; Tagesaggregate liegen in plain Derived-Tabellen |
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

**Ist-Stand** (alle Tabellen im Schema `public`, Stand Migration `5d2f8a6c1e47`, Branch `stufe1-datenbasis`):

```
identity             health                          calendar / planning
──────────           ──────────────────────────      ────────────────────
app_user             activity                        calendar_event
user_setting         activity_stream_axis            plan
connection           activity_stream                 plan_block
data_source          wellness_sample                 goal
                     sleep_session
                     daily_summary
                     metric_def
                     custom_metric_definition
agent                derived                         platform / UI
──────────           ──────────────────────────      ────────────────────
conversation         metric_daily_value              raw_payload
conversation_message wellness_daily_stats            sync_state
agent_memory         hr_bucket_seconds_daily         sync_failure (ungenutzt)
                     activity_stats                  user_dashboard_tile
                     activity_split
                     activity_best_effort
                     activity_step_result
```

- **OAuth-Tokens** (Garmin, Google) liegen verschlüsselt in
  `connection.credentials_enc`, nicht in einer eigenen `oauth_token`-Tabelle.
- **Existieren nicht** (Zielbild bzw. ersetzt): `proposal` (ersetzt durch
  `conversation_message.tool_calls` + `tool_call_id`), `tool_registry`,
  `metric_daily` (ersetzt durch die drei Derived-Tabellen), `memory (vector)`
  (ersetzt durch `agent_memory` ohne Embeddings), `load_state` (CTL/ATL/TSB werden
  zur Abfragezeit berechnet), `hr_zone_daily` (ersetzt durch
  `hr_bucket_seconds_daily`), `calendar_account`, `body_composition`, `audit_log`.
- **Geplant** laut [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md): `garmin_workout`,
  `garmin_workout_schedule`, `proposal_snapshot`. `activity_record` ist seit Stufe 1
  gelöscht, ebenso die Extension TimescaleDB.

### 2.2 Zentrale Entscheidung: Narrow vs. Arrays für Zeitreihen

**Ist-Stand:** Wellness narrow, Aktivitäten als Arrays.

- `wellness_sample` bleibt narrow (`metric_id`, `value`): Wellness-Metriken kommen
  ständig neu hinzu, eine neue Metrik ist ein `metric_def`-Seed statt einer Migration.
- Sekundendaten einer Aktivität liegen in `activity_stream_axis` (eine Zeile je
  Aktivität: `start_at`, `t_offset_s int[]`, `source`) und `activity_stream` (eine
  Zeile je Aktivität und Kanal: `v4 real[]` bzw. `v8 double precision[]` für
  `lat_deg`/`lng_deg`). Alle Kanäle sind auf dieselbe Achse ausgerichtet, fehlende
  Werte sind `NULL` im Array. Ein neuer Kanal ist ein Eintrag in `STREAM_CHANNELS`
  (`src/kairos/activities/streams.py`), keine Migration.

Arrays statt narrow, weil Sekundendaten nur als ganze Aktivität gelesen werden (von
den Ableitungen und von `activity_analyze`), nie über viele Aktivitäten hinweg. Das
spart gegenüber dem früheren `activity_record` Faktor ≈ 25 an Speicher (§1.3).

### 2.3 Kanonische Kernobjekte

**`wellness_sample`** — normale Tabelle (bis Stufe 1 eine Timescale-Hypertable).

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

Primärschlüssel `id` (normale Tabelle seit Stufe 1; vorher Hypertable mit PK
`(id, observed_at)`), Unique `(user_id, metric_id, observed_at)`. Die Quelle ist **nicht** Teil des Keys;
`data_source` ist heute leer.

**`activity`** — eine Zeile pro Trainingseinheit, Summary-Felder aus Garmins
`activity_list`: `external_id` (Garmin-`activityId`), `name`, `description`, `sport`
(Garmin-`typeKey`), `sport_profile` (`running`, `cycling`, `swimming`, `hiking`,
`generic`), `garmin_type_id`, `garmin_parent_type_id`, `start_at`, `end_at`,
`start_local`, `utc_offset_min`, `distance_m`, `duration_s`, `moving_duration_s`,
`avg_speed_mps`, `avg_hr`, `max_hr`, `elevation_gain_m`, `calories`, `lap_count`,
`garmin_training_load`, `garmin_vo2max`, `fit_payload_id` (→ `raw_payload` mit dem
Original-ZIP) sowie `deleted_at`/`deleted_reason` (`kairos`, `garmin_sync`) für
gelöschte Aktivitäten. Unique `(user_id, external_id)`; der Upsert aktualisiert alle
Summary-Felder.

**`activity_stream_axis` / `activity_stream`** — Sekundendaten als Arrays (§2.2),
geschrieben beim Sync aus dem FIT-ZIP und jederzeit per Reprocess-Job aus dem
Archiv neu baubar.

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

**Aktivitäts-Ableitungen** ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) Teil B), versioniert über
`ACTIVITY_DERIVED_ALGO_VERSION`, berechnet in `src/kairos/activities/derive/` nach jedem
`activity_fit`-Sync, beim Reprocess und am Ende jedes Garmin-Syncs für alle
Aktivitäten mit älterer Version:

| Tabelle | Inhalt | Schlüssel |
|---|---|---|
| `activity_stats` | Steckbrief: Umfang, Pace, HF, Zonen, TRIMP, Höhe, Entkopplung, Abdeckung, `quality` | `activity_id` |
| `activity_split` | km-Splits (Rad 5 km, Schwimmen 100 m) und Uhr-Runden | `(activity_id, kind, idx)` |
| `activity_best_effort` | schnellste Abschnitte über 800 m bis 100 km, nur GPS-Läufe | `(activity_id, distance_key)` |
| `activity_step_result` | Soll/Ist je Ausführung eines Workout-Schritts | `(activity_id, exec_idx)` |

Die Agent-Tools `activity_search`, `activity_get`, `activity_splits`, `best_efforts`
lesen nur diese Tabellen; `activity_analyze` liest zusätzlich die Streams **einer**
Aktivität.

### 2.5 Raw-Zone

```
raw_payload(
  id, user_id, connector, kind, fetched_at,
  window_start, window_end,
  payload_gzip bytea,      -- gzip-JSON oder Original-FIT-ZIP, immer in der DB
  payload_format text,     -- 'json_gzip' | 'fit_zip'
  object_key   text,       -- ungenutzt (kein Object Store)
  content_hash bytea       -- dedupliziert wiederholte identische Antworten
)
-- Unique (user_id, connector, kind, window_start, content_hash)
```

Es gibt **keinen Object Store**. Seit Stufe 1 wird das **Original-FIT-ZIP** jeder
Aktivität als eigene Zeile mit `payload_format='fit_zip'` archiviert und über
`activity.fit_payload_id` verknüpft; die `activity_fit`-Zeile selbst enthält nur noch
ein Manifest. Ältere Aktivitäten haben zusätzlich das dekodierte JSON-Archiv von
vorher, das als Rückfall dient, wenn ein ZIP fehlt. `raw_payload.object_key` ist
ungenutzt.

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
  Aktivitäten speichern `start_local` + `utc_offset_min` (seit Stufe 1), weil Garmin
  die Zeitzone (`timeZoneId`) nur als Zahl liefert; der Offset ergibt sich aus
  `startTimeLocal − startTimeGMT`.
- **Tagesgrenzen** (seit Stufe 1): Aktivitäten zählen zu ihrem lokalen Starttag
  (`start_local`), Wellness-Werte zum Tag in `home_timezone`
  (`metrics_recompute.py`, `metrics_data.py`).
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
| HR-Kurve einer Aktivität | < 300 ms | `activity_stream`, eine Zeile je Kanal |
| Ganzjahres-Zonenverteilung | < 200 ms | `hr_bucket_seconds_daily` |
| Korrelationsanalyse 2 Metriken/2 Jahre | < 1 s | Derived-Tabellen (nicht gebaut) |

Die Zielzeiten sind Planwerte und nicht gemessen.

**Regel für Tool-Implementierungen:** Kein Agent-Tool liest je direkt aus
`wellness_sample` ohne enge Zeitbegrenzung oder aus `activity_stream` über mehr als eine Aktivität. Der Default ist
immer die Derived-Zone.
