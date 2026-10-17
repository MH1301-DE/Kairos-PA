# Aktivitäten & Workouts: Agent-Tools (Design-Spec)

| | |
|---|---|
| **Datum** | 2026-10-07 |
| **Status** | Design abgestimmt. **AP 0 (Verifikation) abgeschlossen am 2026-10-13**, Ergebnisse in §2.1; Fixtures unter `tests/fixtures/garmin/`. **Überarbeitet am 2026-10-13 nach dem Brainstorming** (Entscheidungen D1–D34, Prüfaufträge P1–P3): Diese Spec ist jetzt **Stufe 1**. |
| **Umsetzung** | **AP 1a–3 umgesetzt** auf Branch `stufe1-datenbasis` (2026-10-14 bis 2026-10-17), Plan `docs/superpowers/plans/2026-10-13-stufe1-datenbasis-und-lese-tools.md`. Offen: Live-Eval 17–21/26 (LLM-Key), Entscheidungen zu V2, V4, V7 und Laufband (§12.3). |
| **Baut auf** | `03-agent-design.md` §4.2 · Agent-Harness v2 (`2026-10-05-agent-harness-v2-design.md`) · Phase 5 Planning (`2026-09-12-phase-5-planning-design.md`) |
| **Ist-Stand** | Code- und DB-Prüfung vom 2026-10-07 (26 Fragen, inkl. Live-Abruf von `get_personal_record` und `get_activity_splits`); Prüfaufträge P1–P3 vom 2026-10-13 (§2.2) |
| **Entscheidungen** | [`2026-10-13-brainstorming-entscheidungen.md`](2026-10-13-brainstorming-entscheidungen.md) (D1–D34, Stufenplan) |
| **Folgedokumente** | `superpowers/plans/2026-10-07-doku-abgleich.md` (erledigt); Spec Stufe 2 „Scheduler & Proaktivität“ und Spec Stufe 3 „Coach-Modus“ (beide offen) |

---

## 0. Zusammenfassung

Kairos bekommt in Stufe 1 sechs Bausteine:

1. **Neue Datenbasis.** Sekundendaten liegen als Arrays je Aktivität und Kanal (`activity_stream`) statt als eine Zeile pro Sekunde und Kanal; gemessen 58× kleiner. Die Original-FIT wird als ZIP archiviert. TimescaleDB entfällt, Tageswerte werden nach Ortszeit geschnitten, und die HFmax kommt aus der Nutzereingabe.
2. **Abgeleitete Aktivitätsdaten.** Pro Aktivität entstehen ein Steckbrief (`activity_stats`), Splits pro Kilometer bzw. Uhr-Runde (`activity_split`), die schnellsten Abschnitte über Standarddistanzen (`activity_best_effort`) und für Workouts der Soll/Ist-Vergleich pro Schritt (`activity_step_result`). Alles wird deterministisch aus der archivierten FIT berechnet.
3. **Fünf Lese-Tools in vier Detailstufen:** Suche → Steckbrief → Split-Tabelle (eine Zeile pro km, pro Runde oder pro Workout-Schritt) → Analyse. Dazu kommen Lauf-Bestleistungen. Kein Sekundenwert erreicht den Kontext.
4. **Workout-Verwaltung in Garmin.** Strukturierte Workouts mit Schritt-Notizen und (nach dem Uhr-Test AP 0b) Sekundärzielen lassen sich anlegen, ändern, terminieren und löschen, einzeln oder gesammelt. Jedes Terminieren legt zusätzlich einen Google-Kalendertermin an.
5. **Aktivitäten in Garmin** umbenennen und löschen.
6. **Zwei Harness-Erweiterungen:**
   - Vorschau-Snapshots: Der Nutzer bestätigt genau das, was er gesehen hat, auch bei „lösche alle“.
   - Ein gemeinsamer Garmin-Schreibdienst: nur Token-Login, gedrosselt, mit Kompensation bei Teilfehlern.

**Nicht mehr in dieser Spec:** Die Kopplung der Planung an Garmin (`plan_commit`/`plan_adjust` mit Workouts, früher Teil E) zieht in den Coach-Modus (Stufe 3, D28). Bis dahin legt der Chat Workouts direkt über die Workout-Tools an.

Der Tool-Satz wächst von 12 auf 26. Die Tool-Schemas kosten danach geschätzt 4.000–4.500 Tokens pro Turn; heute sind es gemessen 1.461. Das liegt weiterhin deutlich unter dem Ziel von 15.000 Tokens Median-Input.

---

## 1. Entscheidungen

### 1.1 Mit dem Nutzer abgestimmt (2026-10-07)

| Thema | Entscheidung |
|---|---|
| Detailstufen | Steckbrief; darunter eine Split-Tabelle mit einer Zeile pro Kilometer (Pace, Höhenmeter, HF min/Median/max …); darunter Analyse-Operationen |
| Pace | in Steckbrief und Splits immer enthalten, serverseitig formatiert |
| Bestleistungen | nur Laufen, Distanzen von 800 m bis 100 km |
| Sportarten (Aktivitätsdaten) | Laufen, Rad, Schwimmen, Wandern/Bergsteigen. **Klettern ist nicht im Scope.** |
| Aktivitäten anlegen | entfällt, „Anlegen“ meint Workouts |
| Workouts | strukturierte Schritte: Aufwärmen, Intervalle/Wiederholungen, Erholung, Auslaufen |
| Eigentum | unerheblich: Der Agent darf jedes Workout im Konto ändern und löschen |
| Löschen | immer mit Bestätigung; mehrere oder alle Workouts in einem Vorgang |
| Terminieren | legt immer zusätzlich einen kurzen Google-Kalendertermin an |
| Plan | `plan_commit` = Workouts in Garmin anlegen, terminieren und je einen Kalendertermin anlegen. **Seit 2026-10-13 Teil von Stufe 3** (Coach-Modus, D28). |

### 1.2 In dieser Spec getroffen (bitte prüfen)

| # | Entscheidung | Begründung |
|---|---|---|
| E1 | Km-Splits werden aus dem FIT-Feld `distance` selbst geschnitten; die Uhr-Runden kommen zusätzlich als eigene Split-Art dazu. | Garmins Runden sind nur bei Auto-Lap auf 1 km auch Kilometer. Die FIT-Distanz ist Garmins eigene Distanz und liegt lokal vor, ein Request ist nicht nötig. |
| E2 | Best Efforts werden selbst berechnet (gleitendes Fenster); `get_personal_record` wird nicht importiert. | Garmin führt 800 m, 1.500 m, 3.000 m, 50 km und 100 km nicht. Validiert wird gegen Garmins `fastestSplit_*` und die PR-Werte (Abschnitt 12.3). |
| E3 | Distanzliste: 800 m · 1.500 m · 3.000 m · 5 km · 10 km · HM · M · 50 km · 100 km | Vorschlag vom 07.10., unwidersprochen; als Konstante jederzeit änderbar |
| E4 | Workouts in V1 nur für Laufen und Rad; Kraft-Workouts mit Übungen folgen als V1.1 (D15) | Schwimm-Workouts haben eine eigene Schrittlogik (Bahnen, Schwimmstil, Pausen) und kommen später. Wandern hat keine sinnvolle Struktur. |
| E5 | Aktivitäts-Lese-Tools lesen nur die DB, nie Garmin live. | Kein Rate-Limit-Risiko, deterministische Zahlen, kurze Antwortzeit |
| E6 | Workout-Lese-Tools frischen einen lokalen Spiegel auf, höchstens alle 5 min. | Garmin ist führend, und der Nutzer legt Workouts auch in Garmin Connect an. |
| E7 | Ein Garmin-Workout pro Planblock, keine Wiederverwendung | Gilt als Vorgabe für Stufe 3 (§8). Einzelne Tage bleiben unabhängig änderbar. |
| E8 | ~~Workout-Templates für Planblöcke sind Platzhalter mit HF-Zonen-Zielen.~~ | Entfällt: Pläne erzeugt der Coach-Modus aus der Wissensbank (D19, D24). |
| E9 | **HF-Ziele in Workouts sind immer bpm-Bereiche** (`hr_range`). Zonen-Kürzel (Z1–Z5) in Nutzeranfragen werden beim Erzeugen über die Kairos-Zonen in bpm umgerechnet; die HFmax dafür kommt aus A.6. `hr_zone` (Garmin-Zonennummer) bleibt im Modell nur, um bestehende Garmin-Workouts mit `zoneNumber` lesen, anzeigen und unverändert zurückschreiben zu können. | Entscheidung des Nutzers (2026-10-13). Alle bestehenden Workouts nutzen bpm; die Zahl auf der Uhr ist dieselbe, die Kairos in Vorschau und Kalender zeigt — kein Auseinanderlaufen von Garmin- und Kairos-Zonen. |
| E10 | Aktivitäten umbenennen und löschen bleibt als kleines Paket erhalten (Teil F). | Stand in der ursprünglichen Anfrage. Lässt sich streichen, ohne den Rest zu berühren. |
| E11 | `Connector.write_back` wird für Garmin nicht genutzt. | Workout-Operationen sind mehrstufig (anlegen → terminieren → Kalender). Schreibzugriffe laufen wie beim Kalender über Domänen-Services. |
| E12 | Keine Kalorien im Steckbrief | Ernährung ist Nicht-Ziel (`00` §3). Der Wert bleibt in der DB. |

### 1.3 Nicht-Ziele (V1)

- Sekundendaten im Kontext, manuelle Aktivitäten, FIT-/GPX-Upload
- Auswertungen über die Sekundendaten mehrerer Aktivitäten (D2)
- Klettern; Bestleistungen außerhalb des Laufens
- Workouts für Schwimmen und Wandern; Kraft folgt als V1.1 (D15)
- Planung mit Garmin-Workouts (Stufe 3, D28); Scheduler, Push und automatische Reaktionen (Stufe 2)
- Aktivitätstyp ändern (`set_activity_type`)
- `push_workout_to_device`. Ein terminiertes Workout synchronisiert ohnehin über den Garmin-Kalender auf die Uhr.

### 1.4 Änderungen aus dem Brainstorming (2026-10-13)

| Entscheidung | Inhalt | Abschnitt |
|---|---|---|
| D1, D2 | Sekundendaten als Arrays (`activity_stream`), `activity_record` entfällt | A.2 |
| D3 | Original-FIT als ZIP archivieren statt dekodiertem JSON; Bestand einmal neu laden | A.2, A.4 |
| D4 | TimescaleDB entfernen, Standard-Postgres 16 | A.7 |
| D8 | Tagesgrenzen nach Ortszeit | A.8 |
| D9 | TRIMP zählt weiter Samples als Sekunden (P1: sekündliche Aufzeichnung) | §2.2 |
| D10 | HFmax aus Nutzereingabe, sonst 220 − Alter; Einstellungsseite | A.6 |
| D11 | Pace kurzer Abschnitte aus der Distanz; Laufleistung nur mit Hinweis | B.1, C.2 |
| D12, D13 | Soll/Ist pro Workout-Schritt mit Trefferregel | B.6, C.3 |
| D14 | Sekundärziele nach Uhr-Test | D.1, D.2, AP 0b |
| — (Befund) | Schritt-Notizen ins Workout-Modell, sonst gehen sie beim Ändern verloren | D.1, D.2 |
| D28 | Planung mit Garmin-Workouts nach Stufe 3 | §8 |

---

## 2. Ist-Stand, auf dem die Spec aufsetzt

Belege stehen im Prüfbericht vom 2026-10-07.

| Bereich | Ist-Stand | Folge |
|---|---|---|
| `activity` | Summary-Spalten aus `activity_list`. `activity_type` ist immer NULL, weil `normalize.py:295` einen String erwartet, Garmin aber ein Dict liefert. Zeitzone, `movingDuration`, Training Load, VO₂max und `fastestSplit_*` liegen nur im `raw_payload`. Der Upsert aktualisiert `start_at`/`end_at` nicht (`canonical.py:140-151`). | Teil A.1 |
| `activity_record` | narrow (`metric` als Text, `value` als double), Hypertable; 7 Kanäle befüllt; gemessen 224 B pro Zeile inkl. Indizes, ≈ 3,5 MB pro Aktivität. **`distance` fehlt** in `_FIT_FIELDS` (`normalize.py:309-320`), steht aber in jedem FIT-Record im `raw_payload`. Gelesen nur von `recompute_hr_bucket_seconds_daily` (`metrics_recompute.py`) und `get_activity_detail` (`data_read.py`, Endpoint `GET /api/data/activities/{external_id}`, vom Frontend nicht aufgerufen). | Teil A.2 |
| FIT-Archiv | nur `record`, `session`, `lap` als JSON (`connector.py:81-86`); `length`, `event`, `workout`, `workout_step`, `device_info` werden verworfen; keine FIT-Dateien gespeichert | Teil A.2 |
| TimescaleDB | nur `create_hypertable` für `wellness_sample` und `activity_record` (Migration `6bf30be597a0`); kein `time_bucket`, keine Kompression und keine Continuous Aggregates (beide mit RLS gesperrt). Images: `timescale/timescaledb-ha:pg16` (Compose, CI), `timescale/timescaledb:latest-pg16` (`tests/conftest.py`). | Teil A.7 |
| Tagesgrenzen | `metrics_recompute.py` und `metrics_data.py` schneiden Tage nach UTC (`AT TIME ZONE 'UTC'`); `app_user.home_timezone` existiert (Default `Europe/Berlin`), wird dort aber nicht genutzt. | Teil A.8 |
| HFmax | `estimate_hr_max()` (`metrics/hr_zones.py`) nimmt `hr_max_override`, sonst das Maximum aus 220 − Alter und der höchsten gemessenen Aktivitäts-HF. `birth_date` und `hr_max_override` stehen in `user_setting`, sind aber weder über die API noch im Frontend setzbar. | Teil A.6 |
| Löschungen | kein Abgleich, kein Soft-Delete | Teil A.3 |
| Garmin-Client | `_build_garmin_client` (`sync.py:288-345`): nur Token, kein Passwort. Bei Ablehnung setzt er `reauth_required` **und committet**. | Teil D.7 |
| Proposals | keine Tabelle; `conversation_message.tool_calls` + `tool_call_id`, `FOR UPDATE` + 409 | Teil G.1 |
| Tool-Ausgaben | Hülle `summary/data/meta`; `meta.truncated` wird nie gesetzt; kein globaler Cap; keine Token-Telemetrie | Teil G.2–G.4 |
| Scheduler | keiner; Syncs nur manuell als BackgroundTask; Recompute nach dem Backfill | Ableitungen hängen sich an Sync und Recompute. |
| Durchsatz | 1,5 s zwischen Tagesfenstern; FIT-Downloads innerhalb eines Fensters ohne Pause; 300 s Cooldown | Teil A.5 |
| Reale Daten | 136 Aktivitäten (11.05.2025–07.10.2026): running 99, hiking 11, lap_swimming 7, cycling 7, strength_training 6, hiit 2, breathwork 2, treadmill_running 1, resort_skiing 1. Stand 13.10.: 139 Aktivitäten. | Sportprofile, Teil A.1 |
| `garminconnect` | Laut aktuellem `master`-README gibt es `upload_running_workout`/`upload_cycling_workout`, `get_workout_by_id`, `update_workout` (behält die ID, Termine bleiben gültig), `delete_workout`, `schedule_workout(id, datum)` und `unschedule_workout(schedule_id)`. | In 0.3.17 bestätigt (AP 0, §2.1) |

### 2.1 Ergebnisse AP 0 (2026-10-13)

Geprüft gegen das echte Konto: Lese-Abrufe plus ein vollständiger Schreibzyklus mit zwei
Wegwerf-Workouts (Laufen und Rad, danach gelöscht; das Konto ist unverändert). Rohantworten
anonymisiert unter `tests/fixtures/garmin/`, abgesichert durch
`tests/test_garmin_workout_methods.py` und `tests/test_garmin_workout_fixtures.py`.
Zusätzliche Quelle: das bestehende Projekt `garmin-workout-importer` (16 hochgeladene
Workouts, Update-Fallstrick, siehe unten).

