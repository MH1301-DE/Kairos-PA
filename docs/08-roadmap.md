# 08 — Roadmap, Risiken & offene Punkte

## 1. Leitgedanke der Reihenfolge

Zuerst die **Datenpipeline**, dann die **Kennzahlen**, dann der **Agent**. Ein Agent
auf lückenhaften Daten produziert überzeugend klingenden Unsinn und verbrennt genau
das Vertrauen, das das Projekt braucht.

Zweiter Grundsatz: **Der Betreiber ist Nutzer null.** Erst wenn eine Phase für einen
Nutzer über zwei Wochen stabil läuft, kommen weitere dazu.

---

## Phase 0 — Fundament (≈ 1 Woche)

**Ziel:** Ein leeres, aber korrektes System läuft auf der VM.

- [ ] Repo, Projektstruktur, Linting, mypy, pytest, CI
- [ ] Docker Compose lokal: Postgres+Timescale+pgvector, Redis, API
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
- [ ] `connectors.garmin`: Auth via `garth`, MFA-Pfad, Reauth-UI
- [ ] Fetch aller Datentypen aus [04](04-integrationen.md#23-abzurufende-datentypen)
- [ ] Raw-Store mit `content_hash`-Deduplizierung
- [ ] Normalisierung → `wellness_sample`, `sleep_session`, `activity`, `daily_summary`
- [ ] FIT-Download + `fitdecode` → `activity_record`
- [ ] Backfill-Job, gedrosselt, unterbrechbar, mit Fortschrittsanzeige
- [ ] Hypertables, Kompressionspolicies
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
- [ ] `metric_daily`, `hr_zone_daily` als Continuous Aggregates / Recompute-Jobs
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

**Abnahme:** 15/15 Referenzfragen korrekt. Median-Input < 15k Tokens bei > 40
registrierten Tools.

---

## Phase 5 — Planung & Proaktivität (≈ 2 Wochen)

- [ ] Planungsmodell: `plan`, `plan_block`, Ziele, Präferenzen
- [ ] Planungsalgorithmus: Constraint-Erfüllung über freie Blöcke, Erholungszustand,
      Mindestabstände zwischen harten Einheiten
- [ ] Agent-Tools: `plan.propose`, `plan.commit`, `plan.adjust`
- [ ] Insight-Job (regelbasiert) + Web Push
- [ ] Benachrichtigungseinstellungen je Nutzer

**Abnahme:** Referenzfrage 8 und 14 werden vollständig und nachvollziehbar
beantwortet und in den Kalender geschrieben.

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
| R1 | Garmin ändert die inoffizielle API | hoch | hoch | Rohdatenarchiv, Connector-Abstraktion, Aggregator als Rückfalloption |
| R2 | Google-OAuth-Verifizierung blockiert dauerhaften Betrieb | mittel | mittel | Vorab klären; Apple/CalDAV als Primärkalender |
| R3 | Backfill dauert länger als geplant / trifft Rate-Limits | mittel | niedrig | Gedrosselt, unterbrechbar, Fortschrittsanzeige |
| R4 | Agent nennt falsche Zahlen | mittel | **hoch** | Rechenverbot, Zahlen-Assertions in der Eval-Suite |
| R5 | LLM-Kosten laufen aus dem Ruder | mittel | mittel | Kontextbudget, Caching, Modell-Routing, Tageslimit |
| R6 | Projekt versandet nach Phase 1 | **hoch** | hoch | Phasenschnitt liefert nach Phase 2 eigenständigen Nutzen |
| R7 | Nutzer 2–5 nutzen es nach 4 Wochen nicht mehr | mittel | mittel | Proaktivität sparsam dosieren, Onboarding begleiten |
| R8 | Prompt Injection über Mail | mittel | mittel | Gmail zuletzt und eng gescoped; Bestätigungspflicht |
| R9 | Datenmodell erweist sich als zu eng | niedrig | hoch | Narrow-Schema + Raw-Zone erlauben Reprocessing |
| R10 | Timescale-Migration auf 48 Mio. Zeilen wird zum Problem | niedrig | mittel | Staging mit anonymisierter Kopie ab Phase 3 |

Das **realistischste Projektrisiko ist R6**, nicht die Technik.

---

## 3. Offene Punkte

Diese Fragen sind bewusst nicht entschieden worden und brauchen eine Antwort, bevor
gebaut wird:

### Vor Phase 0

1. **VM-Anbieter und Domain** — bestätigt? Läuft bereits etwas Vergleichbares, das
   mitgenutzt werden kann?
2. **Frontend: SvelteKit oder Next.js?** SvelteKit ist schlanker und für ein
   datendichtes Dashboard angenehmer; Next.js hat das größere Ökosystem. Reine
   Präferenzfrage.
3. **LLM-Anbieter und -Modelle** — welches Modell für die Analyse, welches kleine
   für einfache Abfragen?

### Vor Phase 1

4. **Garmin-Gerätemodelle der 5 Nutzer.** Davon hängt ab, welche Datentypen
   überhaupt existieren (HRV-Status, Body Battery und Training Readiness gibt es
   nicht auf jedem Gerät). Beeinflusst die Volumenrechnung und die verfügbaren Module.
5. **MFA auf den Garmin-Konten aktiv?** Beeinflusst den Auth-Flow spürbar.
6. **Wie weit zurück soll der Backfill reichen?** 12 Monate ist die Annahme.
   Mehr ist speichertechnisch problemlos, kostet aber Backfill-Zeit.

### Vor Phase 3

7. **Google-OAuth-Status klären** (siehe [04, Abschnitt 3.1](04-integrationen.md#31-auth)).
   Das ist der einzige Punkt, der eine geplante Integration ganz kippen könnte.
8. **Welcher Kalender ist `primary_write_calendar` je Nutzer?**
9. **Gmail wirklich nötig?** Der Nutzen ist der geringste, das Risiko das größte.
   Ein bewusstes Weglassen wäre eine legitime Entscheidung.

### Vor Phase 5

10. **Wie proaktiv soll das System sein?** Vorschlag: Default "eine Meldung pro Tag,
    nur bei Auffälligkeit", je Nutzer anpassbar bis "nie".
11. **Welche Trainingsphilosophie liegt der Beratung zugrunde?** Polarisiert,
    pyramidal, schwellenorientiert? Das ist eine inhaltliche, keine technische
    Entscheidung — und sie prägt jede Empfehlung, die der Agent gibt.
