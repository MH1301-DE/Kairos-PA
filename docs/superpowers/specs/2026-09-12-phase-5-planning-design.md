# Phase 5 — Planung (Slice): Design-Spezifikation

> Autonome Session (Nutzer explizit: "mache soweit es geht mit Phase 5
> weiter"). Scope-Entscheidungen unten mit Begründung, gleiches Muster wie
> Phase 3/4. Anders als Phase 4 gibt es hier **keinen vorherigen Dialog** zu
> Phase-5-spezifischen Fragen — die Entscheidungen sind autonom getroffen und
> müssen vor einer Ausführung noch vom Nutzer bestätigt werden, wenn Zeit ist.

## Ziel

Referenzfragen 13 ("Erstell mir einen Trainingsplan für die nächsten 3
Wochen") und 15 ("Was habe ich diese Woche schon trainiert und was fehlt
noch laut Plan?") vollständig beantwortbar — inkl. echtem Schreiben in den
Kalender, wie `08-roadmap.md`s (korrigierte) Phase-5-Abnahme verlangt.

## Scope-Entscheidungen (mit Begründung)

**1. Nur "Planung", nicht "Planung & Proaktivität" — der nächtliche
Insight-Job + Web Push sind explizit nicht Teil dieser Spec.** Die
Referenzfragen-Abnahme (13+15) verlangt keine Proaktivität, nur eine korrekt
beantwortbare Planungsfrage. Der Insight-Job ist ein eigenständiges
Subsystem (Cron-Scheduling, Web-Push-Infrastruktur, Benachrichtigungs-
einstellungen) ohne Abhängigkeit zur Planungslogik — sauber als eigener
Folge-Task trennbar, nicht künstlich mit hineingezogen, nur weil beides
unter "Phase 5" im Roadmap steht.

**2. Der Planungsalgorithmus ist eine regelbasierte Heuristik, kein
Solver/Optimierer.** "Constraint-Erfüllung" aus dem Roadmap-Text klingt nach
einem echten Constraint-Solver — für 1-5 Freizeitsportler ist das
Overengineering. Stattdessen eine nachvollziehbare, testbare Regel-Kette
(analog zu den bestehenden reinen Formel-Funktionen in
`src/kairos/metrics/formulas/`):
- Ein Long Run pro Woche, gelegt auf den Tag mit dem längsten freien Block.
- Harte Einheiten (Intervalle/Tempo) mit Mindestabstand ≥ 48 h zueinander,
  nur an Tagen mit einem freien Block ≥ 60 Minuten.
- Restliche Trainingstage: lockere Einheiten, mindestens ein echter Ruhetag
  pro Woche.
- Wochenbelastung (TRIMP-Summe, Edwards-Formel — bereits kanonisch für
  CTL/ATL/TSB, siehe HANDOVER) steigt ~10 %/Woche, letzte Woche vor
  Zieldatum taper (Belastung sinkt gezielt), falls ein Zieldatum gesetzt ist.
- Deterministisch bei gleichen Eingaben (Kalender, Erholungszustand,
  Zieldatum) — nachvollziehbar, nicht "der Agent hat sich das ausgedacht".

**3. Vier neue Tools statt einem generischen "plan"-Tool, weiterhin keine
Tool-Registry.** `plan_propose` (read-ähnlich, erzeugt einen Entwurf, kein
Kalender-Schreibzugriff), `plan_commit` (write, Proposal-Bestätigung,
schreibt echte Kalendertermine — beantwortet Frage 13 vollständig erst nach
Bestätigung), `plan_adjust` (write, Proposal-Bestätigung, passt einen
laufenden Plan an neue Umstände an), `plan_progress` (read, beantwortet
Frage 15 direkt: Plan-Soll vs. Trainings-Ist der aktuellen Woche). Macht 12
Core-Tools insgesamt — bei 12 ist weiterhin nichts zu durchsuchen (Phase-4-
MVP-Spec Scope-Entscheidung 1 gilt unverändert), keine Registry nötig.

**4. `plan_commit` schreibt Kalendertermine über die bestehende
`propose_calendar_event`-Logik, kein neuer Schreibpfad.** Ein
`plan_block` wird 1:1 zu einem `POST /api/calendar/events`-Aufruf (bzw.
direkt `_create_calendar_event`) pro Block — exakt das Muster, das die
Phase-4-MVP-Tools für Einzeltermine schon nutzen. Kein Sonder-Batch-Schreib-
pfad, auch wenn ein Plan aus bis zu 21 Terminen (3 Wochen) bestehen kann.

## Datenmodell

### Neue Tabelle: `plan`

```
id            UUID PK
user_id       UUID FK app_user, RLS-Spalte
title         TEXT NOT NULL
start_date    DATE NOT NULL
end_date      DATE NOT NULL
goal_date     DATE                        -- optionales Zieldatum (Rennen), für Taper-Logik
status        TEXT NOT NULL DEFAULT 'draft'   -- draft | committed | abandoned
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()

FORCE ROW LEVEL SECURITY (Standard-Muster)
```

### Neue Tabelle: `plan_block`

```
id                 UUID PK
plan_id            UUID FK plan, RLS über user_id (eigene Spalte, gleicher Grund wie
                   conversation_message.user_id -- keine Subquery in der RLS-Policy)
user_id            UUID FK app_user
day                DATE NOT NULL
workout_type       TEXT NOT NULL          -- 'long_run' | 'hard' | 'easy' | 'rest'
target_trimp       FLOAT                  -- NULL für 'rest'
calendar_event_id  UUID FK calendar_event, NULL bis plan_commit gelaufen ist
status             TEXT NOT NULL DEFAULT 'planned'  -- planned | done | skipped

FORCE ROW LEVEL SECURITY (Standard-Muster)
CheckConstraint workout_type IN ('long_run','hard','easy','rest')
CheckConstraint status IN ('planned','done','skipped')
```

**`status='done'` wird nicht automatisch aus echten Trainingsdaten
abgeleitet** — `plan_progress` vergleicht bei jedem Aufruf live gegen die
echten Aktivitätsdaten (wie Frage 15 es verlangt: "was habe ich schon
trainiert"), statt einen Cache-Status zu pflegen, der veralten könnte.

## Backend-Architektur

### `src/kairos/planning/algorithm.py`

Reine Funktion, kein DB-Zugriff, analog zu `metrics/formulas/`:

```python
def generate_plan_blocks(
    *, start: date, end: date, goal_date: date | None,
    free_blocks_by_day: dict[date, list[FreeBlock]],
    current_ctl: float,
) -> list[PlannedBlock]:
    ...
```

`PlannedBlock` = `(day, workout_type, target_trimp)`. Nimmt bereits
berechnete freie Blöcke (aus dem bestehenden `compute_free_blocks`) und den
aktuellen CTL-Wert als Eingabe — holt sich selbst nichts aus der DB, bleibt
so pur testbar wie jede bestehende Formel.

### `src/kairos/repositories/plan.py`

`PlanRepository`: `create_draft`, `get`, `list_blocks`, `commit` (setzt
`status='committed'`, verknüpft `plan_block.calendar_event_id` je Block),
`replace_remaining_blocks` (für `plan_adjust` — ersetzt nur zukünftige,
noch nicht `'done'`-markierte Blöcke).

### Vier neue Tool-Handler in `src/kairos/agent/tools.py`

- `plan_propose_handler(session, *, user_id, weeks, goal_date=None)` — ruft
  `compute_free_blocks` je Tag im Fenster + `generate_plan_blocks` auf,
  persistiert einen `plan`+`plan_block`-Satz mit `status='draft'`
  (read-artig, kein Proposal nötig — ein Entwurf ist folgenlos, exakt wie
  `remember`s Begründung in der MVP-Spec). Rückgabe: `plan_id` + Übersicht.
- `plan_commit_handler(session, *, user_id, plan_id)` — `write`,
  `requires_confirmation=True`. Ruft für jeden offenen Block
  `_create_calendar_event` auf, setzt `plan.status='committed'`.
- `plan_adjust_handler(session, *, user_id, plan_id, reason)` — `write`,
  `requires_confirmation=True`. Reduziert die Ziel-TRIMP-Werte der
  verbleibenden `'planned'`-Blöcke (einfache Regel: -30 % bei "viel Stress"/
  "krank"-artigen `reason`-Stichworten, sonst -15 % als konservativer
  Default).
  > **Korrektur (2026-09-12, während der Implementierung von Task 4):**
  > `plan_adjust` aktualisiert **keine** bereits committeten Kalendertermine
  > — Phase 3 hat bewusst nur `POST`/`DELETE` für Kalenderevents gebaut, kein
  > `PATCH`/Update-Endpoint (siehe `docs/HANDOVER.md`). Der Handler ändert
  > ausschließlich `plan_block.target_trimp` für Blöcke mit `status='planned'`;
  > bereits verknüpfte `calendar_event`-Zeilen bleiben unverändert. Der
  > ursprüngliche Satz oben ("aktualisiert bereits committete
  > Kalendertermine") ist als dokumentierte Historie stehen gelassen.
- `plan_progress_handler(session, *, user_id, plan_id=None)` — `read`.
  Ohne `plan_id` wird der aktuell aktive (`status='committed'`) Plan des
  Nutzers verwendet. Vergleicht diese Woche: Soll (`plan_block`-Einträge)
  gegen Ist (echte `activity`-Einträge im selben Zeitraum, TRIMP über die
  bestehende `edwards_daily_load_series`).

## Frontend

**Kein neues Frontend in dieser Spec.** Pläne werden ausschließlich über den
Chat (`/chat`, bereits vorhanden) vorgeschlagen/bestätigt/abgefragt — exakt
wie die Phase-4-MVP-Spec es für `propose_calendar_event` schon vorsieht,
kein Sonderweg für Trainingspläne. Eine dedizierte `/plans`-Übersichtsseite
wäre ein sinnvoller späterer Ausbau, aber nicht nötig, um die Referenzfragen
13/15 zu beantworten (die werden per Chat-Frage gestellt).

## Testing-Strategie

- Unit-Tests für `generate_plan_blocks` (reine Funktion): 3-Wochen-Fenster
  mit typischem freien-Blöcke-Muster erzeugt genau einen Long Run/Woche,
  Mindestabstand zwischen harten Einheiten wird eingehalten, Taper-Woche vor
  `goal_date` hat niedrigere Gesamtbelastung als die Woche davor, ein
  Fenster ganz ohne freie Blöcke erzeugt nur `rest`-Blöcke (kein Crash).
- Tool-Handler-Tests (isoliert, wie die bestehenden `test_agent_tools.py`) +
  Dispatcher-Tests (wie `test_agent_dispatcher.py`: `plan_commit`/
  `plan_adjust` ohne Bestätigung dürfen ihren Handler nie aufrufen).
- Integrationstest: `plan_commit` gegen eine echte DB — jeder `plan_block`
  bekommt eine `calendar_event_id`, die zugehörige `calendar_event`-Zeile
  hat `source='kairos'`.

## Global Constraints

- `install_rls_listener(session, user_id)` auf jeder Session, die `plan`/
  `plan_block` liest oder schreibt.
- `ruff`/`mypy --strict`, conventional commits.
- `plan_commit`/`plan_adjust` erzwingen Proposal-Bestätigung wie jedes
  andere `write`-Tool (Phase-4-MVP-Dispatcher, unverändert wiederverwendet).
- Kein neuer Kalender-Schreibpfad — jeder Termin läuft über
  `_create_calendar_event` (Scope-Entscheidung 4).

## Abnahmekriterien

Referenzfrage 13 ("Trainingsplan für die nächsten 3 Wochen") erzeugt über
`plan_propose` + `plan_commit` einen nachvollziehbaren, im echten
Google-Kalender sichtbaren Trainingsplan. Referenzfrage 15 ("was habe ich
schon trainiert, was fehlt laut Plan") wird über `plan_progress` korrekt
und mit echten Zahlen beantwortet.

## Bewusst nicht Teil dieser Spec (Folge-Task)

- Nächtlicher Insight-Job (regelbasiert) + Web Push + Benachrichtigungs-
  einstellungen — das "Proaktivität"-Drittel von Phase 5.
- Eine dedizierte `/plans`-Frontend-Seite außerhalb des Chats.
- Was passiert, wenn ein Nutzer einen `calendar_event` manuell löscht, der
  zu einem `plan_block` gehört (verwaist der Block, oder wird er erkannt?)
  — nicht spezifiziert, gleiche Kategorie offener Punkt wie die bereits in
  Phase 3 dokumentierte "DELETE ohne aktive Verbindung"-Lücke.