| # | Frage | Ergebnis |
|---|---|---|
| 1 | Workout-Methoden in 0.3.17 | **alle vorhanden**, inkl. `get_scheduled_workouts(year, month)`, `get_scheduled_workout_by_id`, `set_activity_name`, `delete_activity`. Kein Versionssprung, kein Adapter. |
| 2 | Referenz-Workouts | Laufen: Schwelle (Wiederholung, Pace, HF-Bereich), Kadenz, Steigerungen — vom Importer angelegt und vom Nutzer in Garmin Connect nachträglich geändert (z. B. 4 → 6 Wiederholungen; bestätigt R5 „Garmin ist führend“). Wegwerf-Workouts: HF-Zone per `zoneNumber`, Pace, `lap.button`, HF-Bereich; Rad: Leistungszone, Leistungsbereich, Geschwindigkeit, Kadenz. Alle Ziele überstehen den Rundweg unverändert. |
| 3 | Schreibzyklus | anlegen → terminieren → ändern → Termin entfernen → neu terminieren → löschen: alles erfolgreich. Ergebnisse siehe D.2–D.4 (unten eingearbeitet). |
| 4 | Listen-Methoden | Workouts: `get_workouts(start, limit)` (24 im Konto, eine Seite). Termine: `get_scheduled_workouts(year, month)` liefert das **Kalenderraster des Monats inkl. Randwochen** (z. B. 25.08.–19.10. für September) und **alle Eintragstypen** (`workout`, `fbtAdaptiveWorkout`, `activity`, `nap`, `weight`) → nach `itemType == "workout"` filtern, Dubletten aus überlappenden Monaten per `id` entfernen. |
| 5 | Kadenz-Faktor | Garmins `averageRunningCadenceInStepsPerMinute` = **2 × (`avg_cadence` + `avg_fractional_cadence`)** der FIT-Session, exakt in 219 von 219 Fällen. `activity_record.cadence` enthält nur den ganzzahligen Wert pro Bein → spm-Werte aus Records sind bis zu 2 spm zu niedrig (siehe A.2). |
| 6 | `activity_fit`-Payloads | 0–4 Aktivitäten pro Fenster; `activity_id` = `activity.external_id` (136/136 zugeordnet, 0 Fehler). Dieselbe Aktivität steht in **mehreren** Payloads (siehe 8) → Reprocess dedupliziert nach `activity_id` (jüngster Payload gewinnt). |
| 7 | `activity.activity_type`, `audit_log` | `activity_type` wird **nirgends gelesen** (nur `canonical.py:129` schreibt) → Spalte kann entfallen. `audit_log` existiert nicht → wird in AP 5 nach `06` §7 angelegt. |
| 8 | Datumskriterium `get_activities_by_date` | **lokales Startdatum** (ein Lauf um 02:05 Ortszeit, nach UTC am Vortag, steht im Fenster des lokalen Tags). Achtung: Jedes Tagesfenster ruft `get_activities_by_date(d, d+1)` auf, also **zwei Tage inklusive**. |
| 9 | Typliste | 154 Typen als Fixture (`activity_types.json`); alle 9 real vorkommenden `typeKey`s aufgelöst (u. a. `treadmill_running → running`, `lap_swimming → swimming`, `strength_training`/`hiit → fitness_equipment`, `mountaineering → other`). |

**Zusätzliche Befunde**

- **Garmin Coach.** Der Kalender enthielt adaptive Coach-Workouts (`itemType: "fbtAdaptiveWorkout"`, mit `trainingPlanId`, **ohne `workoutId`**). Sie stehen nicht in `get_workouts` und sind damit für `workout_delete`/`workout_unschedule` unerreichbar — die geplante Markierung „Workout aus Trainingsplan“ entfällt. Der Nutzer hat den Coach-Plan inzwischen gelöscht (§15, Punkt 7).
- **Update-Fallstrick (aus dem Importer):** Werden bei `update_workout` zusätzliche, Garmin unbekannte Feldnamen mitgeschickt (z. B. `targetValueLow/High` neben `targetValueOne/Two`), setzt Garmin die Zielwerte serverseitig auf `null` — Ursache des Uhr-Fehlers „HF 101–101“. Der Mapper schickt deshalb nur bekannte Felder; ein `update_workout` mit der vollständigen, unveränderten `get_workout_by_id`-Antwort plus geänderten Feldern funktioniert (AP 0 live geprüft).
- **Garmin-Termine haben keine Uhrzeit** (`startTimestampLocal` ist `null`); die Uhrzeit existiert nur im Google-Termin und in `garmin_workout_schedule.start_at`.
- **Schritt-Notizen.** Die Workouts aus dem Importer nutzen das Schrittfeld `description` (bis 39 Zeichen, z. B. „KADENZ - Tempo halten! Metronom 164 spm“). Das Kairos-Modell muss es führen, sonst gehen die Notizen beim Ändern verloren (D.1).
- **Sekundärziele.** Jeder Schritt enthält `secondaryTargetType`, `secondaryTargetValueOne/Two`, `secondaryTargetValueUnit` und `secondaryZoneNumber`; in allen Fixtures leer.
- **Pace-Reihenfolge.** Der Importer schickte die schnellere Grenze als `targetValueOne` (z. B. 3,636/3,509 m/s), das AP-0-Wegwerf-Workout die langsamere. Garmin speichert beides so, wie gesendet. `from_garmin` sortiert deshalb nach Wert.

### 2.2 Prüfaufträge P1–P3 (2026-10-13)

| # | Frage | Ergebnis | Folge |
|---|---|---|---|
| P1 | Zeichnet die Uhr sekündlich auf? | Ja: HF-Zeilen / `duration_s` = 1,000–1,003 bei den letzten 20 Aktivitäten, Median-Abstand 1 s; Lücken von 13–91 s sind Pausen. `activity.duration_s` ist die Timer-Zeit. | Tages-TRIMP zählt weiter Samples als Sekunden (D9). Die Zeitgewichtung in B.1 bleibt als Absicherung für andere Geräte. |
| P2 | Wie groß ist das Array-Format an echten Daten? | 475 MB → 8,5 MB für 139 Aktivitäten (3.499,5 → 59,9 KB je Aktivität, Faktor ≈ 58). Je Kanal: HF 3,6 KB, Kadenz 2,7, Höhe 4,3, Geschwindigkeit 5,0, Leistung 6,3, Breite 13,4, Länge 14,2, Zeitachse 9,8 KB. | Format aus A.2 übernommen. Die Zeitachse lässt sich später per Lauflängen-Kodierung fast ganz einsparen. |
| P3 | Enthält die Aktivitäts-FIT die Workout-Schritte? | Ja (Aktivität 272, „W3 Do Schwelle 4x6“): `workout_mesgs` und `workout_step_mesgs` mit Dauer, Zieltyp, Zielwerten und Notiz; die Runden tragen `wkt_step_index` (Wiederholungsschritt ohne eigene Runde, letzte Runde mit `session_end` ohne Index). Ein Intervall verteilt sich wegen Auto-Lap auf mehrere Runden. **HF-Ziele sind in der FIT mehrdeutig** (Profil: ≤ 100 = % HFmax, > 100 = bpm + 100; die Datei enthält 100/150, die API 100–150 bpm). | Soll/Ist nach B.6: Struktur aus der FIT, Runden je Schritt zusammenfassen, HF-Ziele aus der API. |

---

## 3. Architektur

```
                  Sync (bestehend, erweitert)
Garmin ── activity_list ──────────────────▶ raw_payload (JSON)
       └─ activity_fit (ZIP je Aktivität) ──▶ raw_payload (kind 'activity_fit_file')
                                              │ normalize / decode
                                              ▼
                activity, activity_stream_axis, activity_stream
                                              │ derive            ◀── reprocess (ohne Garmin-Request)
                                              ▼
 activity_stats · activity_split · activity_best_effort · activity_step_result
                                              ▲
                                              │ nur DB
                                     Aktivitäts-Lese-Tools

Agent-Schreib-Tools ── Proposal + Vorschau ──▶ Bestätigung ──▶ TrainingScheduleService
                                                                 │                │
                                                 GarminWorkoutService      Kalender-Service
                                                                 │                │
                                    Garmin workout-service/Kalender   Google Calendar (source='kairos')
                                                                 │
                                         garmin_workout · garmin_workout_schedule (Spiegel)
```

**Leitregeln**

- **R1** Aktivitäts-Lese-Tools lesen nur die DB.
- **R2** Alles Abgeleitete ist aus `raw_payload` reproduzierbar (`algo_version`). Für Aktivitäten ist die Quelle das archivierte FIT-ZIP; auch `activity_stream` ist eine Ableitung davon.
- **R3** Der Server formatiert jede Zahl, die der Agent nennen soll: Pace, Zeiten, Distanzen, Differenzen. Das Modell rechnet nicht (Rechenverbot, `03` §1).
- **R4** Jede Schreibaktion bei Garmin oder Google läuft über Proposal → Vorschau-Snapshot → Bestätigung.
- **R5** Garmin ist führend für Workouts und Aktivitäten. Lokale Tabellen sind Spiegel oder Ableitungen.
- **R6** Kein Tool löst je einen Login mit Zugangsdaten aus, nur Token-Logins.

---

## 4. Teil A — Datengrundlage

### A.1 `activity` erweitern und korrigieren

Eine Migration, danach der Normalizer-Fix:

| Änderung | Spalte | Quelle (`activity_list`) |
|---|---|---|
| neu | `sport_profile text NOT NULL DEFAULT 'generic'`, CHECK (`running`, `cycling`, `swimming`, `hiking`, `generic`) | abgeleitet aus `activityType` (Tabelle unten) |
| neu | `garmin_type_id int`, `garmin_parent_type_id int` | `activityType.typeId`, `.parentTypeId` |
| neu | `description text` | `description` |
| neu | `start_local timestamp`, `utc_offset_min smallint` | `startTimeLocal`; Offset = `startTimeLocal − startTimeGMT` |
| neu | `moving_duration_s real`, `avg_speed_mps real`, `lap_count smallint` | `movingDuration`, `averageSpeed`, `lapCount` |
| neu | `garmin_training_load real`, `garmin_vo2max real` | `activityTrainingLoad`, `vO2MaxValue` |
| neu | `deleted_at timestamptz`, `deleted_reason text`, CHECK (`kairos`, `garmin_sync`) | Teil A.3 und F |
| neu | `fit_payload_id` | Verweis auf das archivierte FIT-ZIP (A.2) |
| entfällt | `activity_type` | Ist immer NULL; wird laut AP 0 nirgends gelesen. |
| entfällt | `fit_object_key` | ungenutzt (0 von 136 befüllt); ersetzt durch `fit_payload_id` |

- `sport` bleibt der Garmin-`typeKey`.
- **Upsert-Fix:** Bei einem Konflikt werden alle fachlichen Spalten aktualisiert, auch `start_at`, `end_at` und `start_local`. Ausgenommen sind `id`, `user_id`, `external_id` und `created_at`. Taucht eine als gelöscht markierte Aktivität bei Garmin wieder auf, wird `deleted_at` geleert.
- **Indizes:** `(user_id, start_at DESC) WHERE deleted_at IS NULL` und `(user_id, sport_profile, start_at DESC)`.

**Sportprofile** (`typeKey` → Profil):

| Profil | typeKeys (mindestens) | Fallback |
|---|---|---|
| `running` | running, trail_running, treadmill_running, track_running | Elterntyp ist running |
| `cycling` | cycling, road_biking, mountain_biking, gravel_cycling, indoor_cycling, virtual_ride | Elterntyp ist cycling |
| `swimming` | lap_swimming, open_water_swimming | Elterntyp ist swimming |
| `hiking` | hiking, mountaineering, walking | — |
| `generic` | alles andere (strength_training, hiit, breathwork, resort_skiing …) | — |

Die Elterntypen werden über eine Typliste aufgelöst, die einmal per `get_activity_types()` abgerufen und als Fixture eingecheckt wird (`typeId → typeKey → parentTypeId`). Ein Test stellt sicher, dass alle neun real vorkommenden `typeKey`s ohne Fallback zugeordnet werden.

### A.2 FIT-Archiv und Sekundendaten (D1, D3)

**1. FIT-ZIP archivieren.** `_fetch_activity_fits` speichert für jede Aktivität das ZIP aus `download_activity(…, ORIGINAL)` unverändert als eigene `raw_payload`-Zeile:

| Feld | Wert |
|---|---|
| `kind` | `'activity_fit_file'` |
| `window_start`, `window_end` | Startzeit der Aktivität (UTC) |
| `content_hash` | SHA-256 des ZIP |
| `payload_gzip` | das ZIP selbst (schon komprimiert, kein zweites gzip) |
| `payload_format` (neu) | `'fit_zip'`; bestehende Zeilen `'json_gzip'` (CHECK auf beide Werte) |

- Die Aktivität verweist darauf über die neue Spalte `activity.fit_payload_id` (FK auf `raw_payload.id`, Typ wie dort). Die ungenutzte Spalte `activity.fit_object_key` entfällt.
- Das dekodierte JSON (`records`/`sessions`/`laps`) wird für neue Aktivitäten **nicht mehr** gespeichert. Der vorhandene `activity_fit`-JSON-Bestand bleibt unangetastet (Rohdaten werden nie gelöscht) und dient als Rückfall, falls ein ZIP nicht mehr ladbar ist.
- Normalisierung und Ableitung dekodieren das ZIP (`decode_fit_zip`) und haben damit alle Messages: `record`, `session`, `lap`, `length`, `event`, `workout`, `workout_step`, `device_info`.
- Aufwand: ≈ 125 KB pro Aktivität, im Doku-Szenario ≈ 0,8 GB in 5 Jahren.

**2. Sekundendaten als Arrays.** Zwei neue Tabellen ersetzen `activity_record`. Das Format ist das in P2 gemessene (59,9 KB pro Aktivität):

```sql
CREATE TABLE activity_stream_axis (
  activity_id   bigint PRIMARY KEY REFERENCES activity(id) ON DELETE CASCADE,
  user_id       uuid NOT NULL,
  start_at      timestamptz NOT NULL,     -- Zeitstempel des ersten Records
  t_offset_s    int4[] NOT NULL,          -- Sekunden ab start_at, streng aufsteigend
  source        text NOT NULL CHECK (source IN ('fit_zip', 'fit_json')),
  algo_version  smallint NOT NULL
);

CREATE TABLE activity_stream (
  activity_id   bigint REFERENCES activity(id) ON DELETE CASCADE,
  channel       text NOT NULL,            -- 'hr', 'speed_mps', 'distance_m', …
  user_id       uuid NOT NULL,
  v4            real[],                   -- alle Kanäle außer Position
  v8            float8[],                 -- 'lat_deg', 'lng_deg'
  PRIMARY KEY (activity_id, channel),
  CHECK (num_nonnulls(v4, v8) = 1)
);
-- TOAST-Kompression lz4 für t_offset_s, v4, v8 (ALTER TABLE … ALTER COLUMN … SET COMPRESSION lz4)
```

| Regel | Festlegung |
|---|---|
| Ausrichtung | Jedes Kanal-Array hat die Länge von `t_offset_s`; fehlende Werte sind `NULL`-Elemente. Prüfung beim Schreiben: Zahl der Nicht-NULL-Werte = Zahl der gelesenen FIT-Werte. |
| Kanäle (V1) | `hr`, `cadence`, `speed_mps` (aus `enhanced_speed`, sonst `speed`), `distance_m` (neu), `altitude_m` (aus `enhanced_altitude`, sonst `altitude`), `power_w`, `lat_deg`, `lng_deg`, `temp_c`. Ein Kanal ohne Werte wird nicht geschrieben. |
| Neuer Kanal | Eintrag in der Konstante `STREAM_CHANNELS` (Code, Einheit, `v4`/`v8`); keine Schema-Migration. |
| Kadenz (AP 0) | `cadence` = FIT `cadence + fractional_cadence` pro Bein; Lauf-spm = 2 × Wert. Damit stimmen Splits auf ±1 spm mit Garmin überein. |
| Schreiben | pro Aktivität in einer Transaktion: Achse und alle Kanäle löschen und neu schreiben. Die FIT ist unveränderlich, ein erneutes Schreiben ergibt dieselben Daten. |
| RLS | wie alle fachlichen Tabellen: ENABLE + FORCE + Policy auf `user_id` |
| Lesen | ein Helfer `load_stream(activity_id, channels)` liefert die ausgerichteten Arrays; genutzt von Teil B, `activity_analyze` und dem Detail-Endpoint |
| Später möglich | Die Zeitachse macht ≈ 16 % aus. Da die Uhr sekündlich aufzeichnet (P1), würde eine Lauflängen-Kodierung sie fast ganz einsparen. Nicht in V1. |

**3. Lesepfade umstellen.** Es gibt genau zwei:
- `recompute_hr_bucket_seconds_daily` zählt künftig die HF-Werte aus `activity_stream` (SQL über `unnest(v4)` oder in Python) und ordnet sie dem lokalen Tag zu (A.8).
- `GET /api/data/activities/{external_id}` liefert die Kurven aus `activity_stream`. Das alte Limit von 5.000 Zeilen schnitt im narrow-Format nach rund 12 Minuten ab; künftig begrenzt der Parameter `max_points` (Default 2.000) die Punkte durch Mittelung.

**4. Benötigte Lap-Felder** (aus dem dekodierten ZIP):
- Zeit und Distanz: `start_time`, `total_elapsed_time`, `total_timer_time`, `total_distance`
- HF, Höhe, Technik: `avg_heart_rate`, `max_heart_rate`, `total_ascent`, `total_descent`, `avg_cadence`, `avg_fractional_cadence`, `avg_power`
- Struktur: `intensity`, `lap_trigger`, `wkt_step_index`, `num_lengths`

**5. `activity_record` entfällt** nach der Migration (Reihenfolge in A.7).

### A.3 Abgleich bei Garmin gelöschter Aktivitäten

