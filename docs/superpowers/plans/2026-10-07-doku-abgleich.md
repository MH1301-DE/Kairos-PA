# Doku-Abgleich (2026-10-07)

**Zweck.** Die Code- und DB-Prüfung vom 2026-10-07 (26 Fragen) hat Abweichungen zwischen Doku und Code gefunden. Dieser Plan listet die Korrekturen je Datei. Er ist zugleich Arbeitspaket 8 der Spec `specs/2026-10-07-aktivitaeten-und-workouts-design.md`.

**Regeln für die Umsetzung**

- Die Doku beschreibt den **Ist-Stand**.
- Nicht gebaute Zielbilder werden nicht gelöscht, sondern ausdrücklich als „Zielbild (nicht umgesetzt)“ markiert.
- Jeden Punkt vor dem Ändern erneut am Code prüfen. Die Belege stehen in Klammern und stammen aus dem Prüfbericht.
- Einzige Codeänderung in diesem Plan: das leere Verzeichnis `deploy/Caddyfile;C` löschen.
- Ein Commit pro Datei.

---

## 0. Messaufgabe vorab: Speicherbedarf

Die Speicherrechnung in `02` §1 setzt Aktivitäts-Records im *wide*-Format und Timescale-Kompression (Faktor 10–20) voraus. **Beides trifft nicht zu:** Die Records sind narrow, und Kompression ist mit RLS nicht nutzbar. Deshalb zuerst messen:

```sql
SELECT hypertable_size('activity_record'), approximate_row_count('activity_record');
SELECT hypertable_size('wellness_sample'), approximate_row_count('wellness_sample');
SELECT pg_total_relation_size('raw_payload'), count(*) FROM raw_payload;
```

`pg_total_relation_size` liefert für Hypertables nur die (leere) Elterntabelle, daher `hypertable_size`.

**Überschlag bis zur Messung** (Bytes pro Zeile geschätzt):

| Größe | Wert |
|---|---|
| `activity_record`-Zeilen je Aktivität | 2,15 Mio. Zeilen / 136 Aktivitäten ≈ 15.800 (7 Kanäle); mit `distance_m` ≈ 18.000 |
| Doku-Szenario: Aktivitäten | 5 Nutzer × 250 Aktivitäten/Jahr × 5 Jahre = 6.250 |
| Doku-Szenario: Zeilen | ≈ 110 Mio. |
| Annahme Bytes je Zeile | 150–200 B inkl. PK und Unique-Index |
| Ergebnis | **≈ 17–22 GB allein für `activity_record`** statt der dokumentierten „7–9 GB gesamt“ |

Der reale Nutzer liegt bei etwa 96 Aktivitäten im Jahr, also bei rund 40 % dieses Szenarios.

**Ergebnis:** Messwerte und Hochrechnung (Doku-Szenario und reale Rate) in `02` §1.3/§1.4 und `07` §2.2 eintragen.

---

## 1. `00-vision-und-scope.md`

- [ ] §6 Garmin-Zugang: `garth` → `garminconnect ≥ 0.3.17`, Token-Login, Login nur über den Widget-Flow (garth ist weder installiert noch importiert); Verweis auf ADR-0004
- [ ] §6 Frontend: „Entscheidung steht aus“ → SvelteKit (entschieden am 2026-08-10)
- [ ] §6 Sprache Backend: „Python 3.12“ → „Python ≥ 3.12 (CI 3.12)“
- [ ] §7: Frontend und LLM (litellm, deployment-weiter `LLM_API_KEY`) als erledigt markieren; Nummerierung korrigieren (Punkt 4 fehlt)
- [ ] §2.1, Ziel 3: Trainingsblöcke landen als Kalendertermine **und** als Garmin-Workouts (Verweis auf die neue Spec)
- [ ] §5: Hinweis, dass die Referenzfragen 7 und 10 über die Aktivitäts-Tools beantwortet werden und die Eval-Suite die Fälle 1–16 plus 17–26 umfasst

## 2. `01-architektur.md`

