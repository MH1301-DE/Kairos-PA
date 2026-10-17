# Abnahme Stufe 1 — AP 1a, 1b, 1c (2026-10-14/15)

Spec: `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` §13. Datenbasis: Entwicklungs-DB, Nutzer Max (139 Aktivitäten, 2024-09-12 bis 2026-10-13). Branch `stufe1-datenbasis`.

## 1a Speicher und FIT-Archiv

| Kriterium | Ergebnis |
|---|---|
| alle 139 Aktivitäten in `activity_stream` | 139/139; Quelle `fit_zip` 139, JSON-Rückfall 0; Fehlschläge 0 |
| V8 erfüllt | `scripts/verify_activity_streams.py` → `RESULT: OK`, 0 Abweichungen |
| ≈ 60 KB je Aktivität | 61,7 KB |

Nachabruf: 3 Probe-Aktivitäten, dann 136 mit einem Token-Login, 407,8 s, 2 s Pause je Download, kein 429.

## 1b TimescaleDB entfernen

| Kriterium | Ergebnis |
|---|---|
| Zeilenzahlen vorher = nachher | alle 27 verbleibenden Tabellen identisch (z. B. `wellness_sample` 265.063, `raw_payload` 7.688); zusätzlich je `metric_id` Anzahl, Summe und MD5 über alle Zeilen identisch — im Probelauf, nach der Migration und nach dem Restore in `postgres:16` |
| RLS-Test grün | `tests/test_rls.py` lokal gegen `postgres:16` grün; der GitHub-CI-Lauf steht aus (Branch nicht gepusht) |
| Testsuite gegen `postgres:16` grün | 479 passed, 0 skipped (Stand Task 8) |

Runbook und Rückweg: `docs/HANDOVER.md`, Abschnitt „Runbook A.7“.

## 1c Aktivitäts-Spalten, Abgleich, Tage, HFmax

| Kriterium | Ergebnis |
|---|---|
| alle 9 `typeKey`s zugeordnet | `tests/test_sport_profile.py`; auf der Dev-DB nach Reprocess: running 103 (running 102 + treadmill_running 1), hiking 11, swimming 7 (lap_swimming), cycling 7, generic 11 (strength_training 6, hiit 2, breathwork 2, resort_skiing 1); `start_local` 139/139 |
| Lösch-Abgleich getestet | `tests/test_activity_reconcile_integration.py` (fehlende Aktivität markiert, Tage außerhalb unberührt, Fehler-Payload und fehlerhafte Einträge markieren nichts, 00:30-Lauf über das lokale Datum, gelöschte Aktivität fehlt in HF-Buckets) |
| Testfall 00:30 Ortszeit grün | `tests/test_metrics_local_days_integration.py` |
| TRIMP mit HFmax 214 unverändert außer an Tagen mit Aktivitäten 0–2 Uhr Ortszeit | siehe unten — erfüllt |

HFmax 214 wurde am 2026-10-15 über `PUT /api/settings/profile` für Max eingetragen (Wert laut Max' Vorgabe; Max hatte die Eingabe auf der Seite angekündigt, dann aber freigegeben, ohne Rückfrage weiterzuarbeiten).

### Recompute der Historie (2024-09-12 bis 2026-10-15)

7-Tage-Probe (2026-10-07 bis 13 plus 2025-05-28/29, zurückgerollt): HF-Buckets und TRIMP der letzten 7 Tage identisch.

Gesamte Historie, vorher/nachher:

- **HF-Buckets:** 124 Tage, 347.493 s vorher = nachher. Abweichend nur 2025-05-28 (1.806 → 1.204 s) und 2025-05-29 (6.398 → 7.000 s): Aktivität 226 startet 2025-05-28 23:05 UTC = 2025-05-29 02:05 Ortszeit (UTC+3) und zählt jetzt ganz zum lokalen Starttag.
- **TRIMP Edwards:** unverändert außer 2025-05-28 (64,70 → 42,17) und 2025-05-29 (269,12 → 291,65); Summe 333,82 bleibt. Neu sind nur die Zeilen für 2026-10-14/15 (0, weil der Recompute bis heute läuft). Die verwendete HFmax 214 ist gleich dem bisher gemessenen Maximum 214, deshalb ändert die neue HFmax-Regel keine Werte.
- **Wellness-Tagesstatistik:** Samples je Metrik identisch (z. B. HF 106.828, Stress 54.326). Tage 806 → 799: 2026-04-30 enthielt nur Samples ab 22:00 UTC (= 1. Mai Ortszeit) und entfällt als eigener Tag; ebenso 4 HRV-Tage. Mittelwerte verschieben sich, weil die Samples von 22–24 Uhr UTC zum Folgetag wandern (mittlere Abweichung HF 0,8 bpm, HRV 3,5 ms).
- **Folgewerte:** `sleep_debt` an 396 Tagen geändert (Schlaf zählt zum lokalen Tag des Einschlafens; gleitender Wert), `hrv_baseline` 6, `resting_hr_trend` 3, `hr_zone_distribution/karvonen` 3 Tage (Ruhepuls aus verschobener Wellness-Statistik). CTL/ATL/ACWR, Monotonie und Banister-TRIMP: nur die neuen Zeilen 2026-10-14/15.