Nach jedem **erfolgreichen** `activity_list`-Abruf eines Fensters wird abgeglichen. Lokale, nicht gelöschte Aktivitäten werden markiert (`deleted_at = now()`, `deleted_reason = 'garmin_sync'`), wenn beides zutrifft:

- ihr lokales Startdatum liegt im Fenster,
- ihre `external_id` fehlt in der Antwort.

Dabei gilt:

- **Nur vollständige Antworten.** Die Paginierung muss abgeschlossen sein, und es darf keine Exception aufgetreten sein.
- **Gleiches Datumskriterium wie Garmin.** Garmin filtert nach dem **lokalen Startdatum** (AP 0 bestätigt). Ein Fenster deckt zwei Tage ab (`get_activities_by_date(d, d+1)`, beide inklusive); abgeglichen werden alle Aktivitäten, deren lokales Startdatum `d` oder `d+1` ist.
- **Folgen:** Die abgeleiteten Zeilen der Aktivität werden entfernt und die Tageskennzahlen der betroffenen Tage neu berechnet. `activity`, `activity_stream` und das FIT-Archiv bleiben erhalten (Rohdaten-nah).
- **Recompute anpassen:** `metrics_recompute.py` muss gelöschte Aktivitäten ausschließen. Heute gibt es keinen solchen Filter.

### A.4 Reprocess-Job

`POST /api/activities/reprocess`, Body optional: `from_date`, `to_date`, `activity_ids`, `refetch_fit` (Default `false`).

1. `activity_list`-Payloads im Bereich neu normalisieren (neue Spalten), **ohne Garmin-Request**.
2. Je Aktivität das FIT-ZIP dekodieren (Rückfall: jüngster `activity_fit`-JSON-Payload, `source = 'fit_json'`) und `activity_stream_axis`/`activity_stream` neu schreiben.
3. Abgeleitete Daten (Teil B) für alle betroffenen Aktivitäten berechnen.
4. Nur mit `refetch_fit=true`: das ZIP für alle Aktivitäten ohne `fit_payload_id` laden, mit `GARMIN_FIT_DOWNLOAD_PAUSE_S` zwischen den Downloads. Der Job teilt Lock und Cooldown mit dem Backfill. Downloads, die scheitern (z. B. bei Garmin gelöschte Aktivitäten), werden im Ergebnis gelistet; diese Aktivitäten nutzen den JSON-Rückfall.

**Einmalig bei der Umstellung:** Reprocess über die gesamte Historie mit `refetch_fit=true` (139 Downloads, je 2 s Pause, also rund 5–10 min).

Automatisch läuft der Job in zwei Fällen:

- nach jedem Garmin-Sync, für die darin berührten Aktivitäten;
- wenn `ACTIVITY_DERIVED_ALGO_VERSION` größer ist als die gespeicherte `algo_version`, beim nächsten Sync oder Reprocess.

### A.5 Durchsatz-Fix

Zwischen zwei FIT-Downloads innerhalb eines Fensters wird `GARMIN_FIT_DOWNLOAD_PAUSE_S` gewartet (Default 2,0 s). Heute werden alle FIT-Dateien eines Tages ohne Pause geladen.

### A.6 HFmax und Profileinstellungen (D10)

**Regel.** `estimate_hr_max()` liefert künftig:
1. `user_setting.hr_max_override`, falls gesetzt;
2. sonst 220 − Alter aus `user_setting.birth_date`;
3. sonst nichts.

Der höchste gemessene Wert ist **kein** Kandidat mehr. Liegt `max(activity.max_hr)` der letzten 12 Monate über der verwendeten HFmax, zeigen Einstellungsseite und Lagebild einen Hinweis („gemessen 219 bpm, eingetragen 214 – prüfen“).

**Folgen.**
- Ohne HFmax liefern TRIMP, HF-Zonen und `hr_range`-Umrechnungen keinen Wert, sondern den Hinweis „HFmax fehlt – bitte in den Einstellungen eintragen“.
- **Vor dem Umschalten** für bestehende Nutzer die HFmax eintragen (Max: 214 bpm), sonst fehlt deren TRIMP ab dem nächsten Recompute.
- Danach Recompute der gesamten Historie, weil sich die Zonen ändern können.

**API und Oberfläche.** Neu: `GET/PUT /api/settings/profile` mit `birth_date`, `hr_max_override` (120–230 bpm) und `resting_hr_override`. Die Einstellungsseite fragt ausdrücklich nach dem gemessenen HFmax-Wert und erklärt, dass 220 − Alter individuell stark streut. Sie zeigt die aktuell verwendete HFmax und ihre Herkunft (eingetragen / aus Alter).

### A.7 TimescaleDB entfernen (D4)

Genutzt wird nur `create_hypertable`; Kompression und Continuous Aggregates sind wegen RLS gesperrt (§2). Nach A.2 bleibt als Hypertable nur `wellness_sample`, und die braucht keine.

**Reihenfolge**, damit kein Datenverlust entsteht (alles noch auf dem Timescale-Image):

1. Migration: `activity_stream_axis`, `activity_stream`, `payload_format`, `fit_payload_id` anlegen.
2. Reprocess mit `refetch_fit=true` (A.4) füllt die Arrays. Prüfung (V8): Je Aktivität entspricht die Zahl der Nicht-NULL-Werte je Kanal der Zahl der `activity_record`-Zeilen dieses Kanals; ausgenommen ist der neue Kanal `distance_m`, bei der Kadenz ändert sich nur der Wert. Abweichungen werden gelistet, nicht übergangen.
3. Migration: `wellness_sample` als normale Tabelle neu anlegen (Primärschlüssel nur `id`; fachlicher Unique-Key `(user_id, metric_id, observed_at)` wie bisher), Daten kopieren, Zeilenzahl prüfen, Hypertable löschen, umbenennen, RLS (ENABLE, FORCE, Policy) und Indizes neu anlegen.
4. Migration: `activity_record` löschen, danach `DROP EXTENSION timescaledb`. Ein Downgrade gibt es nicht; vorher `pg_dump`.
5. Image-Wechsel auf `postgres:16` (offizielles Image) in `deploy/docker-compose.yml`, `deploy/docker-compose.dev.yml`, `.github/workflows/ci.yml` und `tests/conftest.py`. Die Daten wandern per `pg_dump -Fc` / `pg_restore` in ein neues Volume; das `timescaledb-ha`-Image nutzt ein anderes Datenverzeichnis und eine andere UID, eine direkte Übernahme des Volumes geht nicht.
6. Modelle: `ActivityRecord` entfällt; die Kommentare „Timescale needs the partitioning column …“ und `observed_at` als PK-Bestandteil entfallen.

**Nachtrag 2026-10-14 (Umsetzung, Q2).** Schritte 3 und 4 sind eine Migration (`fed6d2d1311b_drop_timescaledb`). Damit `alembic upgrade head` auf einem leeren `postgres:16` durchläuft, ist die alte Migration `6bf30be597a0` ein No-op, wenn `pg_available_extensions` keine Zeile `timescaledb` hat; `wellness_sample` behält dann den PK `(id)`, und die neue Migration baut die Tabelle in beiden Fällen gleich um. Die Dev-DB hat zusätzlich `timescaledb_toolkit`; die Migration löscht erst `timescaledb_toolkit`, dann `timescaledb` (beide `IF EXISTS`). Sie bricht ab, wenn die Rolle RLS nicht umgeht (sonst würde die Kopie unter FORCE RLS leer) oder wenn Aktivitäten `activity_record`-Zeilen, aber keine `activity_stream_axis` haben. Der von Timescale angelegte Index `wellness_sample_observed_at_idx` wird nicht nachgebaut; der Unique-Key `(user_id, metric_id, observed_at)` deckt alle Abfragen ab.

Das Vorgehen gehört als Runbook in `docs/HANDOVER.md`. Die Doku-Folgen (ADR-0002, `01`, `02`, `07`, `README.md`) sind Teil von AP 8.

### A.8 Tagesgrenzen nach Ortszeit (D8)

| Daten | Tag |
|---|---|
| Aktivitäten (HF-Buckets, Tages-TRIMP, Zonen) | lokales Startdatum der Aktivität (`start_local::date`, A.1); eine Aktivität über Mitternacht zählt ganz zum Starttag, wie bei Garmin |
| Wellness-Werte (`wellness_daily_stats`) | `(observed_at AT TIME ZONE app_user.home_timezone)::date` |

- Betroffen sind `metrics_recompute.py` und `metrics_data.py`, also alle Stellen mit `AT TIME ZONE 'UTC'`.
- Nach der Umstellung werden alle Tageswerte einmal neu berechnet. Tageswerte, die bisher durch UTC verschoben waren (Aktivitäten zwischen 0 und 2 Uhr Ortszeit), wandern auf den richtigen Tag.
- Testfall: Lauf um 00:30 Ortszeit (22:30 UTC am Vortag) zählt zum lokalen Tag.
- Nicht Teil dieser Spec: Schlaf dem Aufwachtag zuordnen (`02` §2.7, weiter offen).

---

## 5. Teil B — Abgeleitete Aktivitätsdaten

### B.1 Rechenregeln (für alle Tabellen)

