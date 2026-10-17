# 08 — Roadmap, Risiken & offene Punkte

## 1. Leitgedanke der Reihenfolge

Zuerst die **Datenpipeline**, dann die **Kennzahlen**, dann der **Agent**. Ein Agent
auf lückenhaften Daten produziert überzeugend klingenden Unsinn und verbrennt genau
das Vertrauen, das das Projekt braucht.

Zweiter Grundsatz: **Der Betreiber ist Nutzer null.** Erst wenn eine Phase für einen
Nutzer über zwei Wochen stabil läuft, kommen weitere dazu.

### Stand 2026-10-08 (Details in `docs/HANDOVER.md`)

| Phase | Status | Offen |
|---|---|---|
| 0 — Fundament | ✅ `v0.0.1-phase0` | Deployment auf einer VM (VM nicht gebucht), Backup + Restore-Test, RLS-CI-Test |
| 1 — Garmin-Pipeline | ~95 % | Stichprobenvergleich mit Garmin Connect; `sync_failure` wird nicht geschrieben; Lösch-Abgleich fehlt |
| 2 — Kennzahlen & Dashboard | ✅ | Detailansichten Aktivität/Schlaf; `quality`-Filter in Aggregaten; Tagesgrenzen in UTC statt lokal |
| 3 — Kalender | ✅ (nur Google) | CalDAV, Watch-Channels/Push, inkrementeller Sync per `syncToken` |
| 4 — Agent | ✅ MVP + Harness v2 (Streaming, Gedächtnis mit Ablauf) | Eval live 15/16 (Fragen 7 und 10 brauchen Aktivitäts-Tools); Token-Telemetrie; zweistufiges Tool-Laden (erst ab > 30 Tools) |
| 5 — Planung | ✅ `plan_propose`/`plan_commit`/`plan_adjust`/`plan_progress` | Insight-Job + Web Push (Proaktivität) nicht gebaut |
| Frontend-Modernisierung + Designsystem „Ruhe“ | ✅ | — |
| **Aktivitäten & Workouts** | Spec abgestimmt, nicht begonnen | siehe Abschnitt unten |
| **Scheduler** (Stufe 2, D29–D34) | ✅ umgesetzt (Branch `feat/scheduler`, 2026-10-17), ADR-0007 | Real-Data-Lauf eine Woche, iPhone-Test; Insight-Job, Web Push, automatische Reaktionen (D30, D32) nicht Teil |
| 6 — Multi-User-Rollout | offen | — |

Die Checklisten der Phasen unten sind der ursprüngliche Plan; wo die Umsetzung
abweicht, ist das jeweils vermerkt.

---

## Phase 0 — Fundament (≈ 1 Woche)

**Ziel:** Ein leeres, aber korrektes System läuft auf der VM.

- [ ] Repo, Projektstruktur, Linting, mypy, pytest, CI
- [ ] Docker Compose lokal: Postgres+Timescale (pgvector nicht installiert), Redis, API
- [ ] Alembic mit Branch-Unterstützung für Plugins
- [ ] Kernschema: `app_user`, `connection`, `raw_payload`, `sync_state`, RLS
- [ ] RLS-CI-Test (keine Tabelle ohne Policy)
- [ ] Envelope-Verschlüsselung für Credentials
- [ ] Google OAuth-App einrichten (Cloud Console, Test-Nutzer eintragen, Client-ID/Secret)
- [ ] Caddy, Domain, TLS auf der VM
- [ ] Backup-Job + erster Restore-Test

**Abnahme:** Ein Nutzer kann sich anmelden. Backup und Restore funktionieren
nachweislich.

---

## Phase 1 — Garmin-Pipeline (≈ 2 Wochen)

**Ziel:** Vollständige, korrekte Gesundheitsdaten in der Datenbank.