- [ ] §2 Systemkontext: „LLM-API (Anthropic)“ → „LLM-API (über litellm, Anbieter wählbar)“; Apple CalDAV als Zielbild markieren
- [ ] §3 Containerdiagramm: Worker/Scheduler (arq) und Object Store als Zielbild markieren. Ist: FastAPI-BackgroundTasks, kein arq in den Dependencies, kein Object Store. „React/Svelte“ → SvelteKit
- [ ] §4.1: Die Wiederholung über `sync_failure` ist nicht umgesetzt; die Tabelle existiert, wird aber nie geschrieben (`SyncService` ohne Repository, `sync.py:221`) → als offen markieren. Statt „Backfill mit niedrigerer Priorität“ gilt ein Lock je (Nutzer, Kind) plus 300 s Cooldown
- [ ] §4.2: Die Raw-Zone enthält keine FIT-Dateien, nur dekodiertes gzip-JSON (`record`, `session`, `lap`; laut neuer Spec zusätzlich `length`, `event`, `workout`, `workout_step`)
- [ ] §4.3: TRIMP ist kanonisch Edwards, Banister nur eine Variante. Derived-Tabellen sind `metric_daily_value`, `wellness_daily_stats`, `hr_bucket_seconds_daily`
- [ ] §4.4: „Memory Retrieval (pgvector)“ → Ist: `recall` per Substring über `agent_memory`, keine Embeddings. Tool Router, `search_tools`, `load_tools` → Zielbild
- [ ] §4.5: Die Modul-Registry steckt im Frontend (`web/src/lib/modules.ts`) plus Tabelle `user_dashboard_tile`; `module_registry`/`user_dashboard` existieren nicht
- [ ] §5.1 „Nächtlicher Sync 03:15 (garth)“ → Ist: kein Scheduler. Syncs manuell über UI/API; Recompute nach dem Backfill und per `POST /api/metrics/recompute`
- [ ] §5.2: Google-Watch-Channels/Push nicht gebaut, nur `syncToken`-Abruf (manuell ausgelöst); CalDAV nicht gebaut
- [ ] §5.3: `commit_proposal(proposal_id, idempotency_key)` → Bestätigung über `tool_call_id` (Harness v2), künftig über `proposal_snapshot` (neue Spec, G.1)
- [ ] §6 Tabelle:
  - Queue „Redis + arq“ → nicht eingesetzt
  - DB „Kompression; Continuous Aggregates“ → wegen RLS nicht nutzbar (timescale#6827, #5787)
  - Frontend → SvelteKit
  - Zeile „Agent-Tools“: Tools sind Python-Funktionen in `agent/tools.py`, nicht hinter dem Connector-Protocol
- [ ] §8: Zeile „MCP-Server abgestürzt“ entfernen (es gibt keine MCP-Server)

## 3. `02-datenmodell-und-volumen.md`

- [ ] §1.3/§1.4: neu rechnen mit den Messwerten aus §0; das Fazit „unter 10 GB“ entsprechend anpassen
- [ ] §2.1 Übersicht auf tatsächliche Tabellen umstellen:
  - **Existieren nicht:** `proposal`, `tool_registry`, `metric_daily`, `memory (vector)`.
  - **Prüfen:** `load_state`, `hr_zone_daily`, `calendar_account`, `oauth_token`, `audit_log`.
  - **Ergänzen (bestehend):** `goal`, `user_dashboard_tile`, `plan`, `plan_block`, `conversation`, `conversation_message`, `agent_memory`, `metric_daily_value`, `wellness_daily_stats`, `hr_bucket_seconds_daily`.
  - **Ergänzen (neu laut Spec):** `activity_stats`, `activity_split`, `activity_best_effort`, `garmin_workout`, `garmin_workout_schedule`, `proposal_snapshot`.
- [ ] §2.2: Aktivitäts-Records sind narrow (`metric`, `value`; `models.py:320-346`); Begründung entsprechend anpassen
- [ ] §2.3:
  - `wellness_sample`: `quality` ist `varchar(16)` mit Default `ok`; „komprimiert ab 7 Tagen“ streichen.
  - `activity_record`: „Kompression ab 1 Tag“ streichen.
  - `activity`: die neuen Spalten ergänzen (Spec A.1).
  - Den Absatz zu `proposal` durch einen Verweis auf Harness v2 bzw. `proposal_snapshot` ersetzen.
- [ ] §2.4: `metric_daily` → die drei realen Tabellen (plain, gepflegt von `metrics_recompute.py`); Aktivitäts-Ableitungen ergänzen
- [ ] §2.5: kein Object Store; `activity.fit_object_key` ist ungenutzt (0 von 136 befüllt)
- [ ] §2.7: „`local_timezone` je Aktivität“ → `start_local` + `utc_offset_min` (Garmin liefert `timeZoneId` nur als Zahl)
- [ ] §2.8: Die Tagesaggregate filtern `quality` noch nicht (offen); die neuen Aktivitäts-Ableitungen filtern
- [ ] §2.9: Zeile „FIT-Dateien“ → entfällt (es werden keine gespeichert)

## 4. `03-agent-design.md`

- [ ] §2 Budget:
  - Core-Tools „12, ~2.400 (geschätzt)“ → gemessen 1.461 Tokens (o200k, 5.346 Zeichen).
  - Nach der neuen Spec: 26 Tools, ≈ 4.000–4.500 Tokens.
  - Token-Telemetrie fehlt bisher (Spec G.4).
- [ ] §4.2: Tabelle um die 14 neuen Tools erweitern; geänderte `plan_*`-Tools und `render` aktualisieren (Spec §11)
- [ ] §4.3: Schwelle für das zweistufige Laden ergänzen (> 30 Tools oder > 6.000 Schema-Tokens)
- [ ] §4.4: Spaltenformat für Tabellen, formatierte Werte, `meta.next`/`meta.quality`; `meta.truncated` wird gesetzt; Obergrenzen je Tool
- [ ] §5: semantisches/episodisches Gedächtnis per Embedding → Ist:
  - `agent_memory` mit `expires_at`, `recall` per Substring;
  - Extraktion beim Kompaktieren der Historie (Harness v2);
  - kein nächtlicher Job, kein Status `proposed`.
- [ ] §6.1: Bestätigung mit Vorschau-Snapshot und Zustandsmaschine (Spec G.1); Massenoperationen (`workout_delete`, `workout_unschedule`, `activity_delete`)
- [ ] §7 Proaktivität: als Zielbild markieren (kein Insight-Job, kein Web Push)
- [ ] §8: Eval-Stand 16 Fälle (15 + Proposal-Fall), live 15/16; Fälle 17–26 aus der Spec

## 5. `04-integrationen.md`

- [ ] §2.1: Auth über `garth` → `garminconnect`:
  - Token in `connection.credentials_enc`, Login nur über den Widget-Flow, kein Passwort gespeichert;
  - bei Token-Ablehnung `reauth_required`.
- [ ] §2.2: Ist-Drosselung eintragen:
  - 1,5 s zwischen Tagesfenstern (`config.py:21`);
  - FIT-Downloads ohne Pause (Fix: Spec A.5);
  - 300 s Cooldown pro Backfill-Trigger.

  Schreib-Limits aus Spec D.7 ergänzen.
- [ ] §2.3:
  - Tabelle auf `_ALL_KINDS` (`sync.py:53-57`) umstellen, mit `garminconnect`-Methoden statt garth-Endpunkten.
  - `activity_details` und `body_composition` werden nicht abgerufen.
  - `fit_file` heißt `activity_fit` und läuft ohne Object Store.
  - Die Spalte `metric_def.available` existiert nicht.
- [ ] §2.4: Plausibilitätsgrenzen prüfen. Für HF (< 25 / > 230) sind sie belegt; für SpO₂, Schlaf, Stress und HRV am Normalizer verifizieren. `quality` ist Text, nicht `2`
- [ ] §2.5 Backfill: „nur nachts 02:00–06:00“ und „rückwärts laufend“ am Code prüfen und korrigieren
- [ ] neuer §2.6 Workouts (Schreiben): Methoden, Spiegel, Limits (Verweis auf Spec Teil D)
- [ ] §3.2: Watch-Channels/Push nicht gebaut; Abruf nur manuell. Prüfen, ob die Calendar API im Cloud-Projekt inzwischen aktiviert ist (HANDOVER, Punkt 4)
- [ ] §4 CalDAV: als Zielbild markieren
- [ ] §5.1: litellm, deployment-weiter Key, Default-Modell `anthropic/claude-sonnet-5`. §5.3 Prompt-Caching: Ist-Stand prüfen
- [ ] §6 Diagramm: Scheduler als Zielbild markieren

## 6. `06-sicherheit-und-datenschutz.md`

- [ ] §4.3 Rate Limiting:
  - Das `deploy/Caddyfile` (Commit `82326df`) enthält kein Rate-Limit. Standard-Caddy hat dafür keine Direktive, nötig wäre ein Plugin → als Zielbild markieren.
  - „JWT-gebunden“ → session-gebunden.
  - Die vorhandenen App-Limits nennen: 429-Cooldowns der Sync-Trigger, neu die Garmin-Schreiblimits.
- [ ] §7 Audit: Existenz und Befüllung von `audit_log` prüfen und den Ist-Stand eintragen
- [ ] §9 Checkliste: Punkt „Rate-Limit“ ergänzen bzw. als offen markieren
- [ ] Repo: leeres Verzeichnis `deploy/Caddyfile;C` löschen

## 7. `07-deployment-und-betrieb.md`

- [ ] §1: Status je Dienst angeben (gebaut / Zielbild): MinIO, arq Worker/Scheduler, Uptime Kuma, Backup-Container
- [ ] §2.2: SSD-Bedarf nach §0 neu rechnen; CX22 (40 GB) ist im Doku-Szenario voraussichtlich zu knapp → Empfehlung aktualisieren. Die real geplante oder gebuchte VM eintragen (offen, Frage 26)
- [ ] §6.2: Modellname und Preise auf das Default-Modell aktualisieren (Preise prüfen)

## 8. `08-roadmap.md`

- [ ] Phasenstatus aus HANDOVER übernehmen: 0 ✅, 1 ~95 %, 2–5 ✅ mit den dort genannten offenen Punkten
- [ ] Phase 4, Abnahme „13/13“ → 16 Fälle, live 15/16
- [ ] neue Phase „Aktivitäten & Workouts“ mit AP 0–8 und deren Abnahmen (Spec §13)
- [ ] Offene Punkte:
  - doppelte Nummer 7 korrigieren;
  - Punkt 11 (Trainingsphilosophie) mit Verweis auf die Platzhalter-Templates (Spec E.2);
  - VM-Entscheidung (Frage 26).
- [ ] Risikoregister: neues Risiko „Inoffizielle Garmin-Workout-API“; R2 (Google-OAuth) mit aktuellem Stand

## 9. `HANDOVER.md`

- [ ] Tech Stack: Python „3.14.6“ → „≥ 3.12; CI 3.12; lokal 3.13 (Windows) bzw. 3.14.6 (Mac)“
- [ ] „Produktions-Deployment … Caddyfile fehlt“ → Caddyfile vorhanden (`82326df`), ohne Rate-Limit
- [ ] Aktivitäts-Befunde mit Verweis auf die neue Spec aufnehmen: `activity_type` immer NULL, `distance` fehlt, kein Lösch-Abgleich, `sync_failure` ungenutzt, Upsert ohne `start_at`/`end_at`
- [ ] Bulk-Insert: für `activity_record` erledigt (`5b57d89`); `wellness_sample` wird weiterhin zeilenweise geschrieben

## 10. `adr/ADR-0004-garmin-zugang.md`

- [ ] Inhalt auf `garminconnect` + Widget-Flow + Token-only aktualisieren. Die HANDOVER-Tabelle nennt bereits „garminconnect statt garth“; die Datei selbst prüfen. Ergänzen: inoffizielle Schreibzugriffe (Workouts) und ihre Risiken

---

**Abnahme:** Alle Punkte sind abgehakt, keine Aussage in `00`–`08` widerspricht dem Code, und Zielbilder sind als solche erkennbar.