| Thema | Regel |
|---|---|
| Datenbasis | die ausgerichteten Arrays aus `activity_stream` (A.2) plus `lap`-, `length`-, `event`-, `session`-, `workout`- und `workout_step`-Messages aus dem dekodierten FIT-ZIP |
| Gewichtung | Mittelwerte und Mediane sind zeitgewichtet. Gewicht eines Samples = Abstand zum nächsten, gedeckelt auf 10 s. Max' Uhr zeichnet sekündlich auf (P1); die Gewichtung schützt vor Geräten mit „Smart Recording“. |
| Tempo | Pace und Geschwindigkeit über Abschnitte (Splits, Segmente, Bestleistungen, Kurven, Höchstgeschwindigkeit) werden aus `distance_m` und der Zeit berechnet, nicht aus `speed_mps`: Garmins Geschwindigkeitsfeld ist geglättet (in Max' Daten ≈ 12–15 s Verzögerung). Höchstgeschwindigkeit = Maximum über gleitende 10-s-Fenster. |
| Leistung (Laufen) | Laufleistung vom Handgelenk wird ausgewiesen, aber mit Hinweis „Handgelenk-Leistung, eingeschränkt aussagekräftig“; sie korrelierte in Max' Daten kaum mit der Pace (r = 0,16). Leistung vom Rad-Leistungsmesser ohne Hinweis. |
| Pausen | Mit `event_mesgs`: die Timer-Stopp-Intervalle. Ohne (Altbestand): Lücke > 10 s **und** implizite Geschwindigkeit < 0,3 m/s. Pausen zählen wie bei Garmin nicht zur Split- bzw. Timer-Zeit. |
| Distanz | `distance_m` kumulativ (Garmins Distanz); negative Sprünge werden auf 0 geklemmt |
| HF | Werte < 25 oder > 230 werden ignoriert. Schwimmen: `quality='partial'` mit dem Hinweis „Handgelenk-HF im Wasser eingeschränkt verlässlich“ |
| Höhe | gleitender Median über 5 Samples, danach Hysterese von 2 m für Hm↑/Hm↓ |
| Kadenz | Laufen: 2 × (FIT-`cadence` + `fractional_cadence`) = Schritte/min (spm), in AP 0 exakt gegen Garmins `averageRunningCadenceInStepsPerMinute` bestätigt (219/219). Rad: rpm. |
| Zonen | Default-Variante von `hr_zone_distribution` (`percent_max`), dieselbe Funktion wie im Dashboard, mit der HFmax aus A.6 |
| TRIMP | Edwards, dieselbe Formel wie die kanonische Tageslast, angewendet auf die HF-Reihe der Aktivität |
| Distanzquelle | GPS-Abdeckung ≥ 90 % → `gps`; Laufband/Indoor (`session.sub_sport`) oder GPS-Abdeckung < 50 % → `watch_estimate`; Beckenschwimmen → `pool`; sonst `mixed`; ohne Distanz → `none` |
| Ohne Sekundendaten | Steckbrief nur aus der `activity`-Summary, `quality='partial'`, keine Splits und keine Best Efforts |

### B.2 `activity_stats`: eine Zeile pro Aktivität

```sql
CREATE TABLE activity_stats (
  activity_id          bigint PRIMARY KEY REFERENCES activity(id) ON DELETE CASCADE,
  user_id              uuid NOT NULL,
  sport_profile        text NOT NULL,
  algo_version         smallint NOT NULL,
  distance_m           real,
  elapsed_s            real,         -- inkl. Pausen
  timer_s              real,         -- ohne Pausen
  moving_s             real,         -- Garmin movingDuration, sonst eigene Berechnung
  avg_pace_s_km        real,         -- running, hiking (Timer-Zeit)
  avg_moving_pace_s_km real,
  avg_speed_kmh        real,         -- cycling
  max_speed_kmh        real,
  avg_pace_s_100m      real,         -- swimming
  hr_avg smallint, hr_median smallint, hr_min smallint, hr_max smallint,
  hr_zone_s            jsonb,        -- {"z1": s, …, "z5": s}
  trimp_edwards        real,
  elev_gain_m real, elev_loss_m real, alt_min_m real, alt_max_m real,
  cadence_avg          real,         -- spm (Laufen) bzw. rpm (Rad)
  power_avg_w real, power_max_w real,
  fastest_split_idx    smallint, fastest_split_pace_s real,  -- nur volle Splits
  slowest_split_idx    smallint, slowest_split_pace_s real,
  pace_cv_pct          real,         -- Gleichmäßigkeit der Split-Paces
  decoupling_pct       real,         -- NULL, wenn nicht anwendbar
  decoupling_note      text,
  distance_source      text CHECK (distance_source IN ('gps','watch_estimate','pool','mixed','none')),
  hr_coverage_pct real, gps_coverage_pct real,
  quality              text NOT NULL CHECK (quality IN ('ok','partial','suspect')),
  sport_metrics        jsonb NOT NULL DEFAULT '{}',
  computed_at          timestamptz NOT NULL DEFAULT now()
);
```

Row-Level-Security gilt wie bei allen fachlichen Tabellen; das gilt auch für alle weiteren neuen Tabellen dieser Spec.

**`sport_metrics` je Profil** (festes Schema, per Pydantic validiert):

| Profil | Felder |
|---|---|
| running | keine (alles in Spalten) |
| cycling | `avg_moving_speed_kmh`, `normalized_power_w` (nur mit Leistungsdaten) |
| swimming | `pool_length_m`, `active_lengths`, `avg_swolf`, `avg_strokes_per_length`, `rest_s` |
| hiking | `ascent_rate_m_h` (Hm↑ pro Stunde in Abschnitten mit mehr als 3 % Steigung), `descent_rate_m_h` |
| generic | keine |

**Aerobe Entkopplung.** Gilt für Laufen, für Rad mit Leistungsdaten (sonst über die Geschwindigkeit). Die Berechnung läuft so:

1. Die ersten 10 min werden verworfen.
2. Der Rest muss mindestens 40 min lang sein, und `pace_cv_pct` darf höchstens 8 % betragen.
3. Effizienz je Hälfte: `EF = Geschwindigkeit / HF`.
4. `decoupling = (EF₁ − EF₂) / EF₁ × 100`.

Sind die Voraussetzungen nicht erfüllt, bleibt der Wert NULL, und `decoupling_note` nennt den Grund (z. B. „Intervalltraining – nicht anwendbar“, „zu kurz für Entkopplung (< 50 min)“).

### B.3 `activity_split`: Kilometer und Runden

```sql
CREATE TABLE activity_split (
  activity_id     bigint REFERENCES activity(id) ON DELETE CASCADE,
  kind            text CHECK (kind IN ('distance','lap')),
  idx             smallint,                -- 1-basiert
  user_id         uuid NOT NULL,
  unit_m          real,                    -- Splitlänge bei kind='distance'
  start_offset_s  real,                    -- Timer-Zeit seit Start
  distance_m      real,
  timer_s         real,
  pace_s_km real, speed_kmh real, pace_s_100m real,
  elev_gain_m real, elev_loss_m real,
  hr_min smallint, hr_median smallint, hr_max smallint, hr_avg smallint,
  cadence_avg real, power_avg_w real,
  is_partial      boolean NOT NULL DEFAULT false,
  lap_intensity   text,     -- nur lap: warmup | active | rest | recovery | cooldown
  lap_trigger     text,     -- nur lap: manual | distance | time | session_end …
  wkt_step_index  smallint, -- nur lap: Schritt des ausgeführten Workouts
  swim_lengths    smallint, swolf real,
  quality         text NOT NULL,
  PRIMARY KEY (activity_id, kind, idx)
);
```

| Profil | `distance`-Splits | `lap`-Splits |
|---|---|---|
| running, hiking | 1 km | ja |
| cycling | 5 km | ja |
| swimming | 100 m (nur mit `length_mesgs`) | ja (Intervalle) |
| generic | — | ja, falls vorhanden |

- **Splitgrenzen:** Die Zeit an der exakten Distanzmarke wird linear interpoliert.
- **Letzter Teil-Split:** Er bleibt erhalten, wenn er mindestens 100 m (Laufen/Wandern), 1 km (Rad) bzw. 25 m (Schwimmen) lang ist. Er bekommt `is_partial = true` und zählt weder für den schnellsten/langsamsten Split noch für `pace_cv_pct`.

### B.4 `activity_best_effort`: schnellste Abschnitte (nur Laufen)

```sql
CREATE TABLE activity_best_effort (
  activity_id    bigint REFERENCES activity(id) ON DELETE CASCADE,
  distance_key   text,          -- '800m','1500m','3000m','5k','10k','hm','m','50k','100k'
  user_id        uuid NOT NULL,
  distance_m     real NOT NULL, -- 800 … 21097.5, 42195 … 100000
  duration_s     real NOT NULL, -- Timer-Zeit
  start_offset_s real NOT NULL,
  start_km       real NOT NULL,
  hr_avg         smallint,
  quality        text NOT NULL,
  PRIMARY KEY (activity_id, distance_key)
);
```

- **Wann berechnet wird:** `sport_profile='running'`, `distance_source='gps'`, nicht gelöscht, und die Aktivität ist mindestens so lang wie die Zieldistanz. Laufband- und Indoor-Läufe werden nicht berechnet.
- **Algorithmus:** Ein Zwei-Zeiger-Fenster über (Timer-Zeit, Distanz); die exakte Zieldistanz wird interpoliert. Aufwand O(n) je Distanz.
- **Plausibilität:**
  - Fenster mit einem Schritt über `BEST_EFFORT_MAX_STEP_SPEED_MPS` (Default 8,5 m/s) gelten als GPS-Sprung und werden verworfen.
  - Fenster mit Lücken über 10 s, die nicht als Pause erkannt wurden, bekommen `quality='partial'`.
- **Validierung:** Abschnitt 12.3 (V2, V3).

### B.5 Ablauf und Aufwand

- **Auslöser:** nach dem Commit von `activity_fit` für die berührten Aktivitäten, nach dem Löschen einer Aktivität und per Reprocess.
- **Laufzeit-Ziel:** unter 200 ms pro Aktivität ohne FIT-Dekodierung; die gesamte Historie (139 Aktivitäten) inklusive Dekodierung in unter 2 min.
- **Volumen:** vernachlässigbar. `activity_split` hat rund 20 Zeilen pro Aktivität, `activity_best_effort` höchstens 9, `activity_step_result` eine Zeile je ausgeführtem Workout-Schritt.

### B.6 Soll/Ist pro Workout-Schritt (D12, D13)

Gilt für Aktivitäten, die als Garmin-Workout gelaufen wurden, also deren FIT einen `workout_mesgs`-Eintrag hat.

**Quellen** (P3):

| Was | Quelle |
|---|---|
| Struktur (Schritte, Dauer, Wiederholungen, Notizen) | `workout_step_mesgs` der FIT |
| Zuordnung der Runden | `lap.wkt_step_index` = `message_index` des Schritts |
| Ziele für Pace, Geschwindigkeit, Kadenz, Leistung | `workout_step` der FIT (`custom_target_value_low/high`); Grenzen nach Wert sortieren |
| Ziele für HF | **Garmin-API**, nicht die FIT: Die FIT kodiert HF-Ziele mehrdeutig (P3). Zuordnung zum Workout über den Spiegel (`garmin_workout`, D.3): gleicher Name und Termin am lokalen Aktivitätsdatum, sonst gleicher Name. Ohne Treffer gilt das HF-Ziel als „unklar“ und wird nicht bewertet. |

**Ausführungen bilden.** Aufeinanderfolgende Runden mit demselben `wkt_step_index` sind **eine** Ausführung; ein Intervall kann wegen Auto-Lap aus mehreren Runden bestehen (P3). Läuft ein Wiederholungsblock erneut, beginnt eine neue Ausführung mit der nächsten Wiederholungsnummer. Die letzte Runde ohne Index (`session_end`) und Runden kürzer als 5 s bleiben unberücksichtigt.

**Tabelle**

```sql
CREATE TABLE activity_step_result (
  activity_id      bigint REFERENCES activity(id) ON DELETE CASCADE,
  exec_idx         smallint,              -- 1-basiert, Reihenfolge der Ausführungen
  user_id          uuid NOT NULL,
  wkt_step_index   smallint NOT NULL,
  repeat_iteration smallint,              -- 1..n bei Schritten in Wiederholungen
  step_type        text NOT NULL,         -- warmup | interval | recovery | rest | cooldown
  step_note        text,
  planned_end      text,                  -- z. B. 'time 360 s', 'distance 2000 m', 'lap_button'
  target_type      text,                  -- pace | speed | hr_range | cadence | power | none
  target_low       real, target_high real,  -- SI-Einheiten (m/s, bpm, spm/rpm, W)
  target_source    text CHECK (target_source IN ('fit', 'api', 'unclear', 'none')),
  secondary_type   text,                  -- wie target_type; erst nach AP 0b befüllt
  secondary_low    real, secondary_high real,
  timer_s          real, distance_m real,
  avg_pace_s_km    real, avg_hr real, hr_in_target_pct real,
  avg_cadence      real, avg_power_w real,
  hit              boolean,               -- NULL, wenn nicht bewertbar
  secondary_hit    boolean,
  PRIMARY KEY (activity_id, exec_idx)
);
```

**Trefferregel** (D13):
- Pace, Geschwindigkeit, Kadenz, Leistung: getroffen, wenn der Ø-Wert der Ausführung im Zielbereich ± 2 % liegt.
- HF: getroffen, wenn mindestens 80 % der Ausführungszeit im Bereich liegen (zeitgewichtet aus `activity_stream`).
- Kein Ziel, Ziel „unklar“ oder Ausführung kürzer als 20 s: `hit = NULL`.

**Sekundärziele** (D14) werden genauso bewertet, sobald AP 0b sie freigibt; bis dahin werden sie ignoriert.

---

## 6. Teil C — Lese-Tools für Aktivitäten

### C.0 Gemeinsame Konventionen

- **Hülle:** `summary` / `data` / `meta` wie bisher. Neu in `meta`: `next` (Hinweis auf die nächste Detailstufe) und `quality`.
- **Tabellen:** spaltenförmig, `{"cols": [...], "rows": [[...], ...]}`. Das spart gegenüber einem Objekt pro Zeile rund 60 % Tokens.
- **Formatierung:** Alle Werte kommen fertig formatiert (deutsch):

  | Wert | Format |
  |---|---|
  | Distanz | `8,02 km` |
  | Zeit | `41:30` bzw. `1:09:26` |
  | Pace Laufen | `5:10 /km` |
  | Pace Schwimmen | `2:05 /100 m` |
  | Geschwindigkeit Rad | `28,4 km/h` |
  | Datum | `Di 07.10.2026 07:12` (lokal) |

- **IDs:** Es wird die Kairos-`activity.id` verwendet. Gelöschte Aktivitäten sind unsichtbar.
- **Datenstand:** `meta.as_of` ist der Zeitpunkt des letzten erfolgreichen `activity_list`-Syncs.
- **Obergrenze:** Jedes Tool hat eine harte Obergrenze, gemessen in Zeichen (≈ 3,7 Zeichen pro Token). Wird sie überschritten, wird deterministisch gekürzt und `meta.truncated = true` gesetzt.

| Tool | Stufe | Obergrenze |
|---|---|---|
| `activity_search` | L0 Suche | 600 Tokens |
| `activity_get` | L1 Steckbrief | 700 Tokens |
| `activity_splits` | L2 Split-Tabelle | 1.200 Tokens |
| `activity_analyze` | L3 Analyse | 800 Tokens |
| `best_efforts` | Bestleistungen | 500 Tokens |

### C.1 `activity_search` (read)

```json
{
  "name": "activity_search",
  "description": "Sucht eigene Aktivitäten (Laufen, Rad, Schwimmen, Wandern …) und liefert eine kompakte Liste mit IDs. Details danach mit activity_get.",
  "parameters": {
    "type": "object",
    "properties": {
      "from_date": {"type": "string", "description": "YYYY-MM-DD, Default: heute − 30 Tage"},
      "to_date": {"type": "string", "description": "YYYY-MM-DD, Default: heute"},
      "sport_profile": {"type": "string", "enum": ["running", "cycling", "swimming", "hiking", "generic"]},
      "name_contains": {"type": "string"},
      "min_distance_km": {"type": "number"},
      "max_distance_km": {"type": "number"},
      "sort": {"type": "string", "enum": ["newest", "oldest", "longest", "fastest"]},
      "limit": {"type": "integer", "minimum": 1, "maximum": 20}
    }
  }
}
```

**Regeln**

- Defaults: `sort=newest`, `limit=10`.
- `fastest` verlangt `sport_profile`. Fehlt es, bekommt das Modell eine Fehlermeldung.
- Die Spalte `tempo` zeigt je Profil Pace oder km/h.

**Beispiel** (Beispielwerte)

```json
{
  "summary": "4 Läufe zwischen 07.09. und 07.10.2026, zusammen 38,60 km.",
  "data": {
    "cols": ["id", "datum", "name", "sport", "distanz", "dauer", "tempo", "hf_avg", "hm_auf", "trimp"],
    "rows": [
      [812, "Di 07.10. 07:12", "Morgenlauf",    "Laufen", "8,02 km",  "41:30",   "5:10 /km", 146, 64,  113],
      [805, "So 05.10. 09:03", "Langer Lauf",   "Laufen", "12,40 km", "1:09:26", "5:36 /km", 139, 121, 141],
      [798, "Mi 01.10. 18:41", "Tempolauf",     "Laufen", "10,05 km", "47:44",   "4:45 /km", 162, 48,  168],
      [791, "So 28.09. 08:15", "Lockerer Lauf", "Laufen", "8,13 km",  "46:21",   "5:42 /km", 136, 70,  82]
    ]
  },
  "meta": {"row_count": 4, "truncated": false, "as_of": "2026-10-07T07:58:00Z", "next": "Details: activity_get(activity_id=…)"}
}
```

### C.2 `activity_get` (read) — Steckbrief

```json
{
  "name": "activity_get",
  "description": "Steckbrief einer Aktivität: Umfang, Pace/Tempo, Herzfrequenz, Zonen, Belastung, schnellster und langsamster km. Ohne activity_id: die letzte Aktivität (optional gefiltert nach sport_profile).",
  "parameters": {
    "type": "object",
    "properties": {
      "activity_id": {"type": "integer"},
      "sport_profile": {"type": "string", "enum": ["running", "cycling", "swimming", "hiking", "generic"]}
    }
  }
}
```

Ohne `activity_id` liefert das Tool die letzte Aktivität. Damit braucht die häufigste Frage („Wie war mein letzter Lauf?“) genau einen Tool-Aufruf.

**Beispiel Laufen** (Beispielwerte, konsistent mit C.3)

```json
{
  "summary": "Lauf Di 07.10.2026: 8,02 km in 41:30 (Ø 5:10 /km), Ø-HF 146, schnellster km 6 (4:58 /km), langsamster km 1 (5:31 /km).",
  "data": {
    "aktivitaet": {"id": 812, "name": "Morgenlauf", "sport": "Laufen (running)", "start": "Di 07.10.2026 07:12", "distanzquelle": "GPS"},
    "umfang": {"distanz": "8,02 km", "zeit": "41:30", "zeit_inkl_pausen": "42:05", "hm_auf": "64 m", "hm_ab": "61 m", "hoehe": "38–71 m"},
    "tempo": {"pace": "5:10 /km", "pace_bewegt": "5:10 /km", "schnellster_km": "km 6 · 4:58 /km", "langsamster_km": "km 1 · 5:31 /km", "gleichmaessigkeit": "CV 3,0 %"},
    "herzfrequenz": {"avg": 146, "median": 147, "min": 112, "max": 171,
                     "zonen": {"z1": "3:10", "z2": "12:40", "z3": "18:05", "z4": "7:35", "z5": "0:00"}},
    "technik": {"kadenz": "172 spm", "leistung": "269 W (Handgelenk, eingeschränkt aussagekräftig)"},
    "belastung": {"trimp_edwards": 113, "garmin_training_load": 84, "garmin_vo2max": 52},
    "effizienz": {"entkopplung": null, "hinweis": "zu kurz für Entkopplung (< 50 min)"},
    "splits": {"km": 8, "runden": 8},
    "workout": null
  },
  "meta": {"quality": "ok", "coverage": "HF 100 %, GPS 99 %", "as_of": "2026-10-07T07:58:00Z",
           "truncated": false, "next": "Kilometerwerte: activity_splits(activity_id=812)"}
}
```

**Abweichungen je Profil**

| Profil | `tempo` | zusätzlich | entfällt |
|---|---|---|---|
| cycling | `avg_kmh`, `max_kmh`, `avg_bewegt_kmh` | Leistung inkl. Normalized Power (falls vorhanden), Kadenz in rpm | schnellster/langsamster km (stattdessen 5-km-Abschnitt) |
| swimming | Pace `/100 m` | Beckenlänge, Bahnen, Ø-SWOLF, Pausenzeit; HF mit Hinweis auf eingeschränkte Verlässlichkeit | Höhe, Kadenz |
| hiking | Pace `/km` | Steigrate (Hm/h), max. Höhe | Kadenz, Leistung |
| generic | — | Dauer, HF, Zonen, TRIMP | Tempo, Splits (außer Runden) |

**Workout-Aktivitäten.** Wurde die Aktivität als Garmin-Workout gelaufen (B.6), ist `data.workout` gefüllt, sonst `null`:

```json
{"name": "W3 Do Schwelle 4x6", "bewertet": 10, "getroffen": 8,
 "kurz": "Intervalle 4/4 im Zielbereich, Trabpausen 2/4 im HF-Bereich"}
```

`meta.next` verweist dann auf `activity_splits(activity_id=…, kind="steps")`.

### C.3 `activity_splits` (read) — Split-Tabelle

```json
{
  "name": "activity_splits",
  "description": "Split-Tabelle einer Aktivität: eine Zeile pro km (Rad 5 km, Schwimmen 100 m), pro Uhr-Runde oder pro Workout-Schritt mit Ziel und Treffer (Soll/Ist), jeweils mit Pace, Höhenmetern und HF.",
  "parameters": {
    "type": "object",
    "properties": {
      "activity_id": {"type": "integer"},
      "kind": {"type": "string", "enum": ["distance", "lap", "steps"]},
      "from_idx": {"type": "integer", "minimum": 1},
      "to_idx": {"type": "integer", "minimum": 1}
    },
    "required": ["activity_id"]
  }
}
```

**Regeln**

- Default ist `kind=distance`. Wurde die Aktivität als Workout gelaufen, weist `summary` auf `kind=steps` hin.
- `kind=steps` liest `activity_step_result` (B.6): eine Zeile je Ausführung eines Workout-Schritts, mit Ziel, Ist-Wert und Treffer. Ohne Workout liefert das Tool einen Fehlerhinweis an das Modell.
- Es werden höchstens 50 Zeilen ausgegeben. Bei mehr Splits ohne Bereichsangabe fasst das Tool je 5 Splits zu einem Block zusammen (Laufen: 5-km-Blöcke) und setzt `truncated=true` sowie `meta.next` mit einem Bereichsbeispiel. Ein Marathon hat 42 Zeilen und passt ungekürzt; ein 100-km-Lauf ergibt 20 Blöcke.
- Spalten ohne Daten (z. B. Leistung ohne Sensor) werden weggelassen.
- Ein Teil-Split wird als `"9 (0,37 km)"` beschriftet.

**Spalten je Profil**

| Profil / Art | Spalten |
|---|---|
| running, `distance` | `km, pace, kum_zeit, hm_auf, hm_ab, hf_min, hf_med, hf_max, kadenz, leistung` |
| hiking, `distance` | `km, pace, kum_zeit, hm_auf, hm_ab, steigrate, hf_min, hf_med, hf_max` |
| cycling, `distance` | `abschnitt, kmh, kum_zeit, hm_auf, hm_ab, hf_min, hf_med, hf_max, kadenz, leistung` |
| swimming, `distance` | `m, pace_100m, kum_zeit, bahnen, swolf, hf_med` |
| alle, `lap` | `runde, typ, schritt, distanz, zeit, tempo, hf_min, hf_med, hf_max, hm_auf, hm_ab` |
| alle, `steps` | `nr, schritt, wdh, ziel, ist, dauer, distanz, hf_med, getroffen` |

**Beispiel Kilometer** (passt zu C.2: Σ Hm↑ 64, Σ Hm↓ 61, Ø-Kadenz 172, Ø-Leistung 269 W)

```json
{
  "summary": "8 Kilometer-Splits. Schnellster km 6 (4:58 /km), langsamster km 1 (5:31 /km).",
  "data": {
    "unit": "1 km",
    "cols": ["km", "pace", "kum_zeit", "hm_auf", "hm_ab", "hf_min", "hf_med", "hf_max", "kadenz", "leistung"],
    "rows": [
      ["1", "5:31", "5:31",  12, 3,  112, 131, 139, 166, 255],
      ["2", "5:16", "10:47", 4,  8,  133, 141, 145, 170, 262],
      ["3", "5:12", "15:59", 9,  6,  140, 145, 148, 171, 266],
      ["4", "5:09", "21:08", 7,  9,  143, 147, 150, 172, 268],
      ["5", "5:07", "26:15", 11, 4,  145, 149, 152, 173, 270],
      ["6", "4:58", "31:13", 3,  12, 147, 153, 158, 176, 281],
      ["7", "5:03", "36:16", 10, 7,  148, 152, 156, 174, 276],
      ["8", "5:08", "41:24", 8,  12, 149, 154, 171, 174, 272]
    ]
  },
  "meta": {"row_count": 8, "truncated": false, "quality": "ok"}
}
```

Die restlichen 0,02 km liegen unter der Mindestlänge von 100 m und erscheinen daher nicht als Teil-Split.

**Beispiel Runden** (Intervalltraining, Ausschnitt)

```json
{
  "cols": ["runde", "typ", "schritt", "distanz", "zeit", "tempo", "hf_min", "hf_med", "hf_max", "hm_auf", "hm_ab"],
  "rows": [
    ["1", "Aufwärmen", 1, "2,71 km", "15:00", "5:32 /km", 118, 134, 142, 12, 9],
    ["2", "Intervall", 2, "0,80 km", "3:08",  "3:55 /km", 141, 163, 171, 3,  2],
    ["3", "Erholung",  3, "0,33 km", "2:00",  "6:04 /km", 150, 152, 165, 1,  2]
  ]
}
```

**Beispiel Workout-Schritte** (Beispielwerte; Struktur von „W3 Do Schwelle 4x6“ aus P3, Ausschnitt)

```json
{
  "summary": "Workout „W3 Do Schwelle 4x6“: Intervalle 4/4 im Zielbereich (Ø 4:40 /km), Trabpausen 2/4 im HF-Bereich.",
  "data": {
    "cols": ["nr", "schritt", "wdh", "ziel", "ist", "dauer", "distanz", "hf_med", "getroffen"],
    "rows": [
      ["1", "Einlaufen locker", null,  "100–150 bpm",   "92 % im Bereich", "11:18", "2,00 km", 138, "ja"],
      ["2", "SCHWELLE 4:50",    "1/4", "4:35–4:45 /km", "4:39 /km",        "6:00",  "1,29 km", 176, "ja"],
      ["3", "Trabpause locker", "1/4", "100–150 bpm",   "64 % im Bereich", "2:30",  "0,37 km", 154, "nein"],
      ["4", "SCHWELLE 4:50",    "2/4", "4:35–4:45 /km", "4:41 /km",        "6:00",  "1,28 km", 180, "ja"]
    ]
  },
  "meta": {"row_count": 4, "truncated": true, "next": "weitere Schritte: activity_splits(activity_id=272, kind=\"steps\", from_idx=5)"}
}
```

Die Spalte `schritt` zeigt die Schritt-Notiz, sonst den Schritttyp.

### C.4 `activity_analyze` (read) — Analyse

```json
{
  "name": "activity_analyze",
  "description": "Serverseitige Auswertung einer Aktivität: segment (Abschnitt nach km oder Minuten), compare (Vergleich mit zweiter Aktivität), hr_drift (aerobe Entkopplung), curve (Verlauf mit höchstens 60 Punkten für render).",
  "parameters": {
    "type": "object",
    "properties": {
      "activity_id": {"type": "integer"},
      "operation": {"type": "string", "enum": ["segment", "compare", "hr_drift", "curve"]},
      "other_activity_id": {"type": "integer", "description": "nur compare"},
      "from_km": {"type": "number"},
      "to_km": {"type": "number"},
      "from_min": {"type": "number"},
      "to_min": {"type": "number"},
      "metric": {"type": "string", "enum": ["hf", "pace", "hoehe", "kadenz", "leistung"], "description": "nur curve"},
      "points": {"type": "integer", "minimum": 10, "maximum": 60}
    },
    "required": ["activity_id", "operation"]
  }
}
```

| Operation | Ergebnis |
|---|---|
| `segment` | Eine Zeile im Split-Format für den Bereich (km **oder** Minuten), plus Dauer und Distanz |
| `compare` | Tabelle `kennzahl, a, b, differenz`. Nur bei gleichem Sportprofil; bei stark unterschiedlicher Distanz mit Hinweis. |
| `hr_drift` | Werte pro Hälfte (Pace, HF, Effizienz), Entkopplung in %, Einordnung nach verbreiteter Faustregel (< 5 % stabil, 5–10 % moderat, > 10 % deutlich). Wenn nicht anwendbar: Grund (B.2). |
| `curve` | `{x_unit, y_unit, x[], y[]}` mit höchstens 60 Punkten (Mittelwert pro Bucket). Gedacht für `render(TimeSeriesChart)`. Pace kommt als `s/km` mit `y_format: "pace"` (render-Erweiterung, G.2) und wird je Bucket aus Distanz und Zeit berechnet (B.1). |

**Beispiel `compare`** (#812 gegen #798)

```json
{
  "summary": "Der Morgenlauf (07.10.) war 0:25 /km langsamer als der Tempolauf (01.10.), bei 16 Schlägen niedrigerer Ø-HF. Effizienz nahezu gleich (1,32 vs. 1,30 m pro Herzschlag).",
  "data": {
    "cols": ["kennzahl", "a: 07.10. Morgenlauf", "b: 01.10. Tempolauf", "differenz a−b"],
    "rows": [
      ["distanz",   "8,02 km",          "10,05 km",         "−2,03 km"],
      ["pace",      "5:10 /km",         "4:45 /km",         "+0:25 /km"],
      ["hf_avg",    "146",              "162",              "−16"],
      ["hf_max",    "171",              "178",              "−7"],
      ["kadenz",    "172 spm",          "180 spm",          "−8 spm"],
      ["leistung",  "269 W",            "301 W",            "−32 W"],
      ["hm_auf",    "64 m",             "48 m",             "+16 m"],
      ["effizienz", "1,32 m/Herzschlag", "1,30 m/Herzschlag", "+0,02"]
    ]
  }
}
```

Effizienz ist hier Geschwindigkeit in m/min geteilt durch die Ø-HF, also Meter pro Herzschlag.

`activity_analyze` liest Sekundendaten **einer** Aktivität aus `activity_stream` (eine Zeile je Kanal). Das ist eng begrenzt und damit konform zu `02` §3.

### C.5 `best_efforts` (read) — Lauf-Bestleistungen

```json
{
  "name": "best_efforts",
  "description": "Lauf-Bestleistungen: schnellste Abschnitte über 800 m bis 100 km aus allen GPS-Läufen, auch innerhalb längerer Läufe.",
  "parameters": {
    "type": "object",
    "properties": {
      "distances": {"type": "array", "items": {"type": "string", "enum": ["800m", "1500m", "3000m", "5k", "10k", "hm", "m", "50k", "100k"]}},
      "period": {"type": "string", "enum": ["all", "ytd", "12m", "90d", "custom"]},
      "from_date": {"type": "string"},
      "to_date": {"type": "string"},
      "top_n": {"type": "integer", "minimum": 1, "maximum": 5}
    }
  }
}
```

**Regeln**

- Defaults: alle Distanzen, `period=all`, `top_n=1`.
- Distanzen ohne passenden Lauf erscheinen mit `—` und einer Begründung.
- Einträge mit `quality='partial'` werden gekennzeichnet.

**Beispiel** (Beispielwerte, `period=ytd`)

```json
{
  "summary": "Bestzeiten 2026: 800 m 3:21 · 1.500 m 6:31 · 3.000 m 13:20 · 5 km 22:28 · 10 km 47:41. HM, M, 50 km, 100 km: noch kein Lauf dieser Länge.",
  "data": {
    "cols": ["distanz", "zeit", "pace", "datum", "aktivitaet", "abschnitt", "qualitaet"],
    "rows": [
      ["800 m",   "3:21",  "4:11 /km", "Mi 24.09.2026", "#790 Intervalle 6×800 m", "km 4,2–5,0",  "ok"],
      ["1.500 m", "6:31",  "4:21 /km", "Mi 01.10.2026", "#798 Tempolauf",          "km 3,0–4,5",  "ok"],
      ["3.000 m", "13:20", "4:27 /km", "Mi 01.10.2026", "#798 Tempolauf",          "km 2,8–5,8",  "ok"],
      ["5 km",    "22:28", "4:30 /km", "Mi 01.10.2026", "#798 Tempolauf",          "km 2,4–7,4",  "ok"],
      ["10 km",   "47:41", "4:46 /km", "Mi 01.10.2026", "#798 Tempolauf",          "km 0,0–10,0", "ok"],
      ["HM",      "—", "—", "—", "—", "—", "noch kein Lauf ≥ 21,1 km"]
    ]
  }
}
```

Damit wird Referenzfrage 7 („beste 5-km-Zeit dieses Jahr“) mit `best_efforts(distances=["5k"], period="ytd")` beantwortet.

**Nachtrag 2026-10-17 (Umsetzung AP 3).** Lücken in C.1–C.5, beim Umsetzen so entschieden:

- `activity_splits(kind="lap")`, Spalte `typ`: Workout-Phase (Aufwärmen, Intervall, Erholung, Pause, Auslaufen) nur bei Runden mit `wkt_step_index`; sonst der Auslöser („Auto-Runde (Distanz)“, „manuell“, „Ende“), weil die Uhr auch normale Auto-Runden als `interval` markiert. `schritt` = `wkt_step_index + 1`.
- `kind="steps"`: `wdh` „2/4“ nimmt als Gesamtzahl den höchsten gelaufenen Durchgang des Wiederholungsblocks (die geplante Zahl ist nicht gespeichert). `hf_med` ist hier der zeitgewichtete Mittelwert, `activity_step_result` hat keinen Median. HF-Ziele ohne bpm-Werte (Q3) erscheinen als „HF-Bereich (Ziel unbekannt)“ mit `getroffen` „–“.
- Schwimmen, `kind="distance"`: Spalte `m` zeigt die aufsummierten Meter (100, 200, …). Blöcke à 5 Splits haben `unit` „5 km“ (Rad 25 km, Schwimmen 500 m).
- `activity_analyze(compare)` hat zusätzlich die Zeile `zeit`; bei Schwimmen entfallen `hm_auf` und `effizienz`. `hr_drift` rechnet mit derselben Funktion wie `activity_stats.decoupling_pct` und liest dafür die Pausen-Ereignisse aus dem FIT-Archiv. `curve` liefert nur Daten; `render(TimeSeriesChart)` mit Minutenachse ist G.2 (AP 4).
- `best_efforts`: Datum steht auch in `summary` („5 km 22:05 (20.09.2026)“), damit Eval 19 die Zahlen prüfen kann; ab `top_n > 1` kommt eine Spalte `rang` dazu. Fehlende Distanzen: „kein GPS-Lauf ≥ 21,1 km im Zeitraum“.
- Tool-Smoke-Test gegen die echten 139 Aktivitäten (982 Aufrufe aller fünf Tools): keine Abstürze, keine Obergrenze überschritten.

---

## 7. Teil D — Workouts in Garmin

### D.1 Kairos-Workout-Modell

Kairos hat ein eigenes, validiertes Workout-Modell (Pydantic). Garmins Format kennt nur der Mapper (D.2).

| Feld | Regel |
|---|---|
| `name` | 1–80 Zeichen |
| `sport` | `running` oder `cycling` (V1) |
| `description` | optional, ≤ 500 Zeichen; Kairos hängt einen Marker an (D.6) |
| `steps` | 1–20 Schritte auf oberster Ebene, insgesamt höchstens 30 inklusive der Schritte in Wiederholungen; genau eine Verschachtelungsebene |

**Schritt**

| Feld | Werte |
|---|---|
| `type` | `warmup`, `interval`, `recovery`, `rest`, `cooldown`, `repeat` |
| `end` | `time` (`seconds` 10–21.600), `distance` (`meters` 50–100.000) oder `lap_button` |
| `target` | `none`; `pace` (`from`/`to` als `m:ss` pro km, nur Laufen); `speed` (`low`/`high` in km/h, nur Rad); `hr_range` (`low`/`high` in bpm, **Standard für HF**); `power_range` (W); `cadence_range` (spm bzw. rpm); `hr_zone` (`zone` 1–5, Garmin-Zonen — nur beim Lesen bestehender Garmin-Workouts, das Agent-Schema bietet es nicht an) |
| `repeat` | `iterations` 1–50; `steps` mit Unter-Schritten vom Typ `interval`, `recovery` oder `rest` |
| `note` | optional, Schritt-Notiz, ≤ 60 Zeichen (Garmin `description`); erscheint auf der Uhr. Max' Workouts nutzen sie bis 39 Zeichen; die genaue Grenze prüft AP 0b. |
| `secondary_target` | optional, gleiche Typen wie `target` außer `none` und `hr_zone`, nicht derselbe Typ wie `target`. **Nur aktiv, wenn AP 0b bestätigt, dass die Uhr Sekundärziele anzeigt** (Schalter `WORKOUT_SECONDARY_TARGETS_ENABLED`, Default aus; ohne Schalter fehlt das Feld im Tool-Schema). |

**Semantische Prüfungen** (serverseitig, mit Fehlermeldung an das Modell)

- `pace.from` ist die schnellere Grenze, also gilt `from ≤ to`. Erlaubt sind 2:30–15:00 /km, die Bereichsbreite muss mindestens 0:05 betragen.
- `hr_range` liegt zwischen 60 und 220 bpm, und es gilt `low < high`.
- `warmup` und `cooldown` sind nur auf oberster Ebene erlaubt; ein `repeat` braucht mindestens einen Unter-Schritt.
- Die geschätzte Gesamtdauer darf höchstens 6 h betragen.
- Für `secondary_target` gelten dieselben Grenzen wie für `target`.

**`STEPS_SCHEMA`** — im Tool ausgeschrieben, ohne `$ref` und ohne Rekursion, damit es über litellm bei allen Anbietern funktioniert:

```json
{
  "type": "array",
  "minItems": 1,
  "maxItems": 20,
  "description": "Schritte in Reihenfolge. repeat enthält eigene steps (nur interval/recovery/rest).",
  "items": {
    "type": "object",
    "properties": {
      "type": {"type": "string", "enum": ["warmup", "interval", "recovery", "rest", "cooldown", "repeat"]},
      "iterations": {"type": "integer", "minimum": 1, "maximum": 50},
      "end": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["time", "distance", "lap_button"]},
          "seconds": {"type": "integer"},
          "meters": {"type": "integer"}
        },
        "required": ["type"]
      },
      "target": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["none", "pace", "speed", "hr_range", "power_range", "cadence_range"], "description": "HF immer als hr_range in bpm"},
          "from": {"type": "string", "description": "Pace m:ss pro km, schnellere Grenze"},
          "to": {"type": "string", "description": "Pace m:ss pro km, langsamere Grenze"},
          "low": {"type": "number"},
          "high": {"type": "number"}
        },
        "required": ["type"]
      },
      "secondary_target": "… wie target, ohne none; nur mit WORKOUT_SECONDARY_TARGETS_ENABLED …",
      "note": {"type": "string", "maxLength": 60, "description": "Schritt-Notiz, erscheint auf der Uhr"},
      "steps": {
        "type": "array",
        "maxItems": 10,
        "items": {
          "type": "object",
          "properties": {
            "type": {"type": "string", "enum": ["interval", "recovery", "rest"]},
            "end": "… wie oben, ausgeschrieben …",
            "target": "… wie oben, ausgeschrieben …",
            "secondary_target": "… wie oben …",
            "note": {"type": "string", "maxLength": 60}
          },
          "required": ["type", "end"]
        }
      }
    },
    "required": ["type"]
  }
}
```

**Kurzform.** Eine einzeilige Darstellung für Listen, Vorschauen und Kalendertermine. Sie wird serverseitig erzeugt.

- **Präfixe:** Laufen „Einl.“/„Ausl.“, Rad „Einf.“/„Ausf.“; `recovery` → „Erh.“, `rest` → „Pause“.
- **Ende:** unter 60 s als `45″`, ganze Minuten als `15′`, sonst `1′30″`; Distanz als `800 m` bzw. `5 km`; Runden-Taste als `Taste`.
- **Ziel:** Pace `@ 3:50–4:00`, HF-Bereich `@ 128–150 bpm`, Leistung `@ 230–250 W`, Geschwindigkeit `@ 30–32 km/h`; nur bei gelesenen Garmin-Workouts mit Zonennummer `Z2 (Garmin)`.
- **Trennzeichen:** ` · `; Wiederholungen als `6×(… / …)`.
- **Beispiel:** `Einl. 15′ @ 128–150 bpm · 6×(800 m @ 3:50–4:00 / 2′ Erh.) · Ausl. Taste`

**Schätzung von Dauer und Distanz.** Daraus ergeben sich die Länge des Kalendertermins, Garmins `estimatedDurationInSecs` und die Vorschau.

- **Zeitschritte:** gehen mit ihrer Dauer ein.
- **Distanzschritte:** Distanz geteilt durch die Zielgeschwindigkeit. Bei einem Pace-Ziel wird die Bereichsmitte genommen. Ohne Ziel gilt eine Referenz:
  - Laufen: Median von `avg_moving_pace_s_km` der Läufe der letzten 90 Tage, Fallback 6:00 /km;
  - Rad: Median-Geschwindigkeit, Fallback 25 km/h.
- **`lap_button`:** `WORKOUT_LAP_BUTTON_ESTIMATE_S` (Default 600 s); markiert als „geschätzt“.
- **Beispiel:** 900 s + 6 × (188 s + 120 s) + 600 s = 3.348 s ≈ 56 min. Der Kalendertermin dauert 60 min, mit dem Hinweis „Auslaufen geschätzt“.

### D.2 Mapping Kairos ↔ Garmin

Der Adapter liegt in `connectors/garmin/workout_mapper.py`:

- `to_garmin(model, *, existing=None) -> dict`
- `from_garmin(payload) -> WorkoutModel | Unsupported`

**Struktur (AP 0 bestätigt, Fixtures `tests/fixtures/garmin/workout_*.json`):**

```
{ workoutName, description, sportType{sportTypeId, sportTypeKey}, estimatedDurationInSecs,
  workoutSegments: [{ segmentOrder: 1, sportType{…},
    workoutSteps: [
      { type: "ExecutableStepDTO", stepOrder, stepType{stepTypeId, stepTypeKey},
        endCondition{conditionTypeId, conditionTypeKey}, endConditionValue,
        targetType{workoutTargetTypeId, workoutTargetTypeKey},
        targetValueOne, targetValueTwo, zoneNumber },
      { type: "RepeatGroupDTO", stepOrder, stepType{6, "repeat"}, numberOfIterations,
        endCondition{7, "iterations"}, endConditionValue = numberOfIterations,
        skipLastRestStep, smartRepeat, workoutSteps: [ … ] } ] }] }
```

| Kairos | Garmin-Key | ID | Status AP 0 |
|---|---|---|---|
| `warmup` / `cooldown` / `interval` / `recovery` | warmup / cooldown / interval / recovery | 1 / 2 / 3 / 4 | bestätigt |
| `rest` | rest | 5 | nur laut `garminconnect.workout.StepType`, nicht live geprüft |
| `repeat` | repeat (Ende `iterations`, ID 7) | 6 | bestätigt |
| Ende `lap_button` / `time` / `distance` | lap.button / time / distance | 1 / 2 / 3 | bestätigt; `lap.button` hat `endConditionValue: null` |
| Ziel `none` | no.target | 1 | bestätigt |
| `power_range` | power.zone, `targetValueOne/Two` in W | 2 | bestätigt |
| — (Leistungszone; nicht im Kairos-Modell V1) | power.zone mit `zoneNumber` | 2 | bestätigt, wird von `from_garmin` gelesen |
| `cadence_range` | cadence, Werte in spm bzw. rpm | 3 | bestätigt |
| `hr_zone` | heart.rate.zone, **`zoneNumber`** = 1–5, `targetValueOne/Two` = `null` | 4 | bestätigt |
| `hr_range` | heart.rate.zone, `targetValueOne/Two` in bpm, `zoneNumber` = `null` | 4 | bestätigt |
| `speed` | speed.zone, Werte in m/s | 5 | bestätigt |
| `pace` | pace.zone, Werte in m/s; **`targetValueOne` = langsamere Grenze (kleinerer m/s-Wert)**, `targetValueTwo` = schnellere. Garmin speichert die Reihenfolge so, wie gesendet; der Importer hat die schnellere zuerst geschickt. `to_garmin` sendet langsam/schnell, `from_garmin` sortiert nach Wert. | 6 | bestätigt |
| Sport `running` / `cycling` | running / cycling | 1 / 2 | bestätigt |
| `note` | Schrittfeld `description` | — | in Fixtures vorhanden (bis 39 Zeichen) |
| `secondary_target` | `secondaryTargetType`, `secondaryTargetValueOne/Two`, `secondaryTargetValueUnit`, `secondaryZoneNumber` (IDs wie beim Hauptziel) | — | Felder vorhanden, leer; Anzeige auf der Uhr: AP 0b |

Hinweis zu `hr_zone`: `zoneNumber` verweist auf die in Garmin Connect hinterlegten HF-Zonen des Nutzers. Kairos **erzeugt** HF-Ziele nur als `hr_range` in bpm (E9); `hr_zone` entsteht ausschließlich durch `from_garmin` bei in Garmin Connect angelegten Workouts und wird beim Zurückschreiben unverändert übernommen.

**Regeln**

- Die IDs stehen ausschließlich im Mapper-Modul. Alle Mapper-Tests laufen gegen echte Fixtures aus AP 0. Das ist die Lehre aus Phase 1: Vier von sechs Normalizern passten nicht zur echten API, obwohl die synthetischen Tests grün waren.
- **Ändern:** `get_workout_by_id` → Name, Beschreibung und Segmente ersetzen → alle übrigen Felder (`workoutId`, `ownerId` …) unverändert lassen → `update_workout(id, data)`. **AP 0 bestätigt:** Die ID bleibt erhalten, der Termin bleibt bestehen, Zielwerte bleiben erhalten. Keine Felder schicken, die Garmin nicht kennt (siehe §2.1, Update-Fallstrick).
- **Nicht abbildbar:** Kraftübungen (bis V1.1), Schwimmdrills, unbekannte Ziel- oder Endtypen, mehrere Segmente und verschachtelte Wiederholungen ergeben `Unsupported` mit `supported=false`. Dasselbe gilt für Workouts mit Sekundärziel, solange `WORKOUT_SECONDARY_TARGETS_ENABLED` aus ist. Solche Workouts kann der Agent auflisten, anzeigen, terminieren und löschen, aber nicht ändern; so geht beim Zurückschreiben nichts verloren.
- **Rundweg-Test:** Für jede Fixture gilt `to_garmin(from_garmin(x))` = `x` in allen Feldern, die der Mapper kennt, einschließlich Schritt-Notizen; einzige erlaubte Abweichung ist die Reihenfolge der Pace-Grenzen.

### D.3 Spiegel-Tabellen

```sql
CREATE TABLE garmin_workout (
  id                   bigserial PRIMARY KEY,
  user_id              uuid NOT NULL,
  garmin_workout_id    bigint NOT NULL,
  name                 text NOT NULL,
  sport                text NOT NULL,          -- Garmin sportTypeKey
  description          text,
  steps                jsonb,                  -- Kairos-Modell; NULL wenn nicht abbildbar
  supported            boolean NOT NULL,
  short_notation       text,
  estimated_duration_s integer,
  origin               text NOT NULL CHECK (origin IN ('kairos','garmin')),
  kairos_marker        text,                   -- Idempotenz-Marker (D.6)
  garmin_updated_at    timestamptz,
  raw_payload_id       integer REFERENCES raw_payload(id),
  synced_at            timestamptz NOT NULL,
  UNIQUE (user_id, garmin_workout_id)
);

CREATE TABLE garmin_workout_schedule (
  id                  bigserial PRIMARY KEY,
  user_id             uuid NOT NULL,
  workout_id          bigint NOT NULL REFERENCES garmin_workout(id) ON DELETE CASCADE,
  garmin_schedule_id  bigint,                  -- NULL, bis die Garmin-ID bekannt ist
  scheduled_date      date NOT NULL,           -- Garmin kennt nur das Datum
  start_at            timestamptz,             -- geplante Uhrzeit (nur Kairos/Google)
  calendar_event_id   uuid REFERENCES calendar_event(id) ON DELETE SET NULL,
  plan_block_id       uuid REFERENCES plan_block(id) ON DELETE SET NULL,  -- ab Stufe 3 befüllt
  status              text NOT NULL CHECK (status IN ('scheduled','pending_id','inconsistent')),
  origin              text NOT NULL CHECK (origin IN ('kairos','garmin')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, garmin_schedule_id)
);
```

Die Typen der Fremdschlüssel entsprechen den Primärschlüsseln im Code: `calendar_event.id` und `plan_block.id` sind `uuid`, `raw_payload.id` ist `integer`.

**Spiegel-Abgleich** (`refresh_workout_mirror(user_id)`)

1. **Workouts.** Die Garmin-Liste wird vollständig paginiert abgerufen und per Upsert übernommen. Lokale Zeilen ohne Gegenstück werden gelöscht; ihre Termine fallen per Cascade weg. Nur für neue oder geänderte Workouts (`garmin_updated_at`) wird zusätzlich `get_workout_by_id` aufgerufen, dann `from_garmin`. Rohantworten landen in `raw_payload` (`kind='workout'`).
2. **Termine.** Der Garmin-Kalender wird für das Fenster heute − 7 bis heute + 90 Tage abgeglichen. Lokale Termine ohne Gegenstück werden gelöscht. Ein verknüpfter Google-Termin bleibt dabei bestehen und wird im Tool-Ergebnis als „verwaist“ gemeldet, denn der Lese-Pfad schreibt nie extern.
3. **Sperre.** Höchstens ein Abgleich pro Nutzer alle `WORKOUT_MIRROR_REFRESH_S` (Default 300 s). Mit `force_refresh` frühestens nach 60 s.

**Listen-Methoden (AP 0):** Workouts über `get_workouts(start, limit=100)`, solange eine volle Seite kommt. Termine über `get_scheduled_workouts(year, month)` für jeden Monat, der das Fenster berührt (für −7 bis +90 Tage also 4–5 Aufrufe); nur `itemType == "workout"` übernehmen und per `id` deduplizieren, da sich die Monatsraster überlappen. `id` ist die Schedule-ID, `workoutId` das Workout.

### D.4 Workout-Tools

Schreibende Tools liefern immer das gleiche Ergebnisformat, auch bei Teilerfolg:

```json
{
  "summary": "34 von 37 Workouts gelöscht, 3 fehlgeschlagen (Garmin 500).",
  "data": {"erledigt": ["…höchstens 20 Namen…"], "fehlgeschlagen": [{"id": 51, "name": "…", "grund": "…"}], "uebersprungen": []},
  "meta": {"truncated": true}
}
```

#### `workout_list` (read)

```json
{
  "name": "workout_list",
  "description": "Listet die Workouts im Garmin-Konto (auch in Garmin Connect angelegte) mit Kurzform, geschätzter Dauer und geplanten Terminen.",
  "parameters": {
    "type": "object",
    "properties": {
      "sport": {"type": "string", "enum": ["running", "cycling", "other"]},
      "name_contains": {"type": "string"},
      "scheduled_from": {"type": "string"},
      "scheduled_to": {"type": "string"},
      "limit": {"type": "integer", "minimum": 1, "maximum": 50},
      "offset": {"type": "integer", "minimum": 0},
      "force_refresh": {"type": "boolean"}
    }
  }
}
```

- Spalten: `id, name, sport, kurzform, dauer, termine, herkunft`. `termine` zeigt die nächsten drei Daten und „…“.
- `summary` nennt die Gesamtzahl, z. B. „37 Workouts, davon 5 in den nächsten 14 Tagen terminiert“, und verwaiste Google-Termine.

#### `workout_get` (read)

```json
{
  "name": "workout_get",
  "description": "Zeigt ein Garmin-Workout im Detail: alle Schritte mit Ende und Ziel, geschätzte Dauer und geplante Termine.",
  "parameters": {
    "type": "object",
    "properties": {
      "workout_id": {"type": "integer"}
    },
    "required": ["workout_id"]
  }
}
```

Das Tool liefert:

- Name, Sportart und die Schritte als nummerierte Zeilen mit Schritt-Notiz, z. B. „1. Einlaufen · 15:00 · 128–150 bpm (Notiz: Einlaufen locker)“ und „2. 6× wiederholen: a) 800 m · 3:50–4:00 /km  b) Erholung · 2:00“;
- die geschätzte Dauer;
- die Termine (ID, Datum, Uhrzeit, Google-Termin ja/nein);
- `supported`.