- [ ] Connector-Contract + gemeinsame Infrastruktur (Retry, Rate-Limit, Watermark)
- [ ] `connectors.garmin`: Auth via `garminconnect` (ursprünglich `garth`, seit März 2026 unbrauchbar), MFA-Pfad, Reauth-UI
- [ ] Fetch aller Datentypen aus [04](04-integrationen.md#23-abzurufende-datentypen)
- [ ] Raw-Store mit `content_hash`-Deduplizierung
- [ ] Normalisierung → `wellness_sample`, `sleep_session`, `activity`, `daily_summary`
- [ ] FIT-Download + `garmin-fit-sdk` (statt `fitdecode`) → `activity_record`
- [ ] Backfill-Job, gedrosselt, unterbrechbar, mit Fortschrittsanzeige
- [ ] Hypertables (Kompressionspolicies entfallen: mit RLS nicht nutzbar)
- [ ] Plausibilitätsprüfung → `quality`-Flag

**Abnahme:** 12 Monate Historie des Betreibers importiert. Stichprobenvergleich mit
Garmin Connect stimmt für 10 zufällige Tage in allen Kennzahlen überein.

**Risiko:** Das ist die Phase mit der höchsten Unsicherheit. Ein Zeitpuffer von
50 % ist realistisch, nicht pessimistisch.

---

## Phase 2 — Kennzahlen & Dashboard (≈ 2 Wochen)

**Ziel:** Man sieht etwas, und die Zahlen stimmen.

- [ ] Metrics-Layer: TRIMP, CTL/ATL/TSB, HR-Zonen, ACWR, HRV-Baseline,
      Schlafschuld, Ruhepuls-Trend
- [ ] Derived-Tabellen als Recompute (gebaut: `wellness_daily_stats`, `hr_bucket_seconds_daily`, `metric_daily_value`; Continuous Aggregates sind mit RLS nicht nutzbar)
- [ ] `coverage` und `confidence` je Kennzahl
- [ ] Modul-Registry + generische Frontend-Komponenten
- [ ] Dashboard mit ~8 Startmodulen, pro Nutzer konfigurierbar
- [ ] Aktivitätsdetail- und Schlafdetailansicht

**Abnahme:** Die Kennzahlen sind gegen unabhängig berechnete Referenzwerte
(Tabellenkalkulation, bekannte Trainingssoftware) validiert. Abweichungen sind
erklärt, nicht wegdefiniert.

---

## Phase 3 — Kalender (≈ 1,5 Wochen)

- [ ] `connectors.google`: OAuth + Login (kombinierter Flow), Sync per `syncToken`, Watch-Channels, Fallback-Poll
- [ ] `connectors.caldav`: iCloud, ctag/etag-Poll
- [ ] Kanonisches `calendar_event`, Deduplizierung gespiegelter Termine
- [ ] Freizeitberechnung (freie Blöcke ≥ X min unter Berücksichtigung von
      Präferenzen und Puffern)
- [ ] Proposal-Mechanik + Bestätigungs-UI
- [ ] Schreiben in den `primary_write_calendar`

**Abnahme:** Ein Termin kann angelegt, geändert und gelöscht werden; die Änderung
erscheint korrekt in beiden Kalendern; keine Sync-Schleife.

---

## Phase 4 — Agent (≈ 2,5 Wochen)

- [ ] Orchestrator, Streaming, Konversationspersistenz
- [ ] Situation-Brief-Builder (adaptiv)
- [ ] Core-Tools (8): `search_tools`, `load_tools`, `query_health`, `analyze_records`, `query_calendar`, `recall`, `remember`, `render`
- [ ] `tool_registry` mit Embeddings, `search_tools`, `load_tools`
- [ ] Sticky Loading, Pack-Prewarming, Nutzungsstatistik
- [ ] Tool-Ausgabekontrakt inkl. Token-Cap
- [ ] Memory: Profil, semantisch, episodisch; `remember`/`recall`
- [ ] Konversations-Compaction
- [ ] Risikoklassen-Durchsetzung im Dispatcher
- [ ] Gesundheitsleitplanken im System-Prompt
- [ ] **Eval-Suite mit den 15 Referenzfragen + Zahlen-Assertions**
- [ ] Token-Telemetrie

**Abnahme (ursprünglich):** 13/13 Referenzfragen korrekt (Referenzfragen 13 und 15
verschoben nach Phase 5, siehe [Phase-4-MVP-Design](superpowers/specs/2026-09-12-phase-4-agent-mvp-design.md)).
Median-Input < 15k Tokens.

**Ist-Stand (2026-10-06):** Die Eval-Suite (`scripts/agent_eval_suite.py`) umfasst
**16 Fälle** — alle 15 Referenzfragen plus einen Mehrschritt-Fall (Vorschlag →
Bestätigen → Folgefrage). Live: **15/16** Tool-Accuracy. Frage 7 ist mangels
Aktivitäts-Tool nicht beantwortbar, Frage 10 nur eingeschränkt; beide deckt die Phase
„Aktivitäten & Workouts“ ab. Der Tool-Satz umfasst 12 Core-Tools ohne
`search_tools`/`load_tools`/`tool_registry`. Median-Input ist mangels
Token-Telemetrie nicht gemessen.

---

## Phase 5 — Planung & Proaktivität (≈ 2 Wochen)

- [ ] Planungsmodell: `plan`, `plan_block`, Ziele, Präferenzen
- [ ] Planungsalgorithmus: Constraint-Erfüllung über freie Blöcke, Erholungszustand,
      Mindestabstände zwischen harten Einheiten
- [ ] Agent-Tools: `plan_propose`, `plan_commit`, `plan_adjust`, `plan_progress`
- [ ] Insight-Job (regelbasiert) + Web Push — der generische Scheduler (ADR-0007) ist
      gebaut und kann den Agenten zu festen Zeiten fragen; Insight-Regeln und Push fehlen
- [ ] Benachrichtigungseinstellungen je Nutzer

**Abnahme:** Referenzfrage 13 und 15 werden vollständig und nachvollziehbar
beantwortet und in den Kalender geschrieben (korrigiert von "8 und 14" —
diese sind bereits mit dem Phase-4-MVP-Tool-Satz beantwortbar, siehe
[Phase-4-MVP-Design](superpowers/specs/2026-09-12-phase-4-agent-mvp-design.md)).

---

## Phase „Aktivitäten & Workouts“ (Spec vom 2026-10-07)

**Ziel:** Der Agent kennt einzelne Einheiten (Steckbrief, km-Splits, Bestleistungen)
und verwaltet strukturierte Workouts in Garmin; `plan_commit` überträgt Planblöcke
als Garmin-Workout plus Google-Termin. Grundlage:
[Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md), §13.

| AP | Inhalt | Abnahme |
|---|---|---|
| 0 Verifikation | Workout-Methoden in `garminconnect` 0.3.17, Referenz-Workouts und Workout-Zyklus als Fixtures, Datumskriterium `get_activities_by_date`, Typliste, offene Code-Fragen (kein Produktcode) | Fixtures eingecheckt; ID-Tabelle D.2 bestätigt oder korrigiert |
| 1 Datengrundlage | `activity` erweitern, Normalizer-Fixes, `distance_m`, zusätzliche FIT-Messages, Lösch-Abgleich, Reprocess, FIT-Pause | alle 136 Aktivitäten ohne Garmin-Request neu verarbeitet; alle 9 `typeKey`s korrekt zugeordnet; Lösch-Abgleich getestet |
| 2 Abgeleitete Daten | `activity_stats`, `activity_split`, `activity_best_effort` | Validierungsbericht V1–V6, Abweichungen erklärt |
| 3 Lese-Tools | 5 Tools, Formatierung, Obergrenzen | Eval 17–21 grün (Referenzfragen 7 und 10 erfüllt); Test für die Obergrenzen |
| 4 Harness | Vorschau-Snapshots, Zustandsmaschine, `tool_progress`, Schema-Budget, Token-Telemetrie | Doppelklick- und Absturz-Tests; Wiederaufnahme getestet |
| 5 Workouts | Client-Provider, Schreibdienst, Mapper, Spiegel, 7 Tools, Google-Kopplung | Mapper-Round-Trip gegen Fixtures; Eval 22–25 grün (Fake); ein manueller Live-Durchlauf |
| 6 Planung | Templates, `plan_commit`, `plan_adjust` | Eval 26 grün; Teilfehler-Test |
| 7 Aktivitäten bearbeiten | `activity_update`, `activity_delete` | Vorschau nennt betroffene Bestleistungen; Recompute nach dem Löschen getestet |
| 8 Doku-Abgleich | [Plan](superpowers/plans/2026-10-07-doku-abgleich.md) | alle Punkte erledigt |

**Reihenfolge:** 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7; AP 8 parallel. Nach AP 3 gibt es
bereits eigenständigen Nutzen.

---

## Phase 6 — Multi-User-Rollout & Erweiterbarkeit (≈ 1,5 Wochen)

- [ ] Onboarding-Flow für neue Nutzer
- [ ] Nutzerverwaltung + Löschung (Account + alle Daten kaskadierend)
- [ ] Plugin-Loader, Manifest-Validierung, Admin-Ansicht
- [ ] **Referenz-Plugin Wetter** (Nachweis: < 150 Zeilen)
- [ ] **Plugin Manuelle Einträge** (Stimmung, Alkohol, Schmerz)
- [ ] Nutzer 2–5 onboarden, gestaffelt
- [ ] Gmail-Integration (eingeschränkt)

**Abnahme:** Alle 5 Nutzer aktiv. Ein Plugin wurde von außen ergänzt, ohne den Kern
zu ändern.

---

## Zeitrahmen gesamt

**≈ 12–13 Wochen Netto-Entwicklungszeit.** Bei nebenberuflicher Umsetzung mit
~10 h/Woche entspricht das realistisch **6–9 Monaten**. Die Phasen sind so
geschnitten, dass nach Phase 2 bereits echter Nutzen existiert (Dashboard mit
korrekten Daten) — falls das Projekt dort ins Stocken gerät, ist es kein Totalverlust.

---

## 2. Risikoregister

| # | Risiko | W | A | Gegenmaßnahme |
|---|---|---|---|---|
| R1 | Garmin ändert die inoffizielle API | hoch | hoch | Rohdatenarchiv, Connector-Abstraktion, Aggregator als Rückfalloption. Eingetreten: `garth` (März 2026) und der mobile Login-clientId (Oktober 2026) — beide Male per Wechsel auf `garminconnect` bzw. den Widget-Flow behoben |
| R2 | Google-OAuth-Verifizierung blockiert dauerhaften Betrieb | niedrig | mittel | **Stand 2026-10:** App im Testing-Status mit eingetragenen Test-Nutzern; Login und Kalender-Sync laufen (Termine live importiert und angelegt). Eine Verifizierung ist bis 100 Test-Nutzer nicht nötig |
| R3 | Backfill dauert länger als geplant / trifft Rate-Limits | mittel | niedrig | Gedrosselt, unterbrechbar, Fortschrittsanzeige |
| R4 | Agent nennt falsche Zahlen | mittel | **hoch** | Rechenverbot, Zahlen-Assertions in der Eval-Suite |
| R5 | LLM-Kosten laufen aus dem Ruder | mittel | mittel | Kontextbudget, Caching, Modell-Routing, Tageslimit |
| R6 | Projekt versandet nach Phase 1 | **hoch** | hoch | Phasenschnitt liefert nach Phase 2 eigenständigen Nutzen |
| R7 | Nutzer 2–5 nutzen es nach 4 Wochen nicht mehr | mittel | mittel | Proaktivität sparsam dosieren, Onboarding begleiten |
| R8 | Prompt Injection über Mail | mittel | mittel | Gmail zuletzt und eng gescoped; Bestätigungspflicht |
| R9 | Datenmodell erweist sich als zu eng | niedrig | hoch | Narrow-Schema + Raw-Zone erlauben Reprocessing |
| R10 | Timescale-Migration auf ≈ 120 Mio. Zeilen wird zum Problem | niedrig | mittel | Staging mit anonymisierter Kopie ab Phase 3 |
| R11 | Inoffizielle Garmin-Workout-API (Schreiben) ändert ihr Format oder sperrt bei Massenoperationen | mittel | hoch | Mapper isoliert, Fixtures aus echtem Konto, Rohdaten-Archiv; ≥ 1 s Drosselung, Stundenlimit, nach 429 Stopp und 15 min Sperre, nur Token-Login ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) §14) |
| R12 | Speicherbedarf deutlich höher als ursprünglich dokumentiert | mittel | mittel | Gemessen und neu gerechnet ([02 §1.3](02-datenmodell-und-volumen.md#13-speicherbedarf)): ≈ 14–30 GB statt 7–9 GB; VM mit ≥ 80 GB SSD |

Das **realistischste Projektrisiko ist R6**, nicht die Technik.

---

## 3. Offene Punkte

Diese Fragen sind bewusst nicht entschieden worden und brauchen eine Antwort, bevor
gebaut wird. Erledigte Punkte sind durchgestrichen.

### Vor Phase 0

1. **VM-Anbieter, VM-Größe und Domain** — weiterhin offen. Nach der Speichermessung
   (2026-10-08) wird eine VM mit ≥ 80 GB SSD empfohlen (z. B. Hetzner CX32), siehe
   [07 §2.2](07-deployment-und-betrieb.md#22-empfehlung). Welche VM real gebucht wird,
   ist nicht entschieden.
2. ~~**Frontend: SvelteKit oder Next.js?**~~ — entschieden: SvelteKit (2026-08-10).
3. ~~**LLM-Anbieter und -Modelle**~~ — entschieden: anbieterunabhängig über litellm,
   Default `anthropic/claude-sonnet-5`, pro Nutzer wählbar; kein Modell-Routing.

### Vor Phase 1

4. **Garmin-Geräte bestätigt:** Forerunner 265S (2×), VivoActive 5 (2×) — alle
   Datentypen inkl. HRV, Body Battery, Training Readiness, SpO₂ verfügbar. ✅
5. **Apple Watch (1 Nutzer): kein Garmin-Connector möglich.** Dieser Nutzer braucht
   einen `connectors.apple_health`-Connector (Phase 6+). In Phase 1–5 hat er nur
   Kalender-Funktionalität. Entscheidung: akzeptiert, Nutzer informieren.
6. ~~**MFA auf Garmin-Konten**~~ — gelöst: `garminconnect` mit `return_on_mfa=True`
   und `resume_login()`; das Onboarding-UI zeigt bei Bedarf ein OTP-Eingabefeld.
7. ~~**Backfill-Tiefe**~~ — umgesetzt: Default 24 Monate, manuell ausgelöst, ≈ 3 h
   Wartezeit je Nutzer (kein nächtliches Fenster).

### Vor Phase 3

8. ~~**Google-OAuth-Status klären**~~ — Testing-Status mit Test-Nutzern genügt, siehe
   Risiko R2.
9. ~~**Welcher Kalender ist `primary_write_calendar` je Nutzer?**~~ — entschieden:
   Googles `primary`-Kalender, keine Auswahl-UI.
10. **Gmail wirklich nötig?** Der Nutzen ist der geringste, das Risiko das größte.
    Ein bewusstes Weglassen wäre eine legitime Entscheidung. — offen.

### Vor Phase 5

11. **Wie proaktiv soll das System sein?** Vorschlag: Default "eine Meldung pro Tag,
    nur bei Auffälligkeit", je Nutzer anpassbar bis "nie". — offen (Proaktivität
    ist nicht gebaut).
12. **Welche Trainingsphilosophie liegt der Beratung zugrunde?** Polarisiert,
    pyramidal, schwellenorientiert? Das ist eine inhaltliche, keine technische
    Entscheidung — und sie prägt jede Empfehlung, die der Agent gibt. — offen. Bis
    zur Entscheidung nutzen die geplanten Workouts je Planblock
    **Platzhalter-Templates** mit HF-Zonen-Zielen ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) E.2), die diese
    Entscheidung später ersetzt.

### Phase „Aktivitäten & Workouts“

13. Offene Punkte der Spec (§15): sichtbarer Marker `[kairos:…]` in
    Workout-Beschreibungen akzeptabel? Distanzliste der Bestleistungen (3.000 m
    behalten, 1 km / 1 Meile ergänzen?); Schwimm-Workouts (V1.1); Soll/Ist pro
    Intervall (V2).
