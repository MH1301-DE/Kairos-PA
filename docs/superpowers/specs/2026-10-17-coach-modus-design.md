# Coach-Modus: Trainingsplanung aus der Wissensbank (Design-Spec, Stufe 3)

| | |
|---|---|
| **Datum** | 2026-10-17 |
| **Status** | Entscheidungen zu §15 vom 2026-10-17 eingearbeitet (§1.3); Frage 4 offen. Umsetzung ab AP 1 auf Branch `feat/coach` (Basis `main` mit Stufe 1). |
| **Baut auf** | [Entscheidungsprotokoll](2026-10-13-brainstorming-entscheidungen.md) D19–D28 · [Recherche Trainingsmethodik](../research/2026-10-13-trainingsmethodik-wissensbank.md) (PR #2) · Stufe 1 [`2026-10-07-aktivitaeten-und-workouts-design.md`](2026-10-07-aktivitaeten-und-workouts-design.md) §8 „Vorgaben für die Spec von Stufe 3“ (PR #1) · Phase 5 Planning (`2026-09-12-phase-5-planning-design.md`) · Agent-Harness v2 (`2026-10-05-agent-harness-v2-design.md`) |
| **Berührt** | Scheduler-Spec `2026-10-15-scheduler-design.md` (PR #4, Stufe 2) für die Wochenbesprechung als geplanter Job |
| **Ersetzt** | heuristischen Plan-Algorithmus `src/kairos/planning/algorithm.py` und die vier `plan_*`-Tools in ihrer Phase-5-Fassung |
| **Nicht im Scope** | siehe §14 |

> **Abhängigkeiten auf einen Blick.** Diese Spec setzt auf drei Dokumente, die am
> 2026-10-17 noch nicht auf `main` sind: Entscheidungsprotokoll und Stufe-1-Spec (PR #1),
> Recherche (PR #2), Scheduler-Spec (PR #4). Im Code setzt sie Stufe 1 AP 1a–3
> (`activity_stats`, `activity_step_result`, Lese-Tools), AP 4 (Harness) und AP 5
> (Workout-Tools) voraus. Welche Arbeitspakete vorher starten können, steht in §12.

---

## 0. Zusammenfassung

Kairos erzeugt Trainingspläne selbst (D19). Der Coach-Modus besteht aus einem eigenen
Bereich **„Coach“** im Frontend und dem Chat (D20):

1. **Wissensbank im Repo** (`knowledge/training/`, D24): je Regel eine Markdown-Datei mit
   maschinenlesbarem Regelteil (YAML, festes Vokabular) und Erklärteil für Agent und
   Nutzer. Ein **Plantyp** (D25) ist eine Zusammenstellung von Regeln plus Parametern.
   Der erste Plantyp `ausdauer-laufen-pyramidal` entsteht aus Max' Regeln (D27) und der
   Recherche.
2. **Bezugswerte** (D26) je Nutzer mit Historie: VDOT, LTHR, FTP, CSS, HFmax. Kairos
   berechnet sie aus Tests und Wettkämpfen und leitet daraus Pace- und HF-Bereiche ab.
3. **Deterministischer Plan-Generator** im Code: Phasen bis zum Ziel grob, Einheiten
   rollierend für 1–2 Wochen (D21). Jede Einheit verweist auf die Regeln, die sie erzeugt
   haben (`id@version`). Das LLM erfindet keine Zahlen; es wählt Parameter, erklärt und
   schlägt Änderungen vor, die ein **Regelprüfer** im Code gegen den Plantyp prüft.
4. **Geführter Einstieg** auf der Seite „Coach“: Ziel, Zeitraum, verfügbare Tage,
   Sportarten, Testwert. Danach Planvorschlag, Bestätigung und Übertragung nach Garmin.
5. **Garmin-Kopplung** (D28, Vorgaben aus Stufe 1 §8): ein Garmin-Workout pro Planblock,
   `plan_commit` überträgt Workout, Garmin-Termin und Kalendertermin idempotent.
6. **Wochenbesprechung im Chat** (D20, D21): Soll/Ist der Woche aus `activity_step_result`,
   Leitplanken-Status, Erholung; danach plant Kairos die nächste Woche im Detail. Auslöser
   ist ein Button, später zusätzlich ein Scheduler-Job (Stufe 2).

Der Tool-Satz wächst von 26 (nach Stufe 1) auf **28**: Die vier `plan_*`-Tools werden
neu gebaut, `knowledge_lookup` und `reference_value_set` kommen hinzu (§8).

---

## 1. Entscheidungen

### 1.1 Mit dem Nutzer abgestimmt (2026-10-13, Entscheidungsprotokoll §2.4)

| # | Entscheidung | Umsetzung in dieser Spec |
|---|---|---|
| D19 | Kairos erzeugt die Trainingspläne selbst | Plan-Generator §6; Phase-5-Algorithmus entfällt |
| D20 | Eigener Bereich plus Chat: geführter Einstieg im Bereich, Feinplanung und Wochenbesprechung im Chat | Seite „Coach“ §9, Chat-Ablauf §7 |
| D21 | Phasen bis zum Ziel grob, Details rollierend 1–2 Wochen, Anpassung in der Wochenbesprechung | `plan_phase` + `plan_block` §5; Rollierung §6.4 |
| D22 | Jeder Nutzer plant für sich | kein Rollenmodell; RLS wie bei allen Tenant-Tabellen |
| D23 | Für alle Nutzer; Hauptsport Laufen, Rad oder Triathlon; Ergänzung Kraft, Schwimmen, Yoga | Datenmodell sportartneutral; Plantypen nacheinander (§3.4) |
| D24 | Wissensbank als Dateien im Repo, Regelteil + Erklärteil, Planblöcke verweisen auf `id@version` | §3 |
| D25 | Plantyp als Einstellung je Nutzer | `coach_profile.plan_type` §5.1 |
| D26 | Bezugswerte gehören zum Plantyp | Plantyp deklariert benötigte Bezugswerte §3.3, §4 |
| D27 | Max' Regeln werden der erste Plantyp; sein laufender Plan wird übernommen | Plantyp 1 §3.4; Übernahme §10 (mit offener Frage §15) |
| D28 | `plan_commit`/`plan_adjust` mit Garmin-Workouts kommen in Stufe 3 | §8.3, §8.4 |

Aus Stufe 1 §8 übernommene Vorgaben: ein Garmin-Workout pro Planblock (E7), Verknüpfung über
`garmin_workout_schedule.plan_block_id`, idempotenter Commit mit Teilerfolgen nach D.4/D.6,
`plan_adjust` per `workout_update`, kein Agent-Tool „Plan verwerfen“, Filter `plan_id` in
`workout_unschedule`/`workout_delete`, B.6 als Datengrundlage der Wochenbesprechung.

### 1.2 In dieser Spec getroffen (bitte prüfen)

| # | Entscheidung | Begründung |
|---|---|---|
| S1 | **Bestehende Tabellen `plan`/`plan_block` erweitern** statt neuer Tabellen | `garmin_workout_schedule.plan_block_id` (Stufe 1 D.3) zeigt schon auf `plan_block`; ein zweites Planmodell hieße zwei Wahrheiten. Die Phase-5-Daten sind Entwürfe ohne Garmin-Bezug. |
| S2 | **Regelprüfer im Code entscheidet**, nicht das LLM | Zahlen (Pace, Umfang, Anteile) sind reproduzierbar und testbar; das LLM begründet mit dem Erklärteil. |
| S3 | **Leitplanken** (Regelart `leitplanke`) blockieren den Generator; im Chat kann der Nutzer sie nur mit ausdrücklicher Bestätigung und Begründung überschreiben, die am Block gespeichert wird | „Kein Ersatz für Sportwissenschaft“ (`00-vision-und-scope.md` §3): Kairos warnt, entmündigt aber nicht. Siehe offene Frage 6. |
| S4 | **Drei-Zonen-Modell** für alle Verteilungen, feinere Zonen nur in Workouts | Recherche §2.1; sportartübergreifend vergleichbar |
| S5 | Workout-Ziele für HF **immer in bpm** (`hr_range`), für Laufen Pace aus VDOT | Stufe 1 E9; Recherche §6.2 |
| S6 | Ein **aktiver Plan** je Nutzer | einfacher Lagebild- und Tool-Kontext; mehrere Ziele bilden Phasen eines Plans |
| S7 | Wissensbank wird **beim Start geladen und validiert**; ungültige Einträge verhindern den Start nicht, deaktivieren aber den betroffenen Plantyp | ein Tippfehler in einer YAML-Datei soll Chat und Sync nicht lahmlegen; CI fängt ihn vorher |
| S8 | Wochenbesprechung als **eigene Konversation je Woche**, angelegt per Button oder Scheduler-Job | jede Woche ein klarer Kontext; die Zusammenfassung landet in `plan_review` und wird nächste Woche zitiert |
| S9 | Die vier Tool-Namen `plan_propose`, `plan_commit`, `plan_adjust`, `plan_progress` bleiben, ihre Schemas ändern sich | Eval-Fälle und Prompt-Texte bleiben lesbar; kein Parallelbetrieb alter und neuer Tools |
| S10 | Private Trainingsdaten (Max' Phase-I-Plan, Zielzeiten) kommen **nicht ins Repo**, sondern über Einstieg, Chat oder eine lokale Importdatei | Das Repo ist öffentlich (Recherche §7.4). |

### 1.3 Antworten auf §15 (Max, 2026-10-17)

| Frage | Entscheidung | Folge |
|---|---|---|
| 1 HFmax-Rückfall | `208 − 0,7 × Alter` (Tanaka) | `metrics/hr_zones.resolve_hr_max` umgestellt; betrifft Stufe 1 A.6 und die Rückfall-Zonen §4.3 |
| 2 Halbmarathon-Ziel | Ziele stellt **jeder Nutzer selbst** ein; es gibt mehrere Nutzer mit verschiedenen Zielen | kein Zielwert im Plantyp; Zielzeit kommt aus `goal` bzw. dem Einstieg (§7.1) |
| 3 Verteilung | pyramidal in Basis und Aufbau, polarisiert in kurzen Blöcken vor dem Wettkampf (Spitze) | Plantyp-Parameter `verteilung: pyramidal`, `verteilung_spitze: polarisiert` |
| 4 Reihenfolge der Plantypen | **offen** | betrifft erst AP 9 |
| 5 Kraft | nur „Wiederholungen in Reserve“, keine 1RM-Schätzungen | keine 1RM-Spalte; Kraft-Einheiten mit RIR in der Notiz |
| 6 Leitplanken überschreibbar | ja, nur mit Begründung und Bestätigung (S3) | `override_reason` wie in §5.3 |
| 7 Übernahme | den dann laufenden Abschnitt übernehmen (§10) | wie §10 |
| 8 Wochenbesprechung | Sonntag 19:00, automatisch per Scheduler-Job (Scheduler ist seit `3910b46` auf `main`), Button zusätzlich | Aktion `coach.week_review` in AP 6 |
| 9 Detailtiefe | 2 Wochen nach Garmin | `COACH_DETAIL_WEEKS = 2` |

---

## 2. Ist-Stand, auf dem die Spec aufsetzt

Geprüft am Code auf `main` (`78c4ac6`). Spec-Aussagen über Stufe 1 beziehen sich auf die
Fassung in PR #1.

### 2.1 Planung heute (Phase 5)

| Stelle | Befund | Folge für Stufe 3 |
|---|---|---|
| `src/kairos/planning/algorithm.py:11-18` | feste Konstanten: Long Run 35 %, harte Einheit je 25 %, +10 % Last pro Woche, 7 Tage Taper mit Faktor 0,5 | wird durch Regeln aus der Wissensbank ersetzt; Taper laut Recherche §4.4 eher 8–14 Tage, −41 bis −60 % |
| `src/kairos/planning/algorithm.py:28` (`generate_plan_blocks`) | plant ganze Wochen nur nach freier Kalenderzeit und CTL; kein Ziel außer `goal_date`, keine Phasen, keine Sportart | Generator §6 neu |
| `src/kairos/db/models.py:474-491` (`Plan`) | `title`, `start_date`, `end_date`, `goal_date`, `status IN ('draft','committed','abandoned')`; kein Bezug zu `goal` | Erweiterung §5.3 |
| `src/kairos/db/models.py:494-518` (`PlanBlock`) | `workout_type IN ('long_run','hard','easy','rest')`, `target_trimp`, `calendar_event_id`, `status IN ('planned','done','skipped')`; keine Struktur, keine Uhrzeit, keine Sportart | Erweiterung §5.3 |
| `alembic/versions/27d8fcfada03_plan_tables.py:77-82` | RLS mit `FORCE` auf `plan_block` (und `plan`) | neue Tabellen folgen demselben Muster |
| `src/kairos/agent/tools.py:263-292` (`_free_blocks_by_day`) | Tagesgrenzen in UTC (`tzinfo=UTC`, Z. 283) | Stufe 1 A.8 stellt auf Ortszeit um; der Generator nutzt die neue Funktion |
| `src/kairos/agent/tools.py:295-306` (`_current_ctl`) | CTL aus `training_load`; ohne Historie 0,0 | bleibt als ein Eingangswert; dazu Umfangshistorie aus `activity_stats` |
| `src/kairos/agent/tools.py:309-338` (`plan_propose`) | Start immer `date.today()`, Titel fest, Ergebnis als Textzeilen | Neubau §8.2 |
| `src/kairos/agent/tools.py:341-369` (`plan_commit`) | je Block ein Kalendertermin **07:00–08:00 UTC** (Z. 357), kein Garmin | Neubau mit Garmin §8.3 |
| `src/kairos/agent/tools.py:372-397` (`plan_adjust`) | Faktor 0,7 bei Stress-Schlüsselwörtern (`_STRESS_KEYWORDS`, Z. 32), sonst 0,85, nur auf `target_trimp`; Kalendertermine werden nicht angepasst (Kommentar Z. 388-393) | Neubau mit strukturierten Änderungen §8.4 |
| `src/kairos/agent/tools.py:400-437` (`plan_progress`) | Soll/Ist nur als TRIMP-Summe der laufenden Woche | Neubau §8.5 |
| `src/kairos/agent/tools.py:603-665` | Tool-Specs: `plan_propose` `read`, `plan_commit`/`plan_adjust` `write` mit Bestätigung, `plan_progress` `read` | Risikoklassen bleiben |
| `src/kairos/repositories/plan.py:80` (`replace_remaining_blocks`) | existiert, hat im Code keinen Aufrufer | wird von der Rollierung (§6.4) genutzt oder entfernt |
| `tests/test_planning_algorithm.py`, `tests/test_agent_tools_planning.py`, `tests/test_plan_commit_integration.py`, `tests/test_plan_repository_integration.py` | Tests der Phase-5-Planung | werden mit AP 3/4/5 ersetzt |

### 2.2 Weitere Bausteine

| Stelle | Befund | Folge |
|---|---|---|
| `src/kairos/db/models.py:49-70` (`UserSetting`) | `birth_date`, `sex`, `resting_hr_override`, `hr_max_override`, Arbeitszeiten, Kalenderpuffer | HFmax bleibt dort (Stufe 1 A.6); Bezugswerte bekommen eine eigene Tabelle (§5.2) |
| `src/kairos/db/models.py:541-562` (`Goal`) + `src/kairos/routers/goals.py:16` | freie Ziele mit `target_value`/`target_unit`/`target_date`, CRUD unter `/api/goals`, Seite `web/src/routes/goals/` | der Plan verweist auf ein Ziel (`plan.goal_id`); der Einstieg legt es bei Bedarf an |
| `src/kairos/agent/situation_brief.py:142-151` (`_ziele_line`) | Lagebild nennt aktive Ziele | bekommt eine Coach-Zeile (§7.3) |
| `src/kairos/agent/history.py:8` | `HISTORY_BUDGET_TOKENS = 12_000` | Wochenbesprechung in eigener Konversation (S8), damit sie nicht in fremde Chats drückt |
| `web/src/routes/+layout.svelte:70-74` | Navigation: Übersicht, Kalender, Ziele, Gedächtnis, Chat | neuer Eintrag „Coach“ |
| `docs/03-agent-design.md` §4.3 | zweistufiges Tool-Laden ab > 30 Tools oder > 6.000 Schema-Tokens | 28 Tools bleiben darunter; Schema-Budget prüfen (§8.7) |
| Stufe 1 B.2/B.6 (PR #1) | `activity_stats` (je Aktivität) und `activity_step_result` (Soll/Ist je Workout-Schritt, Trefferregel D13) | Datengrundlage für Leitplanken und Wochenbesprechung |
| Stufe 1 D.1/D.3/D.4 (PR #1) | Kairos-Workout-Modell, `garmin_workout(_schedule)` mit `plan_block_id`, Workout-Tools mit Teilerfolgsformat | `plan_commit` baut darauf auf |
| Stufe 1 G.1 (PR #1) | Vorschau-Snapshots, `tool_progress` | Bestätigung von `plan_commit`/`plan_adjust` |
| Scheduler-Spec §5, §8 (PR #4) | Aktion `agent.prompt` in fester Job-Konversation | Wochenbesprechung als Job ist mit einer neuen Aktion `coach.week_review` möglich (§7.2) |

**Kein Code zum Coach-Modus vorhanden.** Eine Suche nach „coach“ im Repo findet nur die
Garmin-Coach-Befunde aus Stufe 1 AP 0 (`fbtAdaptiveWorkout`), keine Implementierung.

---

## 3. Wissensbank (`knowledge/training/`)

### 3.1 Ablage

Wie in der Recherche §7.1 vorgeschlagen:

```
knowledge/training/
  README.md          Aufbau, Vokabular, Evidenzstufen, Arbeitsregeln (eigene Worte, Quellen)
  quellen.yaml       Schlüssel → Autoren, Jahr, Titel, DOI/URL
  regeln/
    intensitaet/  progression/  taper/  kraft/  tests/  einheiten/  erholung/  gesundheit/
  plantypen/
    ausdauer-laufen-pyramidal.yaml
```

### 3.2 Eintrag

Eine Markdown-Datei je Regel. YAML-Kopf = Regelteil, darunter Erklärteil mit den
Abschnitten „Warum“, „Wann nicht“ und optional „Für den Nutzer“ (Kurzfassung in einem Satz).

| Feld | Pflicht | Regel |
|---|---|---|
| `id` | ja | stabil, Punktnotation `<sport>.<bereich>.<name>`, eindeutig |
| `version` | ja | Ganzzahl, steigt bei jeder inhaltlichen Änderung |
| `titel` | ja | ein Satz |
| `sportarten` | ja | Teilmenge von `laufen`, `rad`, `schwimmen`, `kraft`, `yoga`, `alle` |
| `art` | ja | `leitplanke` (blockiert), `regel` (Generator hält sie ein, Prüfer warnt), `parameter` (Plantyp setzt den Wert), `einheit` (Einheitentyp), `test` (Bezugswert) |
| `evidenz` | ja | `hoch`, `mittel`, `niedrig`, `praxis` (Recherche §1) |
| `quellen` | ja | Schlüssel aus `quellen.yaml`, mindestens einer |
| `regel` | ja | Objekt mit `typ` aus dem Vokabular §3.3 |

Planblöcke speichern die verwendeten `id@version`. Alte Versionen bleiben über Git
nachvollziehbar; die Datei enthält nur die aktuelle Version.

### 3.3 Vokabular des Regelteils

Erste Fassung aus der Recherche §7.1, präzisiert für den Generator. Jeder Typ ist eine
Python-Klasse (Pydantic, `discriminator="typ"`) mit einer Prüffunktion `check(plan_view) →
list[Verstoss]` und, wo sinnvoll, einer Erzeugungsfunktion für den Generator.

| `typ` | Felder | Prüft / erzeugt |
|---|---|---|
| `anteil_min` / `anteil_max` | `groesse` (z. B. `zeit.z1`), `bezug` (z. B. `zeit.gesamt`), `wert`, `fenster` (`woche`) | Z1 ≥ 75 % der Wochenzeit |
| `obergrenze_relativ` | `groesse`, `bezug` {`funktion`, `groesse`, `fenster_tage`}, `faktor`, `aktion` (`kuerzen`/`warnen`) | Einzellauf ≤ 1,10 × längster Lauf der letzten 30 Tage |
| `obergrenze_absolut` | `groesse`, `wert`, `einheit` | Long Run ≤ 2:30 h |
| `zuwachs_max` | `groesse`, `vergleich` (`vorwoche`/`schnitt_n_wochen`), `n`, `faktor` | Wochenumfang ≤ +10 % |
| `rhythmus` | `zyklus` (z. B. 4), `position`, `aenderung` | jede 4. Woche −30 % |
| `phase` | Liste {`art`, `dauer_wochen` (min/max oder Anteil), `schwerpunkt`, `einheiten`} | Basis → Aufbau → Spitze → Taper |
| `taper` | `tage` (min/max), `umfang_aenderung` (min/max), `intensitaet` (`halten`) | 8–14 Tage, −41 bis −60 % |
| `zonen` | `bezugswert`, Liste {`zone`, `von`, `bis`, `einheit`} | HF-Zonen in % LTHR, Pace-Tempi aus VDOT |
| `test` | `bezugswert`, `protokoll`, `formel` (Name einer Funktion im Code, kein freier Ausdruck) | VDOT aus Wettkampfzeit |
| `einheit` | `einheit_id`, `zone`, `struktur` (Vorlage im Kairos-Workout-Modell), `anteil_max_woche`, `dauer` | Schwellenintervalle, T ≤ 10 % des Wochenumfangs |
| `abstand_min` | `von` (Einheitenmenge), `zu`, `stunden` | Kraft ≥ 3 h vor/nach Ausdauer |
| `haeufigkeit` | `einheit_id` oder Menge, `min`/`max` pro Woche, je Phase | zwei Qualitätseinheiten pro Woche |

Freie Ausdrücke oder Code in YAML sind ausgeschlossen. Ein neuer `typ` braucht eine neue
Klasse im Code und einen Test.

### 3.4 Plantyp

```yaml
id: ausdauer-laufen-pyramidal
version: 1
titel: Wettkampfvorbereitung Laufen, pyramidale Verteilung
hauptsport: laufen
ziele: [wettkampf]               # wettkampf | gesundheit | einsteiger
bezugswerte:
  pflicht: [vdot]
  optional: [lthr_laufen, hf_max]
parameter:
  verteilung: pyramidal          # pyramidal | polarisiert (Recherche §8, Frage 3)
  entlastung_zyklus: 4
  entlastung_umfang: -0.30
  qualitaet_pro_woche: 2
  kraft_pro_woche: {basis: 2, aufbau: 2, spitze: 1, taper: 1}
  taper_tage: 21                 # Marathon; Halbmarathon 10
regeln:                          # Referenzen auf Einträge, Version wird beim Planen festgehalten
  - lauf.intensitaet.z1-anteil
  - lauf.progression.einzellauf
  - lauf.progression.wochenzuwachs
  - lauf.progression.entlastung
  - lauf.einheit.long-run
  - lauf.einheit.schwelle
  - lauf.einheit.intervall
  - lauf.einheit.wiederholung
  - lauf.einheit.marathontempo
  - alle.taper.standard
  - kraft.abstand
  - kraft.schwere-last
phasen: lauf.phase.klassisch
```

**Reihenfolge der Plantypen** (Vorschlag der Recherche §8, Frage 4, offen):
`ausdauer-laufen-pyramidal` → `gesundheit-ausdauer` → `einsteiger-laufen` → `ausdauer-rad`
→ Triathlon. Diese Spec liefert nur den ersten vollständig; die übrigen sind Inhalt, kein
neuer Code, solange ihr Vokabular in §3.3 enthalten ist.

### 3.5 Laden, Prüfen, CI

- `src/kairos/coach/knowledge.py`: `load_knowledge(path) → KnowledgeBase` liest alle
  Einträge, validiert sie (Pydantic) und löst die Referenzen der Plantypen auf. Ergebnis
  wird im Prozess gehalten (unveränderlich, wenige hundert KB).
- **CI-Test** `tests/test_knowledge_base.py`: Schema gültig, `id` eindeutig, alle
  `quellen` existieren, alle Referenzen in Plantypen auflösbar, jeder `einheit`-Eintrag
  erzeugt ein gültiges Kairos-Workout (Stufe 1 D.1), Erklärteil hat „Warum“ und „Wann nicht“.
- Beim Start: ungültige Einträge werden geloggt und ihr Plantyp als „nicht verfügbar“
  markiert (S7).
- **Urheberrecht:** Einträge in eigenen Worten, keine Tabellen aus Büchern, Werte aus den
  veröffentlichten Formeln berechnet (Recherche §7.4). Das README hält die Arbeitsregel fest.

---

## 4. Bezugswerte und Zonen

### 4.1 Arten

| `kind` | Einheit | Quelle | Verwendet für |
|---|---|---|---|
| `vdot` | – | Wettkampf oder Test 3–15 km, Formel Daniels & Gilbert (Recherche §2.3) | Pace-Tempi E, M, T, I, R |
| `lthr_laufen`, `lthr_rad` | bpm | 30-min-Test, Ø-HF der letzten 20 min | HF-Zonen in % LTHR |
| `ftp` | W | 20-min-Test × 0,95 | Leistungszonen Rad |
| `css` | s/100 m | 400 m + 200 m | Schwimmtempo |
| `critical_speed` | m/s | zwei Bestzeiten | optional, später |
| `hf_max` | bpm | **nicht hier**: `user_setting.hr_max_override` bzw. Formel (Stufe 1 A.6) | Rückfall für HF-Zonen |

### 4.2 Ermittlung

1. **Aus einer Aktivität:** Der Nutzer markiert im Chat oder auf der Coach-Seite eine
   Aktivität als Test oder Wettkampf (`reference_value_set` mit `activity_id`). Kairos
   berechnet den Wert aus `activity_stats` (Distanz, Bewegungszeit, HF) und zeigt die
   Rechnung.
2. **Vorschlag aus Bestleistungen:** Liegt in `activity_best_effort` (Stufe 1 B.4) ein
   Abschnitt über 3–15 km vor, der einen höheren VDOT ergibt als der gespeicherte, nennt
   das Lagebild einen Hinweis. Übernommen wird nur nach Bestätigung (Trainingsläufe sind
   selten maximal).
3. **Manuell:** Eingabe auf der Coach-Seite mit Datum und Quelle `manuell`.
4. **Veraltung:** Ein Wert älter als `REFERENCE_VALUE_STALE_DAYS` (Default 84 Tage, ein
   Trainingsblock) gilt als „Test fällig“. Der Generator plant dann in der nächsten
   passenden Woche eine Testeinheit (Einheit vom Typ `test`).

### 4.3 Zonen

`src/kairos/coach/zones.py` berechnet aus den Bezugswerten und dem `zonen`-Eintrag des
Plantyps die konkreten Bereiche je Einheit: Pace `from`/`to` in `m:ss`/km und `hr_range`
in bpm. Abbildung auf das Drei-Zonen-Modell (S4) für die Verteilungsregeln:

| Drei-Zonen | Daniels | HF (% LTHR, Laufen) |
|---|---|---|
| Z1 | E, Long Run | < 85 % |
| Z2 | M, T | 85–100 % |
| Z3 | I, R | > 100 % |

Ohne `lthr_laufen` nimmt Kairos HF-Bereiche aus % HFmax als Rückfall und markiert sie als
„geschätzt“. Ohne Pflicht-Bezugswert des Plantyps (`vdot`) kann kein Plan erzeugt werden;
der Einstieg fragt ihn ab oder plant als Erstes einen Test.

---

## 5. Datenmodell (eine Migration)

### 5.1 `coach_profile` (neu)

```sql
CREATE TABLE coach_profile (
  user_id            uuid PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
  plan_type          text NOT NULL,              -- Plantyp-ID (D25)
  main_sport         text NOT NULL CHECK (main_sport IN ('laufen','rad','triathlon')),
  supplementary      text[] NOT NULL DEFAULT '{}',   -- kraft, schwimmen, yoga
  availability       jsonb NOT NULL,             -- je Wochentag: max. Minuten, Tageszeit, Qualität möglich
  parameters         jsonb NOT NULL DEFAULT '{}',    -- Abweichungen von Plantyp-Parametern
  review_weekday     smallint NOT NULL DEFAULT 6,    -- 0 = Montag; Default Sonntag (D21)
  review_time        time NOT NULL DEFAULT '19:00',
  onboarded_at       timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
```

`availability` Beispiel (Max, Entscheidungsprotokoll §4: Dienstreisen Mo-Abend bis Do-Abend):

```json
{"mo": {"max_min": 45, "quality": false}, "di": {"max_min": 45, "quality": false},
 "mi": {"max_min": 45, "quality": false}, "do": {"max_min": 45, "quality": false},
 "fr": {"max_min": 75, "quality": true},  "sa": {"max_min": 90, "quality": true},
 "so": {"max_min": 150, "quality": true}}
```

Die Werte sind ein Beispiel für das Format; die echten gibt Max im Einstieg ein (S10).

### 5.2 `athlete_reference_value` (neu)

```sql
CREATE TABLE athlete_reference_value (
  id            bigserial PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('vdot','lthr_laufen','lthr_rad','ftp','css','critical_speed')),
  value         double precision NOT NULL,
  measured_on   date NOT NULL,
  source        text NOT NULL CHECK (source IN ('test','wettkampf','manuell','bestleistung')),
  activity_id   bigint REFERENCES activity(id) ON DELETE SET NULL,
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_reference_value_current ON athlete_reference_value (user_id, kind, measured_on DESC);
```

Der aktuelle Wert ist der jüngste je `kind`. Historie bleibt für Verlaufsgrafik und
Wochenbesprechung („VDOT seit Planstart +1,5“).

### 5.3 `plan` und `plan_block` erweitern (S1)

```sql
ALTER TABLE plan
  ADD COLUMN goal_id         uuid REFERENCES goal(id) ON DELETE SET NULL,
  ADD COLUMN plan_type       text,              -- NULL = Phase-5-Altplan
  ADD COLUMN plan_type_version integer,
  ADD COLUMN parameters      jsonb NOT NULL DEFAULT '{}',   -- eingefrorene Parameter beim Erzeugen
  ADD COLUMN detail_until    date;              -- bis hierhin gibt es Einzelblöcke (D21)
-- status: 'draft','committed','abandoned' + 'completed'
-- höchstens ein aktiver Plan je Nutzer (S6)
CREATE UNIQUE INDEX uq_plan_active ON plan (user_id) WHERE status = 'committed';

CREATE TABLE plan_phase (
  id             uuid PRIMARY KEY,
  plan_id        uuid NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
  user_id        uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  seq            smallint NOT NULL,
  kind           text NOT NULL CHECK (kind IN ('basis','aufbau','spitze','taper','wettkampf','uebergang')),
  start_date     date NOT NULL,
  end_date       date NOT NULL,
  focus          text,                         -- Schwerpunkt in einem Satz
  volume_min_km  double precision,             -- Zielkorridor je Woche (Laufen); für Rad Stunden
  volume_max_km  double precision,
  rule_refs      text[] NOT NULL DEFAULT '{}',
  UNIQUE (plan_id, seq)
);

ALTER TABLE plan_block
  ADD COLUMN phase_id        uuid REFERENCES plan_phase(id) ON DELETE SET NULL,
  ADD COLUMN sport           text,
  ADD COLUMN unit_id         text,             -- Einheitentyp aus der Wissensbank, z. B. lauf.einheit.schwelle
  ADD COLUMN start_at        timestamptz,      -- geplante Uhrzeit (Ortszeit-bewusst gespeichert)
  ADD COLUMN planned_duration_s integer,
  ADD COLUMN planned_distance_m integer,
  ADD COLUMN steps           jsonb,            -- Kairos-Workout-Modell (Stufe 1 D.1)
  ADD COLUMN rule_refs       text[] NOT NULL DEFAULT '{}',   -- id@version (D24)
  ADD COLUMN override_reason text,             -- gesetzt, wenn eine Leitplanke bewusst überschrieben wurde (S3)
  ADD COLUMN activity_id     bigint REFERENCES activity(id) ON DELETE SET NULL;  -- zugeordnete Ist-Aktivität
-- workout_type: alte vier Werte bleiben gültig, neu: 'quality','strength','cross','test'
-- status: 'planned','done','skipped' + 'partial','replaced'
```

Die zusätzlichen CHECK-Werte ersetzen die Constraints `plan_status_check`,
`plan_block_workout_type_check` und `plan_block_status_check` (drop + create in derselben
Migration). `workout_type` bleibt als grobe Klasse für Lagebild und Kalender, `unit_id`
trägt die genaue Einheit.

### 5.4 `plan_review` (neu)

```sql
CREATE TABLE plan_review (
  id               uuid PRIMARY KEY,
  plan_id          uuid NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
  user_id          uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  week_start       date NOT NULL,
  conversation_id  uuid REFERENCES conversation(id) ON DELETE SET NULL,
  facts            jsonb NOT NULL,   -- Ergebnis von plan_progress(scope='woche') zum Zeitpunkt der Besprechung
  summary          text,             -- vom Agenten am Ende geschrieben, ≤ 1.000 Zeichen
  changes          jsonb NOT NULL DEFAULT '[]',   -- angewendete plan_adjust-Änderungen
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (plan_id, week_start)
);
```

### 5.5 RLS, ORM, Repositories

- Alle neuen Tabellen: `ENABLE` + `FORCE ROW LEVEL SECURITY`, Policy `tenant_isolation`
  auf `user_id` wie in `27d8fcfada03_plan_tables.py:77-82`. Jede Session, die sie liest
  oder schreibt, ruft `install_rls_listener(session, user_id)` (CLAUDE.md).
- RLS-CI-Test um die vier neuen Tabellen erweitern.
- ORM-Modelle in `src/kairos/db/models.py`; Repositories `CoachProfileRepository`,
  `ReferenceValueRepository`, `PlanRepository` (erweitert), `PlanReviewRepository`.
- **Bestandsdaten:** Phase-5-Pläne behalten `plan_type = NULL` und gelten als Altpläne.
  Ein bestehender `committed`-Plan wird bei der Migration auf `abandoned` gesetzt, falls
  der eindeutige Index sonst verletzt würde (mehrere aktive Pläne je Nutzer); die Migration
  protokolliert, welche.

---

## 6. Plan-Generator und Regelprüfer (`src/kairos/coach/`)

### 6.1 Module

| Modul | Aufgabe |
|---|---|
| `knowledge.py` | Wissensbank laden und validieren (§3.5) |
| `rules.py` | Regeltypen aus §3.3: Pydantic-Modelle, `check`, Erzeugungshilfen |
| `zones.py` | Bezugswerte → Pace- und HF-Bereiche (§4.3); VDOT-Formel |
| `history.py` | Trainingshistorie als Eingabe: Wochenumfänge, längster Lauf 30 Tage, Zonenzeit, CTL (aus `activity_stats`, `training_load`) |
| `generator.py` | Phasen und Einzelblöcke erzeugen (§6.2–6.4) |
| `validator.py` | Plan oder Änderung gegen den Plantyp prüfen (§6.5) |
| `service.py` | Orchestrierung für Tools und API: Vorschlag, Commit, Anpassung, Woche abschließen |

Generator und Prüfer sind **reine Funktionen** ohne DB- und Netzwerkzugriff; `service.py`
lädt die Eingaben und schreibt die Ergebnisse. Das macht sie mit Property-Tests prüfbar.

### 6.2 Eingaben und Ausgabe

```python
@dataclass(frozen=True)
class PlanInput:
    plan_type: PlanType               # aufgelöst, mit Regelversionen
    parameters: Mapping[str, Any]     # Plantyp-Parameter + Abweichungen aus coach_profile
    goal: GoalSpec                    # Art, Datum, Distanz, Zielzeit (optional)
    start: date
    availability: Availability
    reference_values: ReferenceValues
    history: TrainingHistory          # letzte 12 Wochen
    free_time: Mapping[date, list[FreeBlock]]   # nur für die Detailwochen
    fixed_blocks: Sequence[PlanBlockView]       # bereits übertragene oder erledigte Blöcke

@dataclass(frozen=True)
class PlanOutput:
    phases: list[PhaseDraft]
    blocks: list[BlockDraft]          # nur bis detail_until
    warnings: list[Verstoss]          # weiche Regeln, die knapp sind oder nicht passten
    explain: list[str]                # kurze, deterministische Begründungen mit Regel-IDs
```

### 6.3 Phasen (grob, bis zum Ziel)

1. Gesamtdauer = Ziel − Start. Der `phase`-Eintrag des Plantyps verteilt sie auf Basis,
   Aufbau, Spitze und Taper (Dauern als Spannen); Taper-Länge aus `taper_tage`.
2. Je Phase ein Umfangskorridor: Start aus der Historie (Schnitt der letzten 4 Wochen),
   Steigerung begrenzt durch `zuwachs_max`, Entlastungswochen durch `rhythmus`, Taper durch
   `taper`.
3. Ist die Zeit zu kurz für die Mindestdauern, kürzt der Generator zuerst die Basis, dann
   den Aufbau, und meldet das als Warnung („Zeit bis zum Ziel knapp“). Unter
   `MIN_PLAN_WEEKS` (Default 4) gibt es nur einen Taper-/Erhaltungsplan.
4. Ohne Wettkampfziel (`gesundheit`) gibt es eine Dauerphase mit Wochenrhythmus statt
   Periodisierung.

### 6.4 Einzelblöcke (rollierend, D21)

Für die nächsten `COACH_DETAIL_WEEKS` (Default 2) Wochen:

1. **Wochenvolumen** aus dem Phasenkorridor, angepasst an die letzte Woche (Soll/Ist):
   Wurde weniger als 80 % des Solls erreicht, startet die nächste Woche nicht höher als das
   Ist plus `zuwachs_max`.
2. **Einheiten wählen:** `haeufigkeit`-Regeln der Phase (z. B. 2 Qualität, 1 Long Run,
   2 Kraft), Rest locker.
3. **Tage zuordnen:** Long Run auf den Tag mit der größten Verfügbarkeit; Qualität nur an
   Tagen mit `quality: true`, mindestens 48 h Abstand; Kraft nach `abstand_min`; mindestens
   ein Ruhetag. Konflikte mit dem Kalender (freie Zeit) verschieben innerhalb der Woche,
   sonst wird die Einheit gekürzt oder entfällt mit Warnung.
4. **Struktur füllen:** Die `einheit`-Vorlage liefert Schritte; Dauer/Distanz aus dem
   Volumenanteil; Ziele aus `zones.py`. Ergebnis ist ein gültiges Kairos-Workout (Stufe 1 D.1).
5. **Prüfen** (§6.5). Verstöße gegen Leitplanken werden durch Kürzen gelöst
   (`aktion: kuerzen`); bleibt ein Verstoß, wird die Einheit nicht erzeugt.
6. `plan.detail_until` = letzter Tag der Detailwochen.

**Rollierung:** Beim Abschluss der Wochenbesprechung (§7) erzeugt `service.roll_forward`
die Woche nach `detail_until` und ersetzt noch nicht übertragene, künftige Blöcke
(`PlanRepository.replace_remaining_blocks`). Übertragene Blöcke ändert nur `plan_adjust`.

### 6.5 Regelprüfer

`validate(plan_view, plan_type, history) → Verstösse` prüft jede Regel des Plantyps über
die Wochen des Plans plus die Historie (für Fenster wie „30 Tage“).

| Ergebnis | Wirkung im Generator | Wirkung bei `plan_adjust` |
|---|---|---|
| Leitplanke verletzt | Einheit kürzen oder weglassen | Änderung abgelehnt mit Begründung und Regel-ID; Überschreiben nur mit `override_reason` und Bestätigung (S3) |
| Regel verletzt | Warnung im Ergebnis | Änderung erlaubt, Warnung in Vorschau und Antwort |
| Parameter | – | Änderung des Parameters nur über `coach_profile` |

Jeder Verstoß enthält `rule_id@version`, Ist-Wert, Grenze und den „Für den Nutzer“-Satz
des Eintrags, damit der Agent ihn ohne zusätzlichen Tool-Aufruf erklären kann.

### 6.6 Erste Leitplanken (aus der Recherche)

| Regel | Art | Evidenz |
|---|---|---|
| Kein Lauf > 110 % des längsten der letzten 30 Tage (`lauf.progression.einzellauf`) | leitplanke | hoch |
| Z1-Anteil ≥ 70 % der Wochenzeit (`lauf.intensitaet.z1-anteil`) | leitplanke | hoch |
| Long Run ≤ 2:30 h und ≤ 35 % des Wochenumfangs (`lauf.einheit.long-run`) | regel | praxis |
| Wochenumfang ≤ +10 % gegenüber Schnitt der letzten 3 Wochen | regel | mittel |
| T ≤ 10 %, I ≤ 8 %, R ≤ 5 %, M ≤ 20 % des Wochenumfangs | regel | praxis |
| Kraft ≥ 3 h Abstand zu Ausdauer, nicht vor Qualität am Folgetag | regel | praxis |
| Taper 8–14 Tage (Marathon bis 21), Umfang −41 bis −60 %, Intensität halten | regel | hoch |

---

## 7. Abläufe

### 7.1 Geführter Einstieg (Seite „Coach“)

Fünf Schritte, je eine Karte; die Eingaben gehen in `coach_profile`, `goal` und
`athlete_reference_value`:

1. **Ziel:** Wettkampf (Distanz, Datum, optional Zielzeit), Gesundheit (Minuten pro Woche)
   oder Einstieg. Bestehende aktive Ziele aus `/api/goals` zur Auswahl.
2. **Zeitraum:** Startdatum (Default nächster Montag), Ziel-Datum aus Schritt 1.
3. **Verfügbare Tage:** je Wochentag Minuten und „Qualität möglich“.
4. **Sportarten:** Hauptsport, Ergänzungen; daraus Vorschlag des Plantyps (D25).
5. **Testwert:** passende Bezugswerte (Pflicht laut Plantyp) aus einer Aktivität, manuell
   oder „noch keiner – Test einplanen“. Kairos zeigt die abgeleiteten Bereiche.

Danach erzeugt `POST /api/coach/plan/propose` einen Entwurf (Phasen + 2 Detailwochen) und
zeigt ihn mit Warnungen und Begründungen. „Plan übernehmen“ öffnet einen Chat mit
vorbereiteter Nachricht, in dem der Agent `plan_commit` mit Vorschau-Snapshot ausführt. So
läuft jede Schreibaktion durch die Bestätigung im Harness (Stufe 1 G.1), auch vom Frontend aus.

### 7.2 Wochenbesprechung (D20, D21)

**Auslöser:**

- Button „Wochenbesprechung starten“ auf der Coach-Seite (immer verfügbar, auch auf Abruf, D31);
- ab Stufe 2 ein Scheduler-Job zu `coach_profile.review_weekday/review_time` mit einer
  neuen Aktion `coach.week_review` (Parameter: keine). Sie unterscheidet sich von
  `agent.prompt` darin, dass sie je Woche eine neue Konversation anlegt (S8) statt einer
  festen Job-Konversation. Die Aktion kommt in die Registry der Scheduler-Spec §5.

**Ablauf:**

1. `service.start_week_review(user_id, week_start)` legt `plan_review` und eine neue
   Konversation „Wochenbesprechung KW n“ an, berechnet `facts` über `plan_progress`
   (`scope="woche"`) und schreibt eine erste Nutzer-Nachricht mit festem Text
   („Wochenbesprechung für KW n. Fakten liegen vor.“).
2. Der Agent bekommt im Systemprompt-Zusatz die `facts`, die Zusammenfassung der Vorwoche
   (`plan_review.summary`) und den Entwurf der nächsten Woche aus dem Generator.
3. Er bespricht: Erledigt/verpasst, Soll/Ist je Qualitätseinheit (Trefferquote aus
   `activity_step_result`, D13), Entkopplung im Long Run, Leitplanken-Status, Erholung
   (HRV, Schlaf), Hinweise auf veraltete Bezugswerte.
4. Der Nutzer antwortet (Befinden, Termine, Wünsche). Änderungen laufen über `plan_adjust`.
5. Abschluss: `plan_adjust` mit `finalize_week=true` schreibt die Zusammenfassung in
   `plan_review.summary`, rolliert den Plan (§6.4) und überträgt die neue Woche nach
   Bestätigung nach Garmin. Ein Tool-Aufruf, eine Bestätigung.

Ohne Antwort des Nutzers bleibt die Besprechung offen; die bereits übertragene nächste
Woche (aus der Rollierung der Vorwoche) gilt weiter. Es gibt keine automatische Änderung
ohne Bestätigung; automatische Entlastung ist Stufe 2 (D32).

### 7.3 Laufender Betrieb im Chat

- **Lagebild** (`situation_brief.py`): neue Zeile „Coach: Plan ‚…‘, Phase Basis (Woche 3/8),
  heute: Schwelle 4×6′, Test fällig: VDOT (91 Tage)“. Nur wenn ein aktiver Plan existiert.
- **Systemprompt:** kurzer Abschnitt „Coach-Modus“: Zahlen kommen aus Tools, Regeln werden
  mit Regel-ID und Evidenzstufe begründet, Leitplanken nicht eigenmächtig umgehen.
- **Ist-Zuordnung:** Nach jedem Garmin-Sync ordnet `service.match_activities` neue
  Aktivitäten Planblöcken zu: zuerst über `garmin_workout_schedule` (Workout auf der Uhr
  gestartet), sonst gleicher Tag und gleiche Sportart. Status `done`, `partial` (< 80 % der
  geplanten Dauer) oder nach Tagesende `skipped`.

---

## 8. Agent-Tools

### 8.1 Übersicht

| Tool | Risiko | Bestätigung | Änderung |
|---|---|---|---|
| `plan_propose` | read | direkt (Entwurf) | Neubau: Generator, Ziel, Plantyp |
| `plan_commit` | write | Bestätigung (Snapshot) | Neubau: Garmin-Kopplung |
| `plan_adjust` | write | Bestätigung (Snapshot) | Neubau: strukturierte Änderungen, Regelprüfer, Wochenabschluss |
| `plan_progress` | read | direkt | Neubau: Soll/Ist je Block und Woche |
| `knowledge_lookup` | read | direkt | neu |
| `reference_value_set` | write | Bestätigung | neu |

### 8.2 `plan_propose` (read)

```json
{
  "name": "plan_propose",
  "description": "Erstellt einen Trainingsplan-Entwurf aus Plantyp, Ziel, Verfügbarkeit und Bezugswerten. Ohne goal_id für das aktive Ziel des Coach-Profils. Schreibt nichts nach Garmin oder in den Kalender.",
  "parameters": {
    "type": "object",
    "properties": {
      "goal_id": {"type": "string"},
      "start": {"type": "string", "description": "ISO-Datum, Default nächster Montag"},
      "overrides": {"type": "object", "description": "Plantyp-Parameter für diesen Entwurf, z. B. {\"verteilung\": \"polarisiert\"}"}
    }
  }
}
```

Ergebnis: Phasen (je eine Zeile), Einheiten der Detailwochen in Kurzform (Stufe 1 D.1),
Wochenumfänge, Warnungen mit Regel-ID. Speichert einen `draft` (ersetzt ältere Entwürfe
desselben Nutzers).

### 8.3 `plan_commit` (write)

Vorgaben aus Stufe 1 §8:

- **Vorschau:** Anzahl Einheiten, Zeitraum, je Einheit Tag, Uhrzeit, Kurzform; betroffene
  Kalendertage. Der Nutzer bestätigt den Snapshot (G.1).
- **Ausführung je Block** (nur bis `detail_until`, Ruhetage ausgenommen): Workout anlegen →
  terminieren → Kalendertermin anlegen → lokale Zeilen (`garmin_workout`,
  `garmin_workout_schedule.plan_block_id`, `plan_block.calendar_event_id`) schreiben.
- **Idempotent:** Blöcke mit vorhandenem Schedule werden übersprungen. Teilerfolge im
  Ergebnisformat von Stufe 1 D.4, Kompensation nach D.6, Fortschritt per `tool_progress`.
- **Uhrzeit:** aus `availability` (Tageszeit) bzw. dem ersten passenden freien Block, in
  `app_user.home_timezone` – nicht mehr 07:00 UTC (heute `tools.py:357`).
- Erster Commit setzt `plan.status = 'committed'` und beendet einen vorherigen aktiven Plan
  (`completed` bzw. `abandoned`); dessen künftige Workouts räumt der Nutzer über
  `workout_delete` mit Filter `plan_id` auf (Stufe 1 §8) – die Vorschau weist darauf hin.

### 8.4 `plan_adjust` (write)

```json
{
  "name": "plan_adjust",
  "description": "Ändert künftige Einheiten des aktiven Plans: verschieben, kürzen, ersetzen, streichen, hinzufügen. Prüft jede Änderung gegen die Regeln des Plantyps. finalize_week schließt die Wochenbesprechung ab und plant die nächste Woche.",
  "parameters": {
    "type": "object",
    "properties": {
      "changes": {
        "type": "array", "maxItems": 14,
        "items": {
          "type": "object",
          "properties": {
            "op": {"type": "string", "enum": ["move", "shorten", "replace", "remove", "add"]},
            "block_id": {"type": "string"},
            "day": {"type": "string"},
            "factor": {"type": "number", "description": "nur shorten, 0.3–1.0"},
            "unit_id": {"type": "string", "description": "nur replace/add, Einheit aus der Wissensbank"},
            "override_reason": {"type": "string", "description": "nur wenn der Nutzer eine Leitplanke ausdrücklich überschreiben will"}
          },
          "required": ["op"]
        }
      },
      "reason": {"type": "string"},
      "finalize_week": {"type": "boolean", "default": false},
      "review_summary": {"type": "string", "maxLength": 1000}
    }
  }
}
```

- Ablauf: Änderungen auf eine Kopie anwenden → Regelprüfer → Vorschau mit Alt/Neu,
  Warnungen und abgelehnten Änderungen → Bestätigung → übertragene Blöcke per
  `workout_update` (gleiche Garmin-ID; bei neuem Tag zusätzlich neu terminieren),
  Kalendertermin ersetzen, lokale Zeilen aktualisieren.
- Abgelehnte Leitplanken-Verstöße erscheinen in der Vorschau nicht als Änderung; der Agent
  erklärt sie und fragt nach, ob der Nutzer bewusst überschreiben will (S3).
- `finalize_week=true`: schreibt `review_summary` und `changes` in `plan_review`, rolliert
  (§6.4) und nimmt die neue Woche in denselben Snapshot auf.

### 8.5 `plan_progress` (read)

Parameter `scope` (`heute` | `woche` | `plan`, Default `woche`), optional `week_start`.

| Scope | Inhalt |
|---|---|
| `heute` | heutige Einheit mit Kurzform und Zielbereichen, Status, nächste Qualitätseinheit |
| `woche` | je Block Soll/Ist (Dauer, Distanz, Zonenzeit, Trefferquote aus `activity_step_result`), Wochensumme Soll/Ist, Z1-Anteil, Leitplanken-Status, Entkopplung des Long Runs, Erholungswerte, Bezugswerte mit Alter |
| `plan` | Phasen mit Fortschritt, Umfangskurve Soll/Ist je Woche, Bezugswert-Verlauf, offene Warnungen |

Obergrenzen wie in Stufe 1 C.0 (Hülle `summary`/`data`/`meta`, `meta.next`).

### 8.6 `knowledge_lookup` und `reference_value_set`

- `knowledge_lookup(rule_id | query, sport?)` → Titel, Art, Evidenz, Erklärteil (gekürzt
  auf 1.500 Zeichen) und Quellen. `query` sucht per Volltext über Titel und Erklärteil
  (Einträge im Speicher, keine Embeddings nötig).
- `reference_value_set(kind, value? | activity_id, measured_on?, source)` → berechnet bei
  `activity_id` den Wert, Vorschau mit Rechnung und den neuen Bereichen der kommenden
  Einheiten. Nach Bestätigung speichern; künftige, noch nicht übertragene Blöcke werden neu
  berechnet, übertragene erst in der nächsten Wochenbesprechung (keine stillen
  Garmin-Änderungen).

### 8.7 Budget

28 Tools liegen unter der Schwelle von 30 (`03` §4.3). Der CI-Test aus Stufe 1 G.3
(18.000 Zeichen) muss mit den neuen Schemas weiter grün sein; erwartete Zunahme ≈ 2.000
Zeichen (größere `plan_adjust`- und `plan_propose`-Schemas, zwei neue Tools). Wird die
Grenze gerissen, wandert `knowledge_lookup` als Erstes in das zweistufige Laden.

---

## 9. API und Frontend

### 9.1 Endpunkte (`src/kairos/routers/coach.py`)

| Methode | Pfad | Zweck |
|---|---|---|
| GET/PUT | `/api/coach/profile` | Coach-Profil lesen/schreiben (Plantyp, Verfügbarkeit, Ergänzungen, Besprechungszeit) |
| GET | `/api/coach/plan-types` | verfügbare Plantypen mit Titel, Zielen, Pflicht-Bezugswerten |
| GET/POST | `/api/coach/reference-values` | Historie lesen, Wert manuell anlegen |
| POST | `/api/coach/plan/propose` | Entwurf erzeugen (wie `plan_propose`) |
| GET | `/api/coach/plan` | aktiver Plan: Phasen, Detailwochen, Status je Block |
| GET | `/api/coach/plan/progress?scope=` | wie `plan_progress` |
| POST | `/api/coach/review` | Wochenbesprechung starten, liefert `conversation_id` |
| GET | `/api/coach/knowledge/{rule_id}` | Erklärteil für Tooltips |

Schreibende Planaktionen (Commit, Anpassung) laufen über den Chat (§7.1), nicht über
eigene Endpunkte. Alle Endpunkte mit `current_user` und `install_rls_listener`.

### 9.2 Seite „Coach“ (`web/src/routes/coach/`)

Im Designsystem „Ruhe“, neuer Navigationseintrag zwischen „Ziele“ und „Gedächtnis“.

- **Ohne Profil:** Einstieg (§7.1) als Schrittfolge.
- **Mit Plan:**
  - Kopf: Ziel, Tage bis zum Ziel, aktuelle Phase;
  - Phasenleiste über die Gesamtdauer;
  - Detailwochen als Liste je Tag mit Kurzform, Status (`StatusPill`), Soll/Ist-Kennzahlen
    und Link zur Aktivität;
  - Umfangskurve Soll/Ist (ECharts, `EChartsBase`);
  - Bezugswerte mit Alter, Verlauf und „Test fällig“;
  - Buttons „Wochenbesprechung starten“, „Plan neu vorschlagen“, „Einstellungen“.
- **Regel-Tooltips:** Warnungen und Begründungen verlinken die Regel-ID; `InfoTooltip`
  zeigt den Satz „Für den Nutzer“ und die Evidenzstufe.

---

## 10. Übernahme des laufenden Plans (D27)

Max' Phase I (21.09.–29.11.2026) endet voraussichtlich, bevor Stufe 3 fertig ist (Stufe 1
und 2 liegen davor). Deshalb übernimmt Kairos **den dann laufenden Abschnitt**
(voraussichtlich „Kraftausdauer Dez–Jan“) statt Phase I:

1. Max legt im Einstieg Ziel (Marathon April 2027), Verfügbarkeit und Bezugswerte an. Der
   VDOT kommt aus dem 10-km-Kontrolltest vom 31.10. bzw. dem Halbmarathon am 29.11.
2. `plan_propose` mit `start` = Beginn des laufenden Abschnitts erzeugt Phasen bis April.
3. Bereits bei Garmin liegende Workouts aus dem eigenen Importer werden nicht übernommen;
   der Nutzer löscht sie oder lässt sie auslaufen. Der Spiegel (Stufe 1 D.3) zeigt sie mit
   `origin='garmin'`.
4. Max' bisherige Regeln sind im Plantyp abgebildet (§3.4, Recherche §6.1); Zahlen, die laut
   Recherche §6.2 nicht zusammenpassen (Halbmarathon-Ziel), klärt Max vorher (§15, Frage 2).

Eine Importdatei für einen frei formulierten Bestandsplan ist nicht vorgesehen; falls Max
sie doch braucht, liegt sie lokal und wird nicht eingecheckt (S10).

---

## 11. Sicherheit und Leitplanken

- **RLS** auf allen neuen Tabellen (§5.5); Wissensbank ist nicht nutzerbezogen und liegt
  schreibgeschützt im Prozess.
- **Keine Schreibaktion ohne Bestätigung:** `plan_commit`, `plan_adjust`,
  `reference_value_set` sind `write` mit Snapshot. Die Ausnahme „automatische Entlastung“
  (D32) gehört zu Stufe 2 und braucht dort ihren eigenen ADR.
- **Gesundheit:** Der Systemprompt-Abschnitt nennt die Grenze aus `00-vision-und-scope.md` §3
  („kein Ersatz für Sportwissenschaft“). Bei Schmerz, Verletzung oder Krankheit im Chat
  steigert der Agent nicht, schlägt Entlastung oder Pause vor und empfiehlt ärztliche
  Abklärung bei anhaltenden Beschwerden.
- **Kein LLM-generierter Regelinhalt:** Der Agent liest die Wissensbank, schreibt aber
  nicht hinein. Änderungen laufen über Pull Requests.
- **Overrides nachvollziehbar:** `plan_block.override_reason` und `plan_review.changes`
  zeigen, wann und warum von einer Leitplanke abgewichen wurde.
- **Öffentliches Repo:** keine personenbezogenen Trainingsdaten in Wissensbank, Fixtures
  oder Tests (S10); Testdaten sind synthetisch.

---

## 12. Tests, Evaluierung, Arbeitspakete

### 12.1 Testansatz

- **Wissensbank:** CI-Test §3.5.
- **Generator/Prüfer:** reine Funktionen; Tabellen-Tests für Max' Szenario (synthetische
  Werte) und Property-Tests (Hypothesis): Für beliebige Verfügbarkeit, Historie und Ziel
  verletzt kein erzeugter Plan eine Leitplanke; Z1-Anteil ≥ 70 %; Taper-Umfang im Korridor;
  mindestens ein Ruhetag je Woche.
- **Zonen:** VDOT-Formel gegen die Werte der Recherche §6.2 (45:11 auf 10 km → VDOT ≈ 45,0;
  T ≈ 4:38/km, I ≈ 4:14/km).
- **Service/Tools:** testcontainers-Postgres mit RLS; Fake-Garmin-Schreibdienst aus Stufe 1;
  Teilerfolg und Idempotenz von `plan_commit`.
- **Frontend:** Komponenten-Tests für Einstieg und Wochenansicht.

### 12.2 Eval-Fälle (Fortsetzung von Stufe 1 §12.1)

| # | Frage/Aufgabe | Erwartung |
|---|---|---|
| 27 | „Plan mir den Marathon im April.“ | `plan_propose`, Antwort nennt Phasen und Warnungen, keine erfundenen Paces |
| 28 | „Was steht heute an?“ | `plan_progress(scope=heute)` |
| 29 | „Ich kann Samstag nicht, schieb den Long Run auf Sonntag.“ | `plan_adjust` `move`, Vorschau, Bestätigung |
| 30 | „Mach den Long Run am Sonntag 32 km“ (längster Lauf 30 Tage: 24 km) | Ablehnung mit `lauf.progression.einzellauf`, Erklärung, Rückfrage |
| 31 | „Warum nur 80 % locker?“ | `knowledge_lookup`, Antwort nennt Evidenzstufe |
| 32 | „Mein 10-km-Test von gestern war 44:20.“ | `reference_value_set` mit `activity_id`, Vorschau der neuen Bereiche |
| 33 | Wochenbesprechung mit einer verpassten Qualitätseinheit | Besprechung nennt sie, nächste Woche ohne Nachholen auf Kosten der Leitplanken, `finalize_week` |

### 12.3 Arbeitspakete

| AP | Inhalt | Voraussetzung | Abnahme |
|---|---|---|---|
| **0 Entscheidungen** | Fragen §15 mit Max klären; Recherche-Fragen §8 beantworten | – | Antworten in §1.1 eingetragen |
| **1 Wissensbank-Gerüst** | `knowledge/training/` mit README, `quellen.yaml`, Vokabular-Klassen (`rules.py`), Loader, CI-Test; Einträge und Plantyp `ausdauer-laufen-pyramidal` | AP 0 (Fragen 1, 3) | CI grün; alle Einträge aus §6.6 vorhanden |
| **2 Datenmodell** | Migration §5, ORM, Repositories, RLS-Test | – | Migration hin/zurück; RLS-Test für vier neue Tabellen grün; Bestandspläne korrekt |
| **3 Generator und Prüfer** | `zones.py`, `history.py`, `generator.py`, `validator.py` | AP 1; Stufe 1 AP 2 (`activity_stats`) für echte Historie, vorher mit Fake-Historie testbar | Property-Tests grün; Max-Szenario plausibel (Review mit Max) |
| **4 Tools und Lagebild** | `plan_propose`, `plan_progress`, `knowledge_lookup`, `reference_value_set`; Systemprompt, Lagebild, Ist-Zuordnung | AP 2, AP 3; Stufe 1 AP 3 (Lese-Tools, `activity_step_result`) | Eval 27, 28, 31, 32 grün; Schema-Budget grün |
| **5 Garmin-Kopplung** | `plan_commit`, `plan_adjust` inkl. Filter `plan_id` in `workout_unschedule`/`workout_delete` | AP 4; Stufe 1 AP 4 (Harness) und AP 5 (Workouts) | Eval 29, 30 grün (Fake); Teilerfolg- und Idempotenz-Test; ein manueller Live-Durchlauf mit Wegwerf-Plan (1 Woche) |
| **6 Wochenbesprechung** | `start_week_review`, `plan_review`, `finalize_week`, Rollierung; Scheduler-Aktion `coach.week_review`, falls Stufe 2 umgesetzt | AP 5; optional Scheduler | Eval 33 grün; Rollierung über 3 simulierte Wochen getestet |
| **7 Frontend** | Seite „Coach“, Einstieg, Plan-Ansicht, Bezugswerte, Endpunkte §9.1 | AP 4 (lesend), AP 6 (Button) | Durchlauf Einstieg → Entwurf → Commit im Browser |
| **8 Übernahme und Doku** | Max' laufenden Abschnitt übernehmen (§10); `01`, `03` (Tools), `08` (Stufenplan), HANDOVER, ADR „Wissensbank als Code“ | AP 7 | Max' Plan aktiv; keine Aussage in der Doku widerspricht dem Code |
| **9 Weitere Plantypen** | `gesundheit-ausdauer`, `einsteiger-laufen`, `ausdauer-rad` als Wissensbank-Inhalt | AP 1–4 | je Plantyp Property-Tests und ein Beispielplan |

**Reihenfolge:** AP 0 → AP 1 und AP 2 parallel → AP 3 → AP 4 → AP 5 → AP 6 → AP 7 → AP 8;
AP 9 danach. **AP 0–3 können vor Abschluss von Stufe 1 beginnen** (sie brauchen nur die
Wissensbank, die Migration und Fake-Historien); ab AP 4 wartet die Arbeit auf Stufe 1
AP 3, ab AP 5 auf Stufe 1 AP 4/5.

---

## 13. Risiken

| Risiko | W | A | Gegenmaßnahme |
|---|---|---|---|
| Generator erzeugt Pläne, die sich „falsch anfühlen“, obwohl alle Regeln eingehalten sind | hoch | mittel | Review des Max-Szenarios in AP 3; Parameter je Nutzer anpassbar; Wochenbesprechung korrigiert |
| Regelvokabular reicht für Rad/Triathlon nicht | mittel | mittel | Plantypen nacheinander (AP 9); neuer `typ` = neue Klasse + Test |
| Falsche Bezugswerte (z. B. Trainingslauf als Test) führen zu zu schnellen Paces | mittel | hoch | Bestleistungen nur als Vorschlag mit Bestätigung; Vorschau mit Rechnung; Veraltungsregel |
| Leitplanken werden durch Overrides ausgehöhlt | niedrig | mittel | Override nur mit Begründung und Bestätigung, protokolliert; Wochenbesprechung nennt Overrides |
| Garmin-Teilerfolge beim Commit vieler Blöcke | mittel | mittel | nur 1–2 Wochen übertragen (D21); Idempotenz; Stufe 1 D.6 |
| Stufe 1 oder 2 verzögert sich, Coach-Modus wartet | hoch | mittel | AP 0–3 ohne Stufe 1 möglich; Wochenbesprechung ohne Scheduler per Button |
| Tool-Auswahl wird mit 28 Tools ungenauer | niedrig | mittel | Eval beobachten; `knowledge_lookup` zuerst ins zweistufige Laden |
| Urheberrecht bei Inhalten aus Büchern | niedrig | mittel | eigene Worte, Formeln statt Tabellen, Quellen (Recherche §7.4) |
| Gesundheitsrisiko durch zu aggressive Pläne | niedrig | hoch | Leitplanken mit Evidenz hoch; Hinweis bei Schmerz/Krankheit; kein Steigern ohne Ist-Daten |

---

## 14. Nicht-Ziele

- Automatische Entlastung ohne Bestätigung, Web-Push, automatische Reaktionen (Stufe 2, D29–D34).
- Trainer-Rollen oder Pläne für andere Nutzer (D22).
- Triathlon-Plantyp und Koppeleinheiten in der ersten Fassung (Recherche §7.3).
- Kraft-Workouts mit Übungen und Lasten (Stufe 1.1, D15); bis dahin plant der Coach Kraft
  als Einheit mit Dauer und Notiz.
- Schwimm-Workouts mit Bahnen und Stilen (Stufe 1 §15, Punkt 2).
- Ernährung, Wettkampf-Pacing-Strategie, Laktat- oder Labortests.
- Lernende oder statistische Modelle, die Regeln selbst anpassen.
- Bearbeiten der Wissensbank über die Oberfläche oder durch den Agenten.

---

## 15. Offene Fragen an Max

> **Beantwortet am 2026-10-17 bis auf Frage 4**, siehe §1.3.

Aus der Recherche §8 übernommen (1–5) und aus dieser Spec (6–9):

1. **HFmax-Rückfall:** `208 − 0,7 × Alter` (Tanaka) statt `220 − Alter`? Betrifft Stufe 1 A.6
   und die Rückfall-Zonen hier (§4.3).
2. **Halbmarathon-Ziel:** 1:33–1:36 oder Tempo 4:38–4:42 (≈ 1:38–1:39)? (Recherche §6.2)
3. **Default-Verteilung** für `ausdauer-laufen-pyramidal`: pyramidal oder polarisiert?
   Vorschlag: pyramidal in der Basis, polarisiert in kurzen Blöcken vor dem Wettkampf.
4. **Reihenfolge der Plantypen** und Sportarten/Ziele der anderen Nutzer.
5. **Kraft:** 1RM-Schätzungen speichern oder nur „Wiederholungen in Reserve“?
6. **Leitplanken überschreibbar?** Vorschlag S3: ja, nur mit Begründung und Bestätigung.
   Alternative: nie überschreibbar.
7. **Übernahme:** Den dann laufenden Abschnitt übernehmen (§10) statt Phase I – einverstanden?
8. **Wochenbesprechung:** Sonntag 19:00 als Default (D21: „Sonntagabend nach dem Long Run“)?
   Und: soll sie als Scheduler-Job automatisch starten, sobald Stufe 2 da ist, oder nur auf
   Knopfdruck?
9. **Detailtiefe:** 2 Wochen im Voraus nach Garmin übertragen (Default) oder nur die
   nächste Woche?