#### `workout_create` (write)

```json
{
  "name": "workout_create",
  "description": "Legt ein strukturiertes Workout in Garmin an (Laufen/Rad), optional direkt terminiert inkl. Google-Kalendertermin. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "name": {"type": "string"},
      "sport": {"type": "string", "enum": ["running", "cycling"]},
      "description": {"type": "string"},
      "steps": "<STEPS_SCHEMA aus D.1>",
      "schedule_start_at": {"type": "string", "description": "optional, lokal YYYY-MM-DDTHH:MM"}
    },
    "required": ["name", "sport", "steps"]
  }
}
```

- **Vorschau:** Name, Kurzform, geschätzte Dauer und Distanz (ggf. mit „geschätzt“), dazu optional der Termin mit Datum, Beginn–Ende und Kollisionen mit bestehenden Kalenderterminen.
- **Ausführung:**
  1. Workout in Garmin anlegen (mit Marker).
  2. Optional terminieren.
  3. Google-Termin anlegen.
  4. Spiegelzeilen schreiben.

  Scheitert Schritt 2 oder 3, bleibt das Workout erhalten. Der Termin wird kompensiert (D.6), und das Ergebnis meldet einen Teilerfolg.

#### `workout_update` (write)

```json
{
  "name": "workout_update",
  "description": "Ändert ein Garmin-Workout: Name, Beschreibung und/oder die komplette Schrittfolge. Geplante Termine bleiben erhalten. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "workout_id": {"type": "integer"},
      "name": {"type": "string"},
      "description": {"type": "string"},
      "steps": "<STEPS_SCHEMA aus D.1>"
    },
    "required": ["workout_id"]
  }
}
```

- **Regeln:**
  - Mindestens eines der Felder `name`, `description` oder `steps` ist gesetzt.
  - `steps` ersetzt die Schrittfolge vollständig.
  - Bei `supported=false` gibt das Tool den Fehler „nur in Garmin Connect bearbeitbar“ zurück.
- **Vorschau:** alt → neu (Kurzform, Dauer) und die betroffenen künftigen Termine.
- **Ausführung:**
  1. Workout frisch per `get_workout_by_id` holen.
  2. Änderungen einarbeiten und `update_workout` aufrufen.
  3. Ändern sich Name oder geschätzte Dauer, werden die künftigen verknüpften Google-Termine ersetzt (löschen + neu anlegen; ein PATCH existiert nicht).
  4. Spiegel aktualisieren.

#### `workout_schedule` (write)

```json
{
  "name": "workout_schedule",
  "description": "Terminiert ein Garmin-Workout (erscheint auf der Uhr) und legt einen Google-Kalendertermin an. Mit replace_schedule_id wird ein bestehender Termin verschoben. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "workout_id": {"type": "integer"},
      "start_at": {"type": "string", "description": "lokal, YYYY-MM-DDTHH:MM"},
      "replace_schedule_id": {"type": "integer"}
    },
    "required": ["workout_id", "start_at"]
  }
}
```

- **Regeln:**
  - `start_at` darf nicht in der Vergangenheit liegen.
  - Das Garmin-Datum ist das lokale Datum von `start_at` in der Heimatzeitzone des Nutzers.
  - Steht dasselbe Workout am selben Tag schon im Kalender, warnt die Vorschau.
- **Ausführung (neu):**
  1. In Garmin terminieren.
  2. Google-Termin anlegen.
  3. Spiegelzeile schreiben.
- **Ausführung (verschieben):**
  1. Neuen Termin in Garmin anlegen.
  2. Neuen Google-Termin anlegen.
  3. Alten Garmin-Termin entfernen.
  4. Alten Google-Termin löschen.
  5. Spiegel aktualisieren.

  Erst anlegen, dann entfernen: Bei einem Fehler bleibt mindestens ein gültiger Termin bestehen.
- **Schedule-ID:** Sie steht in der Antwort von `schedule_workout` als **`workoutScheduleId`** (AP 0 bestätigt; dieselbe ID erscheint als `id` im Kalender). Der Polling-Fallback und `status='pending_id'` bleiben nur als Absicherung für den Fall, dass das Feld fehlt.

#### `workout_unschedule` (destructive)

```json
{
  "name": "workout_unschedule",
  "description": "Entfernt geplante Workout-Termine aus Garmin samt zugehörigen Google-Terminen; die Workouts selbst bleiben. Auswahl per IDs oder Zeitraum. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "schedule_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 100},
      "from_date": {"type": "string"},
      "to_date": {"type": "string"}
    }
  }
}
```

- **Auswahl:** Mindestens ein Kriterium ist gesetzt. Mehrere Kriterien werden UND-verknüpft. Nach dem Auflösen sind höchstens 100 Termine erlaubt. Ein Filter `plan_id` kommt mit Stufe 3 (§8).
- **Vorschau:** die aufgelöste Liste mit Datum, Uhrzeit und Workout.
- **Ausführung pro Termin:**
  1. In Garmin entfernen (`unschedule_workout` antwortet mit leerem Objekt; 404 heißt „bereits entfernt“).
  2. Den verknüpften Google-Termin löschen (`source='kairos'`).
  3. Spiegelzeile löschen.

#### `workout_delete` (destructive)

```json
{
  "name": "workout_delete",
  "description": "Löscht Workouts aus dem Garmin-Konto, einzeln oder gesammelt (IDs, Namensfilter, Sportart oder alle). Künftige Termine und deren Google-Termine werden mit entfernt. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "workout_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 200},
      "all": {"type": "boolean"},
      "name_contains": {"type": "string"},
      "sport": {"type": "string", "enum": ["running", "cycling", "other"]}
    }
  }
}
```

- **Auswahl:**
  - `all=true` ist nicht mit anderen Kriterien kombinierbar; die übrigen Kriterien werden UND-verknüpft.
  - Die Auswahl wird in der Vorschau nach einem erzwungenen Spiegel-Abgleich aufgelöst. „Alle“ bedeutet also: alle zum Zeitpunkt der Vorschau.
  - Höchstens 200 Workouts. Bei mehr bricht das Tool mit dem Hinweis ab, die Auswahl einzugrenzen.
- **Vorschau:** Anzahl der Workouts, Anzahl der betroffenen künftigen Termine und Google-Termine, die ersten 20 Namen und „… und N weitere“. (Workouts aus Garmin-Coach-Plänen stehen laut AP 0 nicht in der Workout-Bibliothek und können hier nicht auftauchen.)
- **Ausführung**, sequenziell und gedrosselt, pro Workout:
  1. Künftige Termine entfernen (wie `workout_unschedule`).
  2. `delete_workout` aufrufen.
  3. Spiegelzeile löschen.

  **AP 0:** Löscht man ein terminiertes Workout, entfernt Garmin den künftigen Termin mit (Kalender leer, `get_scheduled_workout_by_id` → 404). Schritt 1 ist für Garmin also nicht nötig, bleibt aber für die verknüpften Google-Termine. Das Verhalten bei **vergangenen** Terminen ist nicht geprüft (es wurde kein vergangener Termin gelöscht). Vergangene Google-Termine bleiben als Historie stehen.
- **Abbruch:**
  - 429 oder Auth-Fehler: sofort stoppen; das Ergebnis nennt Erledigtes und Offenes.
  - 404: zählt als bereits gelöscht.
  - Andere Fehler: das Workout gilt als fehlgeschlagen, die übrigen werden weiter bearbeitet.

### D.5 Kopplung an Google Calendar

| Regel | Festlegung |
|---|---|
| Titel | `Training: {Workout-Name}` (gekürzt auf 60 Zeichen) |
| Beschreibung | Kurzform, geschätzte Dauer, „Garmin-Workout · terminiert von Kairos“ |
| Dauer | Start + Schätzung, aufgerundet auf 5 min, mindestens 15 min. Bei Planblöcken gelten die Blockzeiten. |
| Anlegen und Löschen | über den bestehenden Kalenderpfad (`_create_calendar_event` / `_delete_calendar_event`, `source='kairos'`) |
| Ändern | löschen + neu anlegen (es gibt keinen PATCH-Endpoint) |
| Kollisionen | werden in der Vorschau angezeigt, blockieren aber nicht |
| Google nicht verbunden | Die Vorschau warnt: „Termin wird nur in Garmin angelegt“. Bestätigt der Nutzer, wird nur in Garmin terminiert. |

### D.6 Konsistenz zwischen Garmin, Google und DB

- **Savepoint pro Element** (`session.begin_nested()`). Scheitert ein Element, werden nur dessen lokale Änderungen zurückgerollt.
- **Keine Exception bei Element-Fehlern.** Fehler einzelner Elemente beenden das Tool nicht, und die Bestätigungstransaktion committet die erfolgreichen Elemente. Das behebt nebenbei einen bekannten Restpunkt: Wenn `plan_commit` heute bei Block N scheitert, existieren die Google-Termine 1 bis N−1, ihre lokalen Zeilen sind aber zurückgerollt.
- **Reihenfolge pro Element:** Garmin → Google → DB.
  - Scheitert Google, wird der Garmin-Schritt kompensiert (Termin entfernen).
  - Scheitert auch die Kompensation, bekommt die Zeile `status='inconsistent'`, und der Nutzer erhält einen konkreten Hinweis.
- **Wiederaufnahme.** Ist der Snapshot-Status `executing` (G.1), läuft die Ausführung im Wiederaufnahme-Modus:
  - Workouts werden vor dem Anlegen über `kairos_marker` gesucht.
  - Termine werden über das Paar (Workout, Datum) erkannt.
- **Marker.** Die letzte Zeile der Beschreibung lautet `[kairos:<8 hex>]`, ein Hash aus `tool_call_id` und Elementindex. Der Marker ist in Garmin Connect sichtbar. Die Alternative, ein Abgleich über Name und Anlagezeit, wäre schwächer.

### D.7 Garmin-Schreibdienst und Client

- **Gemeinsamer `GarminClientProvider`** für Sync und Tools (Refactor von `_build_garmin_client`):
  - nur Token-Login. Ein vom Client erneuertes Token wird nach jeder Operation verschlüsselt zurückgeschrieben (eigene kurze Transaktion; gleicher Mechanismus wie `refresh_token`).
  - Bei Ablehnung wird `reauth_required` in einer **eigenen** Transaktion gesetzt, nie in der des Aufrufers. Fehlertext für das Tool: „Garmin-Verbindung muss neu angemeldet werden (Konto → Garmin)“.
  - In-Process-Cache je Nutzer mit TTL 10 min, invalidiert bei einem Auth-Fehler.
- **Serialisierung:** ein `asyncio.Lock` je Nutzer für alle Garmin-Schreibzugriffe und Spiegel-Abgleiche; Aufrufe über `asyncio.to_thread`.
- **Drosselung:**
  - mindestens `GARMIN_WRITE_MIN_INTERVAL_S` (Default 1,0 s) zwischen zwei Schreib-Requests;
  - höchstens `GARMIN_WRITE_MAX_PER_HOUR` (Default 300) pro Nutzer;
  - bei Überschreitung Abbruch mit Teilergebnis.
- **Wiederholungen:**
  - Anlegen und Terminieren werden nie automatisch wiederholt.
  - Ändern, Löschen und Termin entfernen werden einmal nach 2 s wiederholt, bei 5xx oder Netzfehler.
  - 429: sofortiger Stopp und 15 min Sperre für weitere Garmin-Schreibzugriffe dieses Nutzers. Hintergrund ist der Cloudflare-Vorfall aus Phase 1.
- **Archiv:** Jede gesendete und empfangene Workout-JSON landet in `raw_payload` (`kind='workout'`, dedupliziert über `content_hash`).
- **Audit:** Jeder ausgeführte Schreibvorgang wird in `audit_log` geschrieben. Die Tabelle existiert laut AP 0 noch nicht und wird in AP 5 nach `06` §7 angelegt.

---

## 8. Teil E — Planung (verschoben nach Stufe 3)

Seit dem Brainstorming (D19, D28) erzeugt Kairos Trainingspläne im **Coach-Modus** aus einer
Wissensbank; die Platzhalter-Templates (früher E.2) entfallen. Die Kopplung der Planung an
Garmin wird deshalb mit dem Coach-Modus in Stufe 3 gebaut und dort spezifiziert.

**In Stufe 1 gilt:** `plan_propose`, `plan_commit`, `plan_adjust` und `plan_progress` bleiben
unverändert (Kalendertermine, kein Garmin). Workouts legt der Chat direkt über die
Workout-Tools aus Teil D an.

**Vorgaben für die Spec von Stufe 3** (aus der bisherigen Fassung dieses Teils übernommen):

- Ein Garmin-Workout pro Planblock, keine Wiederverwendung (E7); die Verknüpfung läuft über
  `garmin_workout_schedule.plan_block_id`, damit es keine zirkulären Fremdschlüssel gibt.
- `plan_commit` überträgt je Block: Workout anlegen → terminieren → Google-Termin anlegen →
  lokale Zeilen schreiben. Bereits übertragene Blöcke werden übersprungen (idempotent);
  Teilerfolge folgen D.4 und D.6; bei vielen Blöcken Fortschritt per `tool_progress` (G.1).
- `plan_adjust` ändert übertragene Blöcke per `workout_update` (gleiche Garmin-ID, Termin bleibt)
  und ersetzt den Google-Termin.
- „Plan verwerfen“ ist kein Agent-Tool; aufgeräumt wird über einen dann neuen Filter `plan_id`
  in `workout_unschedule` und `workout_delete`.
- Die Soll/Ist-Auswertung pro Schritt (B.6) ist die Datengrundlage für die Wochenbesprechung.

---

## 9. Teil F — Aktivitäten in Garmin bearbeiten und löschen

#### `activity_update` (write)

```json
{
  "name": "activity_update",
  "description": "Ändert Name und/oder Beschreibung einer Aktivität in Garmin. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "activity_id": {"type": "integer"},
      "name": {"type": "string"},
      "description": {"type": "string"}
    },
    "required": ["activity_id"]
  }
}
```

- **Vorschau:** alt → neu.
- **Ausführung:** `set_activity_name` bzw. `set_activity_description` (je ein Request), danach die lokalen Spalten aktualisieren.

#### `activity_delete` (destructive)

```json
{
  "name": "activity_delete",
  "description": "Löscht Aktivitäten unwiderruflich aus Garmin (höchstens 20). Kairos behält die Rohdaten im Archiv. Erfordert Bestätigung.",
  "parameters": {
    "type": "object",
    "properties": {
      "activity_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 20}
    },
    "required": ["activity_ids"]
  }
}
```

- **Vorschau:**
  - Datum, Name und Distanz je Aktivität.
  - Warnung: in Garmin unwiderruflich; Trainingslast-Verlauf und Bestleistungen ändern sich.
  - **Betroffene Bestleistungen werden namentlich genannt**, z. B. „hält deine 5-km-Bestzeit“.
- **Ausführung:**
  1. `delete_activity` aufrufen.
  2. Soft-Delete (`deleted_reason='kairos'`).
  3. Abgeleitete Zeilen entfernen.
  4. Tageskennzahlen der betroffenen Tage neu berechnen.

---

## 10. Teil G — Harness-Erweiterungen

### G.1 Vorschau-Snapshots für Bestätigungen

**Problem.** Heute bestätigt der Nutzer die rohen Argumente des Modells. Bei `workout_delete(all=true)` wüsste er nicht, *was* gelöscht wird. Außerdem würde „alle“ erst bei der Ausführung aufgelöst und könnte dann mehr umfassen als zum Zeitpunkt der Bestätigung.

**Lösung.** `ToolSpec` bekommt eine optionale Funktion `preview(args, ctx) -> Preview(card, resolved_args)`. Sie liest nur; sie darf allerdings den Workout-Spiegel auffrischen.

```sql
CREATE TABLE proposal_snapshot (
  conversation_id  uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  tool_call_id     text NOT NULL,
  user_id          uuid NOT NULL,
  tool_name        text NOT NULL,
  card             jsonb NOT NULL,      -- was der Nutzer sieht
  resolved_args    jsonb NOT NULL,      -- was ausgeführt wird
  status           text NOT NULL CHECK (status IN ('pending','executing','done','rejected','expired')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  executing_since  timestamptz,
  executed_at      timestamptz,
  result_summary   text,
  PRIMARY KEY (conversation_id, tool_call_id)
);
```

**Ablauf**

1. Der Dispatcher fängt einen bestätigungspflichtigen Aufruf ab und ruft `preview` auf. Bei einem Validierungsfehler bekommt das Modell ein Fehlerergebnis, und es entsteht kein Proposal.
2. Der Snapshot wird gespeichert, und das SSE-Event `proposal` überträgt die `card`.
3. **Bestätigen, Transaktion 1:**
   - Snapshot `FOR UPDATE` sperren.
   - Ist der Status nicht `pending`, folgt 409. Bei `executing` ist das `proposal_in_progress`.
   - Ist der Snapshot älter als `PROPOSAL_STALE_AFTER_S` (Default 1.800 s), folgt 409 `proposal_stale`. Das Modell muss dann neu vorschlagen.
   - Sonst Status auf `executing` setzen, `executing_since` setzen und **committen**.
4. **Bestätigen, Transaktion 2:** Ausführung mit `resolved_args`, nie mit den Modell-Argumenten. Im selben Commit werden das Tool-Ergebnis als Nachricht und der Status `done` geschrieben.
5. **Absturz zwischen 3 und 4:** Der Status bleibt `executing`. Nach `PROPOSAL_RECOVERY_AFTER_S` (Default 600 s) ist eine erneute Bestätigung im Wiederaufnahme-Modus erlaubt (D.6).
6. `GET …/messages` liefert für offene Vorschläge die `card`, damit sie nach einem Reload wieder erscheinen.
7. Tools ohne `preview` verhalten sich wie bisher (card = Argumente).

Damit wird die heutige Regel aus Harness v2 („`FOR UPDATE` bis zum einzigen Commit“) durch eine Zustandsmaschine ersetzt. Doppelte Ausführung bleibt ausgeschlossen, und externe Seiteneffekte gehen bei Teilfehlern nicht mehr verloren.

**Fortschritt.** Für Ausführungen mit mehr als 10 Elementen gibt es ein optionales SSE-Event `tool_progress` mit `{done, total}`, im UI als „12/37“.

### G.2 Tool-Ausgabekontrakt

- `meta.truncated` wird tatsächlich gesetzt. Die Obergrenzen gelten je Tool (C.0); gekürzt wird deterministisch.
- Neue `meta`-Felder: `next` und `quality`.
- Tabellen sind spaltenförmig (`cols` / `rows`).
- Ein Formatierungsmodul `agent/format.py` (Pace, Dauer, Distanz, Datum, Differenzen) wird zentral getestet. Kein Tool formatiert selbst.
- `render` bekommt für `TimeSeriesChart` ein optionales `y_format: "pace"`: Die Achse zeigt m:ss, die Daten bleiben in s/km.

### G.3 Budget für Tool-Schemas

Ein CI-Test summiert die serialisierten Schemas aller Tools und schlägt bei mehr als **18.000 Zeichen** fehl. Heute sind es 5.346 Zeichen für 12 Tools; nach dieser Spec werden rund 15.000 erwartet. Die Schwelle für das zweistufige Laden aus `03` §4.3 liegt bei mehr als 30 Tools oder mehr als 6.000 Schema-Tokens.

### G.4 Token-Telemetrie (minimal)

Das `usage`-Objekt von litellm wird pro LLM-Aufruf in `structlog` geloggt und an der Assistant-Nachricht gespeichert (`input_tokens`, `output_tokens`). Das ist die Grundlage für die Median-Prüfung aus `03` §2 und §8, und die neuen Tools vergrößern den Input messbar.

### G.5 Systemprompt und Lagebild

Ergänzung im Systemprompt (rund 120 Tokens):

- Für Fragen zu einzelnen Einheiten `activity_get` nutzen, ohne ID für die letzte Aktivität. Kilometerwerte kommen über `activity_splits`, Bestzeiten über `best_efforts`. Zahlen nur aus Tool-Ergebnissen übernehmen.
- Ob ein Workout getroffen wurde, kommt aus `activity_splits(kind="steps")`.
- HF-Ziele immer als `hr_range` in bpm. Nennt der Nutzer eine Zone („Zone 2“), die bpm-Grenzen aus der Zeile `HF-Zonen` im Lagebild übernehmen, nicht schätzen.
- Workouts nur mit konkreter Uhrzeit terminieren. Ohne Angabe erst freie Blöcke über `query_calendar(duration_minutes=…)` suchen.
- Mehrere Workouts in **einem** Aufruf von `workout_delete` bzw. `workout_unschedule` löschen, nicht einzeln.

Das Lagebild bekommt dafür eine feste Zeile (≈ 30 Tokens), z. B. „HF-Zonen (HFmax 214, eingetragen): Z1 107–128 · Z2 128–150 · Z3 150–171 · Z4 171–193 · Z5 193–214 bpm“. Fehlt die HFmax, steht dort „HF-Zonen: HFmax fehlt (Einstellungen)“ (A.6).

Optional zeigt das Lagebild die letzte Aktivität mit ID, z. B. „Letzte Aktivität: Lauf 07.10., 8,02 km (#812)“. Dann kann der Agent `activity_splits` direkt aufrufen.

---

## 11. Gesamtübersicht der Tools (26)

| Tool | Klasse | Ausführung | Status |
|---|---|---|---|
| `query_health` | read | direkt | unverändert |
| `analyze_records` | read | direkt | unverändert |
| `query_calendar` | read | direkt | unverändert |
| `recall` | read | direkt | unverändert |
| `remember` | write | direkt (Undo-Chip) | unverändert |
| `render` | read | direkt | geändert (`y_format`) |
| `propose_calendar_event` | write | Bestätigung | unverändert |
| `delete_calendar_event` | destructive | Bestätigung | unverändert |
| `plan_propose` | read | direkt (Entwurf) | unverändert; Neubau im Coach-Modus (Stufe 3) |
| `plan_commit` | write | Bestätigung | unverändert; Garmin-Kopplung in Stufe 3 |
| `plan_adjust` | write | Bestätigung | unverändert; Garmin-Kopplung in Stufe 3 |
| `plan_progress` | read | direkt | unverändert |
| `activity_search` | read | direkt | **neu** |
| `activity_get` | read | direkt | **neu** |
| `activity_splits` | read | direkt | **neu** |
| `activity_analyze` | read | direkt | **neu** |
| `best_efforts` | read | direkt | **neu** |
| `workout_list` | read | direkt (Spiegel) | **neu** |
| `workout_get` | read | direkt (Spiegel) | **neu** |
| `workout_create` | write | Bestätigung | **neu** |
| `workout_update` | write | Bestätigung | **neu** |
| `workout_schedule` | write | Bestätigung | **neu** |
| `workout_unschedule` | destructive | Bestätigung | **neu** |
| `workout_delete` | destructive | Bestätigung | **neu** |
| `activity_update` | write | Bestätigung | **neu** |
| `activity_delete` | destructive | Bestätigung | **neu** |

---

## 12. Evaluierung und Validierung

### 12.1 Neue Eval-Fälle (17–26)

| # | Frage | Erwartete Tools | Prüfungen |
|---|---|---|---|
| 17 | „Wie war mein letzter Lauf?“ | `activity_get` | Distanz, Ø-Pace und Ø-HF exakt wie im Tool-Ergebnis |
| 18 | „Zeig mir die Kilometerzeiten meines letzten Laufs.“ | `activity_splits` (ggf. vorher `activity_get`) | schnellster und langsamster km exakt |
| 19 | „Was war meine beste 5-km-Zeit dieses Jahr?“ (= Referenzfrage 7) | `best_efforts` | Zeit und Datum exakt |
| 20 | „Vergleich meinen Lauf von gestern mit dem letzten Tempolauf.“ (= Referenzfrage 10) | `activity_search` → `activity_analyze(compare)` | Differenzen für Pace und HF exakt |
| 21 | „Wie lief meine letzte Schwimmeinheit?“ | `activity_get(sport_profile=swimming)` | Pace /100 m exakt, Hinweis zur HF genannt |
| 22 | „Leg mir für morgen 18:30 ein Intervalltraining an: 15 min einlaufen, 6×800 m in 3:50–4:00 mit 2 min Trabpause, auslaufen.“ | `workout_create` mit `schedule_start_at` | Proposal, Schritte exakt. Nach Bestätigung: Workout, Garmin-Termin, Google-Termin 18:30–19:30 |
| 23 | „Verschieb das Workout auf Donnerstag 7 Uhr.“ | `workout_schedule(replace_schedule_id)` | danach genau ein Termin; alter Google-Termin weg |
| 24 | „Mach daraus 8 Wiederholungen.“ | `workout_get` → `workout_update` | `iterations = 8`, Termin unverändert |
| 25 | „Lösch alle Workouts in meinem Garmin-Konto.“ | `workout_delete(all=true)` | eine Bestätigung mit korrekter Anzahl, danach 0 Workouts |
| 26 | „Habe ich bei meiner letzten Schwelle die Intervalle getroffen?“ | `activity_search` bzw. `activity_get` → `activity_splits(kind="steps")` | Zahl der getroffenen und bewerteten Schritte sowie Ø-Pace der Intervalle exakt wie im Tool-Ergebnis |

### 12.2 Testumgebung für Schreibfälle

Die Fälle 22–25 laufen standardmäßig gegen `FakeGarminWorkoutClient` und einen Fake-Kalender-Client (beide In-Memory). Gegen ein echtes Konto laufen sie nur mit dem Flag `--live-garmin` und einem **Testkonto**. Fall 25 darf nie gegen das eigene Konto laufen.

### 12.3 Datenvalidierung

Die Validierung ergibt einen einmaligen Bericht in AP 2 und danach Regressionstests mit fixierten Beispielaktivitäten.

| # | Prüfung | Kriterium |
|---|---|---|
| V1 | Km-Splits gegen Uhr-Runden (Läufe mit Auto-Lap 1 km, aus `lap_mesgs`) | Zeitdifferenz ≤ 1 s in ≥ 95 % der Splits |
| V2 | Best Effort 5 km bzw. 1 km (intern berechnet) gegen Garmins `fastestSplit_5000` bzw. `fastestSplit_1000` je Aktivität | Abweichung ≤ max(2 s, 1 %) in ≥ 90 % der Läufe |
| V3 | Bestwert über die gesamte Historie für 5 km und 10 km gegen Garmin-PR (typeId 3: 1.325,4 s = 22:05; typeId 4: 2.710,2 s = 45:10; Stand 07.10.2026) | Abweichung ≤ max(2 s, 1 %), sofern die PR-Aktivität (`activityId`) im Archiv liegt. Abweichungen werden erklärt, nicht wegdefiniert. |
| V4 | Σ Hm↑ gegen Garmins `elevationGain` | ±10 % in ≥ 90 % |
| V5 | Ø-Kadenz gegen `averageRunCadence` | ±2 spm |
| V6 | Ø-HF gegen `activity.avg_hr` | ±1 bpm |
| V7 | Soll/Ist (B.6) für Aktivität 272 und zwei weitere Workout-Läufe: Zahl der Ausführungen und Dauer je Ausführung gegen die Runden in Garmin Connect | Ausführungen = Schritte × Wiederholungen; Dauer ±1 s gegen die Summe der zugehörigen Runden |
| V8 | Vollständigkeit von `activity_stream` (AP 1a) | je Aktivität und Kanal Nicht-NULL-Werte = `activity_record`-Zeilen; der neue Kanal `distance_m` ist ausgenommen |

**Nachtrag 2026-10-15 (Bericht `docs/validation/2026-10-15-stufe1-ableitungen-v1-v7.md`).** Erfüllt: V1, V3, V5, V6, V2 für 1 km. Nicht erfüllt: V2 für 5 km und V4. V7 ist nach Wortlaut nicht erfüllt (9/10, 9/10, 7/8 — letzte Erholung nicht gelaufen); erfüllt bei geänderter Zählregel — Zählregel zur Bestätigung durch Max. Offene Punkte:

- **V7, Zählregel (vorläufig, zur Bestätigung durch Max):** Vorschlag: „Ausführungen = Schritte × Wiederholungen“ zählt nur gelaufene Ausführungen. Ein geplanter Schritt, der nicht gelaufen wurde, ist keine Ausführung, z. B. die letzte Trabpause in 272: Auf das letzte Intervall folgt dort direkt das Auslaufen.
- **V2, Timer- gegen Gesamtzeit:** B.4 bleibt bei der Timer-Zeit. Garmins `fastestSplit_*` misst die Gesamtzeit; Läufe mit Timer-Stopp im Fenster weichen deshalb ab. Strikt erreicht 5 km 81,4 %, mit Gesamtzeit 94,2 %. Offen (Entscheidung): Der Sprungfilter aus B.4 (ein 1-s-Schritt > 8,5 m/s verwirft das Fenster) trifft GPS-Zittern in Intervall-Läufen und echte Sprints. Ohne Filter erreichen beide Distanzen 100 %.
- **V4:** Die Hysterese in B.1 gilt für Extremwerte. Hoch- und Tiefpunkte zählen voll, sobald die Gegenbewegung 2 m übersteigt; das ist kein Zähler in 2-m-Stufen (korrigiert am 2026-10-15). Auch damit verfehlt V4 das Kriterium: 58,7 %, Median 102 % von Garmin. Garmins Wert ist das `total_ascent`, das die Uhr selbst berechnet; mit Sekunden-Höhendaten in 0,2-m-Auflösung ist er nicht auf ±10 % nachzubauen. Offen (Entscheidung): Wert der Uhr übernehmen, Kriterium ändern oder V4 als nicht erreichbar festhalten.
- **Laufband (vorläufig, zur Bestätigung durch Max):** keine Skalierung der Stream-Distanz auf die (bearbeitete) Garmin-Distanz in Stufe 1. Betroffen ist Aktivität 22 (5,3 statt 7,3 km); Splits und Pace je Schritt bleiben im Stream-Maßstab.

---

## 13. Arbeitspakete und Abnahme

| AP | Inhalt | Abnahme |
|---|---|---|
| **0 Verifikation** | erledigt am 2026-10-13, Ergebnisse in §2.1 | — |
| **0b Uhr-Test** (kein Produktcode) | Ein Wegwerf-Workout mit Sekundärziel (Pace + Kadenz und Pace + HF) und langen Schritt-Notizen anlegen, terminieren und auf die Forerunner 265S synchronisieren. Prüfen, ob die Uhr Sekundärziele anzeigt und Alarme auslöst und wie lang Notizen sein dürfen; danach löschen. | Ergebnis in §2.1; `WORKOUT_SECONDARY_TARGETS_ENABLED` und Notiz-Grenze festgelegt |
| **1a Speicher und FIT-Archiv** (A.2, A.4, A.5) | `payload_format`, `fit_payload_id`, `activity_stream_axis`, `activity_stream`, ZIP-Archiv im Sync, Reprocess mit Nachabruf, Lesepfade (HF-Buckets, Detail-Endpoint) umstellen, FIT-Pause | alle 139 Aktivitäten in `activity_stream` (ZIP oder JSON-Rückfall, Fehlschläge gelistet); V8 erfüllt; ≈ 60 KB je Aktivität |
| **1b TimescaleDB entfernen** (A.7) | `wellness_sample` umbauen, `activity_record` und Extension löschen, Images umstellen, Dump/Restore, Runbook in HANDOVER | Zeilenzahlen vorher = nachher; RLS-CI-Test grün; Testsuite gegen `postgres:16` grün |
| **1c Aktivitäts-Spalten, Abgleich, Tage, HFmax** (A.1, A.3, A.6, A.8) | Migration `activity`, Normalizer-Fixes, Lösch-Abgleich, lokale Tagesgrenzen, HFmax-Regel, `GET/PUT /api/settings/profile`, Einstellungsseite, Recompute der Historie | alle 9 `typeKey`s zugeordnet; Lösch-Abgleich getestet; Testfall 00:30 Ortszeit grün; mit eingetragener HFmax 214 bleibt Max' TRIMP außer an Tagen mit Aktivitäten zwischen 0 und 2 Uhr Ortszeit unverändert |
| **2 Abgeleitete Daten** (Teil B) | vier Tabellen inkl. `activity_step_result`, Rechenregeln, Trigger | Bericht V1–V7, Abweichungen erklärt |
| **3 Lese-Tools** (Teil C) | 5 Tools inkl. `kind="steps"`, Formatierung, Obergrenzen | Eval 17–21 und 26 grün (Referenzfragen 7 und 10 damit erfüllt); Test für die Obergrenzen |
| **4 Harness** (Teil G) | Snapshots, Zustandsmaschine, `tool_progress`, Schema-Budget, Telemetrie | Doppelklick- und Absturz-Tests; Wiederaufnahme getestet |
| **5 Workouts** (Teil D) | Client-Provider, Schreibdienst, Mapper inkl. Schritt-Notizen (Sekundärziele nach AP 0b), Spiegel, 7 Tools, Google-Kopplung, `audit_log` | Mapper-Rundweg gegen alle Fixtures; Eval 22–25 grün (Fake); ein manueller Live-Durchlauf mit einem Wegwerf-Workout |
| ~~**6 Planung** (Teil E)~~ | verschoben nach Stufe 3 (§8) | — |
| **7 Aktivitäten bearbeiten** (Teil F) | 2 Tools | Vorschau nennt betroffene Bestleistungen; Recompute nach dem Löschen getestet |
| **8 Doku** | ADR-0002 (TimescaleDB entfernt), `01`, `02` (Speicherrechnung mit Arrays), `07` (SSD-Bedarf, Images), `README.md`, `08` (Stufenplan), HANDOVER (Runbook A.7) | keine Aussage in der Doku widerspricht dem Code |
| **9 Kraft-Workouts (V1.1)** | Mapper für `StrengthWorkout` (Übung, Sätze, Wiederholungen, Pause, Gewicht), Übungssuche über den Katalog (`exercises.find`/`resolve`), Erweiterung von `workout_create`/`workout_update`; Fixtures aus einem echten Kraft-Workout | Rundweg gegen die Fixtures; ein manueller Live-Durchlauf |

**Reihenfolge:** 0b jederzeit vor 5; 1a → 1b → 1c → 2 → 3 → 4 → 5 → 7 → 9; AP 8 läuft parallel. 1a muss vor 1b fertig sein, weil `activity_record` erst nach dem Füllen der Arrays gelöscht wird. Nach AP 3 gibt es bereits eigenständigen Nutzen: Der Agent kennt einzelne Läufe und ihre Workouts.

---

## 14. Risiken

| Risiko | W | A | Gegenmaßnahme |
|---|---|---|---|
| Die inoffizielle Workout-API ändert ihr Format | mittel | hoch | Mapper isoliert, Fixtures aus echtem Konto, Rohdaten-Archiv, `Unsupported`-Pfad |
| Rate-Limit oder Cloudflare-Sperre bei Massenoperationen | mittel | hoch | 1 s Drosselung, Stundenlimit, bei 429 Stopp und 15 min Sperre, nur Token-Login |
| Die Terminliste bei Garmin ist nur „eventually consistent“ (Hinweis aus Drittprojekten) | mittel | niedrig | ID aus der Antwort, kurzes Polling, Status `pending_id` |
| Teilerfolg zwischen Garmin und Google | mittel | mittel | Savepoints, Kompensation, Status `inconsistent`, idempotente Wiederaufnahme |
| GPS-Fehler verfälschen Best Efforts | mittel | mittel | Sprungfilter, nur GPS-Läufe, Validierung V2/V3 |
| Falsche HF-Bereiche durch falsche HFmax (Eingabefehler oder ungenaues 220 − Alter) | mittel | mittel | HF-Ziele nur in bpm (E9); Einstellungsseite fragt nach dem Messwert; Hinweis, wenn ein gemessener Wert darüber liegt (A.6); Vorschau nennt HFmax und Herkunft |
| Tool-Auswahl wird mit 26 Tools ungenauer | niedrig | mittel | Tool-Accuracy in der Eval beobachten; Schwelle für zweistufiges Laden (G.3) |
| Löschen von Workouts aus Garmin-Trainingsplänen (Coach) | niedrig | mittel | entfällt: Coach-Workouts stehen nicht in der Bibliothek (AP 0) |
| Speicherbedarf deutlich höher als dokumentiert | — | — | gelöst durch `activity_stream` (P2: 58× kleiner) |
| Datenverlust beim Entfernen von TimescaleDB | niedrig | hoch | `pg_dump` vorher, Arrays vor dem Löschen prüfen (V8), Zeilenzahlen vergleichen, Runbook (A.7) |
| HF-Ziele in der FIT mehrdeutig kodiert | hoch | mittel | HF-Ziele aus der Garmin-API; ohne passendes Workout „unklar“ statt geraten (B.6) |
| Uhr zeigt Sekundärziele oder lange Notizen nicht | mittel | niedrig | Freischaltung erst nach AP 0b; bis dahin Workouts mit Sekundärziel schreibgeschützt |
| Fehlende HFmax nach der Regeländerung | mittel | mittel | vor dem Umschalten eintragen (A.6); Hinweis in Lagebild und Tools statt stiller Lücke |

---

## 15. Offene Punkte

1. **Trainingsphilosophie** (Roadmap, offener Punkt 12): Wird im Coach-Modus (Stufe 3) über die Wissensbank gelöst; die Recherche läuft parallel zu Stufe 1.
2. **Schwimm-Workouts:** eigene Schrittlogik mit Bahnen, Schwimmstil und Pausen; nach V1.1.
3. ~~**Soll/Ist pro Intervall**~~ — in V1 (B.6, D12).
4. ~~**Sichtbarer Marker** `[kairos:…]`~~ — akzeptiert (D17).
5. ~~**Distanzliste der Bestleistungen**~~ — bleibt wie in E3 (D16).
6. **VM-Größe:** offen (D6). Mit `activity_stream` und FIT-Archiv reichen im Doku-Szenario 40 GB SSD.
7. ~~**Kairos-Plan neben Garmin Coach**~~ — erledigt: Der Nutzer hat den Garmin-Coach-Plan gelöscht (2026-10-13). `fbtAdaptiveWorkout`-Einträge werden beim Spiegel-Abgleich weiterhin ignoriert.
8. ~~**`hr_zone` oder `hr_range` als Default**~~ — entschieden (2026-10-13): bpm-Bereiche, siehe E9.
9. ~~**HFmax des Betreibers**~~ — bestätigt: 214 bpm. Regel und Einstellungsseite in A.6 (D10).
10. **Sekundärziele:** Freischaltung nach AP 0b (D14).
11. **Kraft-Workouts:** V1.1, AP 9 (D15).
12. **Schlaf dem Aufwachtag zuordnen** (`02` §2.7): nicht Teil dieser Spec.
13. **Commit-Adresse** `haenel@igmr.rwth-aachen.de` fehlt in der Entwicklerliste von `CLAUDE.md`; falls sie dem Nutzer gehört, dort und in HANDOVER ergänzen.
