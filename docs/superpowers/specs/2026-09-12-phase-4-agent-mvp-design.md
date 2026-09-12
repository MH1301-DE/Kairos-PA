# Phase 4 — Agent (MVP-Slice): Design-Spezifikation

> Fortsetzung der dialogischen Brainstorming-Session aus `docs/HANDOVER.md`
> ("Phase 4 — Agent: Brainstorming-Stand"). Alle Scope- und Sicherheits-
> entscheidungen unten wurden im Dialog mit dem Nutzer getroffen, nicht
> autonom entschieden — im Unterschied zu Phase 3, wo der Nutzer abwesend
> war. Ein Teil der Bausteine (Gedächtnis-Speicher, Tool-Sicherheitsgrenzen)
> ist bereits implementiert und committed, nicht nur geplant — siehe
> Abschnitt "Bereits umgesetzt" unten.

## Ziel

Ein nutzbarer Konversations-Agent, der die 13 (von 15) Referenzfragen aus
`docs/00-vision-und-scope.md` Abschnitt 5 korrekt beantwortet — ohne die
volle Spezifikation aus `docs/03-agent-design.md` in einem Rutsch zu bauen.
Reduziert auf das, was für einen alltagstauglichen Agenten mit 8 Tools
wirklich nötig ist (Scope-Entscheidung 1).

## Scope-Entscheidungen (im Dialog getroffen, mit Begründung)

**1. MVP-Slice statt Vollspezifikation.** `docs/03-agent-design.md` beschreibt
eine für 60–90 Tools ausgelegte Architektur (zweistufige Tool-Ladung mit
Embeddings, Sticky Loading, Pack-Prewarming, volles 3-Schicht-Gedächtnis,
nächtlicher Proaktivitäts-Job). Bei den geplanten 8 Core-Tools dieser Phase
gibt es nichts zu durchsuchen — eine `tool_registry` mit Embeddings wäre
Komplexität ohne Gegenwert. **Explizit nicht Teil dieser Phase:**

- `tool_registry`-Tabelle mit Embeddings, `search_tools`/`load_tools` als
  echte Registry-Abfrage (siehe Datenmodell — stattdessen eine statische
  Python-Konstante)
- Sticky Loading, Pack-Prewarming, Nutzungsstatistik (Abschnitt 4.4 in
  `03-agent-design.md`) — lohnt sich erst, wenn tatsächlich > 8 Tools existieren
- Volles 3-Schicht-Gedächtnis (Profil/semantisch/episodisch mit
  Embedding-Retrieval) — die MVP-Version ist eine flache Liste (siehe
  "Bereits umgesetzt" unten), `recall` ist ein einfacher Abruf, keine
  Vektorsuche
- Nächtlicher Proaktivitäts-Job / Insight-Job (Abschnitt 7) — gehört laut
  Roadmap ohnehin zu Phase 5
- Konversations-Streaming — Chat-Antworten kommen für die MVP als
  vollständige Antwort zurück, nicht token-weise gestreamt. Additive
  Erweiterung später, kein Architekturrisiko (siehe Backend-Architektur)

**2. LLM-Provider: litellm statt eigenem Connector-Protocol.** Die bereits
getroffene Entscheidung "beliebiger API-Key muss einsetzbar sein, kein
Hardcoding auf einen Anbieter" (`docs/00-vision-und-scope.md` Zeile ~129,
dort noch veraltet als "API-basiert (Anthropic Claude)" — wird mit dieser
Spec korrigiert) wird über die etablierte Multi-Provider-Bibliothek
`litellm` erfüllt statt über ein eigenes `Connector`-artiges Protocol
(ADR-0003-Muster). Begründung: litellm deckt bereits die relevanten
Provider ab (Anthropic, OpenAI, Google, lokale Modelle über eine
einheitliche `completion()`-API inkl. Tool-Calling), ein eigenes Protocol
würde denselben Adapter-Code nur erneut schreiben. `litellm` unterstützt
außerdem `litellm.completion(..., stream=False)` mit strukturiertem
Tool-Calling — passt direkt zum Tool-Ausgabekontrakt aus
`03-agent-design.md` Abschnitt 4.5.

**3. Eval-Gate: Fragen 13 und 15 raus aus der Phase-4-Abnahme, Pflicht für
Phase 5.** `docs/00-vision-und-scope.md` Abschnitt 5 listet 15
Referenzfragen; `docs/08-roadmap.md` Phase 4 verlangt aktuell "15/15
korrekt", Phase 5 nennt widersprüchlich "Referenzfrage 8 und 14" als eigene
Abnahme — ein in `docs/HANDOVER.md` bereits vermerkter, ungelöster
Widerspruch. Auflösung nach Einzelprüfung jeder der 15 Fragen gegen den
MVP-Tool-Satz (`query_health`, `analyze_records`, `query_calendar`,
`render`, plus das bereits bestehende `POST /api/calendar/events` als
Proposal-Bestätigung):

- **Fragen 1–12 und 14** sind mit dem MVP-Tool-Satz beantwortbar — reine
  Abfrage/Analyse, oder im Fall von Frage 8 ("nächste harte Einheit ohne
  Überlastung") und 11 ("Lauf-Einheit für morgen einplanen") ein einzelner
  Terminvorschlag mit Bestätigung, der exakt dem bereits in Phase 3 gebauten
  Proposal-Flow entspricht (`POST /api/calendar/events`, kein neues
  Planungs-Tool nötig). Frage 14 ("Training an Stress anpassen") ist reine
  Empfehlung, kein automatisches Umplanen.
- **Frage 13** ("Trainingsplan für die nächsten 3 Wochen") verlangt echte
  Mehrwochen-Periodenplanung (Constraint-Erfüllung über freie Blöcke,
  Erholungszustand, Mindestabstände) — das ist exakt der in
  `08-roadmap.md` Phase 5 beschriebene Planungsalgorithmus
  (`plan`/`plan_block`, `plan.propose`/`plan.commit`/`plan.adjust`), keine
  Erweiterung des MVP-Tool-Satzes.
- **Frage 15** ("Was fehlt laut Plan") setzt einen Plan voraus, der erst
  durch Frage 13 entsteht — hängt zwangsläufig an Phase 5.
- **Roadmap-Korrektur nötig:** `08-roadmap.md`s Phase-5-Abnahme nennt
  aktuell "Referenzfrage 8 und 14" — nach dieser Analyse sind das die
  falschen Nummern (8 und 14 sind MVP-tauglich, s.o.). Wird auf
  "Referenzfrage 13 und 15" korrigiert (siehe Abschnitt "Nötige
  Doku-Korrekturen" unten).

**Phase-4-Abnahme (angepasst):** 13/13 Referenzfragen (alle außer 13, 15)
korrekt, Median-Input < 15.000 Tokens.

**4. Gedächtnis-Schreibpfad: automatisches Schreiben + sichtbarer
Rückgängig-Hinweis, kein Pre-Confirmation-Proposal.**
`03-agent-design.md` Abschnitt 5 beschreibt einen Proposal-Status
("automatisch extrahierte Fakten landen im Status `proposed` … Bestätigung
im Dashboard") — dieser Teil wird durch diese Spec **ersetzt**: `remember()`
schreibt sofort, jede Chat-Antwort mit einem `remember`-Aufruf zeigt aber
zwingend einen sichtbaren Hinweis-Chip ("Kairos hat sich gemerkt: … ·
Rückgängig") direkt unter der Antwort. Nichts läuft still im Hintergrund,
aber nicht jede Kleinigkeit unterbricht die Konversation mit einer
Rückfrage. Begründung: bei Dutzenden kleinen Fakten pro Woche wäre eine
Bestätigung pro Fakt reine Reibung ohne Sicherheitsgewinn — Einsehen und
Löschen ist über die bereits gebaute `/memory`-Seite jederzeit möglich.

## Bereits umgesetzt (nicht nur geplant)

Diese Bausteine sind bereits implementiert und auf `main` gemergt, bevor der
Orchestrator selbst existiert — bewusst vorgezogen, weil sie unabhängig vom
Tool-Calling-Loop sind und die Tool-Sicherheitsgrenzen von Anfang an
serverseitig verankern:

- **`agent_memory`-Tabelle** (RLS, Migration `9f3d6a1b2c48`) + `/api/memory`
  CRUD + `/memory`-Verwaltungsseite. Der `source`-Spalte
  (`'user' | 'agent'`) wird vom client-seitigen Endpoint immer auf
  `"user"` erzwungen — ein künftiges `remember`-Tool schreibt `source="agent"`
  über `SqlMemoryRepository.create()` direkt, nie über den öffentlichen
  Router, damit ein Client das "von Kairos"-Badge nie fälschen kann. Der
  sichtbare Rückgängig-Chip (s.o.) fehlt noch — der braucht die
  Chat-Oberfläche, die erst in dieser Phase entsteht.
- **Rate-Limiter für Sync/Backfill** (`SyncJobRegistry`-Cooldown, 5 Min
  Garmin-Backfill / 1 Min Kalender-Sync, `src/kairos/routers/sync.py`) —
  greift am bestehenden REST-Endpoint, also automatisch auch für ein
  künftiges `sync.trigger`-Tool, ohne dass der Dispatcher das noch einmal
  durchsetzen müsste.
- **Bestätigungspflicht beim Löschen fremder Kalendertermine**
  (`DELETE /api/calendar/events/{id}?confirm=true` für `source='external'`,
  serverseitig erzwungen, `src/kairos/routers/calendar.py`) — aus demselben
  Grund am Endpoint verankert statt erst im künftigen Tool-Dispatcher.
- **Verbindung-trennen bleibt ein für den Agenten nicht erreichbares
  Werkzeug** — es existiert aktuell kein Disconnect-Endpoint; falls einer
  gebaut wird, darf er nie als Tool registriert werden (siehe "Nicht
  verhandelbare Grenzen" unten).

## Datenmodell

### Neue Tabelle: `conversation`

```
id            UUID PK
user_id       UUID FK app_user, RLS-Spalte
title         TEXT                      -- erste Nutzernachricht, gekürzt (Anzeige in einer Verlaufsliste)
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()

FORCE ROW LEVEL SECURITY (Standard-Muster)
```

### Neue Tabelle: `conversation_message`

```
id                UUID PK
conversation_id   UUID FK conversation, RLS-Spalte (über user_id auf conversation, siehe unten)
user_id           UUID FK app_user       -- redundant zu conversation.user_id, aber nötig für die RLS-Policy direkt auf dieser Tabelle
role              TEXT NOT NULL          -- 'user' | 'assistant' | 'tool'
content           TEXT                  -- Klartext bei user/assistant; JSON-Ergebnis bei tool
tool_calls        JSONB                 -- vom Modell angeforderte Tool-Calls dieses Turns, falls vorhanden
created_at        TIMESTAMPTZ NOT NULL DEFAULT now()

FORCE ROW LEVEL SECURITY (Standard-Muster)
```

**Kein Rolling-Compaction-Feld in dieser Phase.** `03-agent-design.md`
Abschnitt 5 beschreibt eine fortgeschriebene Zusammenfassung älterer
Nachrichten (max. 400 Tokens). Für die MVP-Phase reicht ein einfacher
Kontextfenster-Cutoff (letzte N Nachrichten wörtlich, siehe
Backend-Architektur) — Compaction ist eine additive Optimierung, sobald
reale Konversationslängen das nötig machen, kein Tag-1-Erfordernis.

### Neue Tabelle: `metric_daily_value`

Schließt die in dieser Session gefundene Lücke: abgeleitete Formel-Metriken
(CTL, ATL, TSB, ACWR, TRIMP-Varianten, Sleep Debt, HRV-Baseline,
Monotonie/Strain, Resting-HR-Trend) existieren aktuell nur als
On-Demand-Berechnung für einen einzelnen `as_of`-Tag
(`src/kairos/metrics/registry.py`), nie als gespeicherte Tagesreihe — genau
deshalb liefert `query_health`/`analyze_records` für Referenzfrage 9
("CTL-Verlauf dieses Jahr") noch keine echte Zeitreihe.

```
user_id       UUID FK app_user, RLS-Spalte, Teil des PK
metric_id     TEXT NOT NULL             -- z.B. 'ctl', 'atl', 'tsb', 'acwr' (kein FK auf metric_def -- das sind Formel-IDs, keine Rohmetrik-IDs)
variant_id    TEXT NOT NULL             -- z.B. 'edwards', 'banister' -- Teil des PK, ein Tag kann mehrere Varianten haben
day           DATE NOT NULL
value         DOUBLE PRECISION
confidence    TEXT NOT NULL             -- 'high' | 'medium' | 'low' | 'insufficient_data', gleiche Werte wie MetricResult.confidence

PRIMARY KEY (user_id, metric_id, variant_id, day)
FORCE ROW LEVEL SECURITY (Standard-Muster)
```

Befüllt durch eine neue Funktion in
`src/kairos/repositories/metrics_recompute.py` (`recompute_metric_daily_values`),
die für jeden Tag mit vorliegenden Rohdaten jede registrierte
`MetricVariant` aus der `MetricRegistry` einmal aufruft und das Ergebnis
persistiert — exakt das gleiche Delete-dann-Insert-Muster wie
`recompute_wellness_daily_stats`. Reiner Rechenaufwand (keine neuen
Formeln), läuft im selben Recompute-Trigger wie die bestehenden
Tages-Aggregate. **Kein eigener Task in dieser Phase** — das ist ein
unabhängig vom Agenten sofort umsetzbares Arbeitspaket (siehe "Nächste
Schritte" unten), wird hier nur spezifiziert, weil `query_health` darauf
aufbaut.

### Neue Tabelle: `custom_metric_definition`

```
id             UUID PK
user_id        UUID FK app_user, RLS-Spalte
code           TEXT NOT NULL             -- vom Nutzer/Agent vergeben, z.B. 'my_recovery_score'
display_name   TEXT NOT NULL
expression     TEXT NOT NULL             -- eingeschränkter Ausdruck, siehe unten
created_by     TEXT NOT NULL DEFAULT 'user'   -- 'user' | 'agent', gleiches Muster wie agent_memory.source
created_at     TIMESTAMPTZ NOT NULL DEFAULT now()

UNIQUE (user_id, code)
FORCE ROW LEVEL SECURITY (Standard-Muster)
```

**Formel-Ausführung: eingeschränkte Ausdruckssprache, kein `eval()`.**
Entscheidung aus dieser Session: nur Arithmetik (`+ - * / ( )`) und
Referenzen auf existierende Metrik-Codes (aus `metric_def` oder
`metric_daily_value.metric_id`) — kein Funktionsaufruf, kein Import, keine
Schleife. Umsetzung über `simpleeval` (whitelisted Grammatik, keine
beliebige Python-Ausführung) mit den referenzierten Metrik-Werten als
einzige verfügbare Namen im Auswertungskontext. Beispiel:
`expression = "hrv_5min * 0.5 + sleep_hours * 0.3 - stress * 0.2"`.

**Nicht Teil dieser Phase.** Wie die Zeitreihen-Tabelle oben ist das ein
eigenständiges, vom Orchestrator unabhängiges Arbeitspaket — hier nur
spezifiziert, weil ein künftiges `metrics.create_custom` MVP-kompatibel als
9. Tool oder als Erweiterung von `render` andockt, sobald es gebaut wird.
Custom-Metriken erscheinen **nicht automatisch** im Dashboard (Entscheidung
aus dieser Session) — der Nutzer weist eine neue Metrik explizit einer
Kachel zu, das widerspricht der aktuellen Formulierung in
`docs/05-erweiterbarkeit.md` Abschnitt 5 ("Überschreiben bestehender
`metric_def` nicht möglich ohne Kern-Änderung") nicht, weil
`custom_metric_definition` bewusst eine eigene Tabelle ist, kein Eingriff
in `metric_def` selbst.

## Backend-Architektur

### `src/kairos/agent/orchestrator.py`

Ein einzelner async Tool-Calling-Loop über `litellm.completion()`
(`stream=False` für diese Phase, s.o.):

```
while True:
    response = litellm.completion(model=user_model_setting, messages=messages, tools=CORE_TOOLS_SCHEMA)
    if response.tool_calls is None:
        persist_and_return(response.content)
        break
    for call in response.tool_calls:
        result = await DISPATCHER[call.name](user_id, call.arguments)  # Risikoklassen-Prüfung hier, siehe unten
        messages.append(tool_result_message(call.id, result))
```

`user_model_setting` kommt aus einer neuen Spalte `user_setting.llm_model`
(z.B. `"anthropic/claude-sonnet-5"`) — der API-Key selbst liegt
envelope-verschlüsselt in einer neuen `connection`-Zeile mit
`connector='llm_provider'` (exakt dasselbe Credential-Muster wie Garmin/
Google Calendar, `credentials_enc` über `kek_from_settings`/`wrap_dek`),
statt eines Werts in `.env` — das erfüllt "beliebiger API-Key pro Nutzer
einsetzbar" wörtlich, nicht nur pro Deployment.

### Core-Tools als statische Konstante, keine Registry-Tabelle

`03-agent-design.md` Abschnitt 4.2 sieht `tool_registry` als SQL-Tabelle mit
Embeddings vor — für 8 statische Tools ohne Suche ist das reiner Overhead
(Scope-Entscheidung 1). Stattdessen: `src/kairos/agent/tools.py` mit einer
festen Liste:

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk_class: Literal["read", "write", "destructive"]
    requires_confirmation: bool   # True für alles außer "read"
    json_schema: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]

CORE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("query_health", "read", False, ..., query_health_handler),
    ToolSpec("analyze_records", "read", False, ..., analyze_records_handler),
    ToolSpec("query_calendar", "read", False, ..., query_calendar_handler),
    ToolSpec("recall", "read", False, ..., recall_handler),
    ToolSpec("remember", "write", False, ..., remember_handler),  # Ausnahme s.u.
    ToolSpec("render", "read", False, ..., render_handler),
    ToolSpec("propose_calendar_event", "write", True, ..., propose_calendar_event_handler),
    ToolSpec("delete_calendar_event", "destructive", True, ..., delete_calendar_event_handler),
)
```

Zwei Abweichungen von der ursprünglichen 8er-Liste in `03-agent-design.md`,
beide aus den Dialogen dieser und der vorherigen Session:

- **`search_tools`/`load_tools` entfallen** — es gibt nichts zu durchsuchen,
  alle 8 Tools sind immer geladen (Scope-Entscheidung 1). Das MVP hat damit
  effektiv 8 echte Tools statt der ursprünglichen 6 fachlichen + 2
  Registry-Meta-Tools.
- **`propose_calendar_event`/`delete_calendar_event` statt eines
  generischen "write"-Tools** — spiegeln bewusst 1:1 die bereits gebauten,
  bestätigungspflichtigen Endpunkte aus Phase 3/dieser Session
  (`POST`/`DELETE /api/calendar/events`), kein neuer Schreibpfad.
- **`remember` ist laut Tabelle `write`, aber ohne Bestätigung** — bewusste,
  dokumentierte Ausnahme von der 6.1-Regel "write → Proposal → Bestätigung"
  (Scope-Entscheidung 4 oben). Jedes andere `write`/`destructive`-Tool hält
  sich an die Regel unverändert.

### Risikoklassen-Durchsetzung

Bleibt exakt wie in `03-agent-design.md` Abschnitt 6.1 beschrieben:
serverseitig im Dispatcher, nicht im Prompt. Für `write`/`destructive` (außer
`remember`) gibt der Handler kein Ergebnis zurück, sondern ein
`Proposal`-Objekt; erst ein zweiter, vom Frontend ausgelöster Aufruf mit der
Nutzerbestätigung führt die eigentliche Aktion aus. Für
`propose_calendar_event`/`delete_calendar_event` ist das keine neue
Mechanik — die zugrunde liegenden REST-Endpunkte kennen dieses Muster
bereits (Kalender-Erstellung lief in Phase 3 schon über einen
Vorschlagen-dann-Bestätigen-UI-Flow; das Löschen externer Termine verlangt
seit dieser Session `confirm=true`, s.o.).

### Situation Brief

Wie in `03-agent-design.md` Abschnitt 3 beschrieben — deterministisch aus
der DB gebaut, kein LLM-Call. Datenquellen für die MVP-Version: bestehende
Metrics-Endpunkte (`query_health`-Handler direkt wiederverwendet),
`CalendarEventRepository`, `Goal`-Repository. **Keine Adaptivität in dieser
Phase** (Abschnitt 3, "bei einer reinen Kalenderfrage wird der
Erholungsblock gekürzt") — der Brief hat für die MVP eine feste Form, die
Kürzung nach Intent-Klassifikator ist eine spätere Optimierung.

### `src/kairos/routers/agent.py`

- `POST /api/agent/conversations` — legt eine neue `conversation` an
- `GET /api/agent/conversations` — Verlaufsliste
- `POST /api/agent/conversations/{id}/messages` — Nutzernachricht senden,
  treibt den Orchestrator-Loop an, gibt die vollständige Antwort zurück
  (kein Streaming, s.o.)
- `POST /api/agent/conversations/{id}/confirm` — bestätigt ein offenes
  Proposal (write/destructive)

## Frontend

- **`/chat`** (neue SvelteKit-Route) — Konversationsliste links (falls
  vorhanden), Nachrichtenverlauf + Eingabefeld rechts, gleiche
  `app.css`-Design-Tokens wie jede andere Seite.
  - Assistenten-Nachrichten mit einem `remember`-Aufruf zeigen den
    Hinweis-Chip "📝 Gemerkt: … · Rückgängig" darunter (Scope-Entscheidung 4)
    — Rückgängig ruft `DELETE /api/memory/{id}` auf derselben Seite auf, die
    schon existiert.
  - Ein offenes Proposal (write/destructive) rendert eine Bestätigen/
    Ablehnen-Karte inline im Verlauf statt eines Popups — passt besser in
    einen Chat-Fluss als ein Modal-Dialog.
- Navigation (`+layout.svelte`) bekommt einen Link "Chat" (oder wird der
  neue Standard-Einstieg — offene Detailfrage, siehe unten).

## Nicht verhandelbare Grenzen (aus dieser und der vorherigen Session)

| Grenze | Durchsetzung | Begründung |
|---|---|---|
| Kein `disconnect`-Tool | Kein Disconnect-Endpoint existiert; falls einer gebaut wird, nie als Tool registrieren | Schwer rückgängig (manuelle Neuanmeldung), kein legitimer Anwendungsfall für den Agenten |
| Backfill/Sync nur rate-limitiert | `SyncJobRegistry`-Cooldown am REST-Endpoint, nicht im Dispatcher | Realer Cloudflare-Lockout-Vorfall durch wiederholte Garmin-Logins |
| Fremde Kalendertermine nur mit Bestätigung löschen | `confirm=true` am REST-Endpoint erzwungen | Echte, von Google synchronisierte Termine, nicht Kairos' eigene Vorschläge |
| Kein stilles Gedächtnis-Schreiben | Sichtbarer Chip nach jedem `remember`-Aufruf | Nutzer muss jederzeit sehen können, was gespeichert wurde |
| Keine Diagnosen/Medikation/Kalorienziele ohne Nachfrage | System-Prompt (Abschnitt 6.3 aus `03-agent-design.md`, unverändert übernommen) | Gesundheitsbezogene Leitplanke |

## Testing-Strategie

- Unit-Tests für jeden Tool-Handler isoliert (gleiches Muster wie
  `metrics/formulas/`-Tests) — Risikoklasse und Bestätigungspflicht sind Teil
  der Assertion, nicht nur das Ergebnis.
- Router-Tests für `agent.py` mit gemocktem `litellm.completion` (kein
  echter API-Call in Tests) — Orchestrator-Loop-Logik (Tool-Call → Handler →
  zurück ins Modell) isoliert von der eigentlichen LLM-Antwort.
- Integrationstest: ein `write`-Tool-Aufruf ohne vorherige Bestätigung darf
  nie die zugrunde liegende Aktion ausführen (Regression gegen genau die
  Klasse von Bug, die die Risikoklassen-Regel verhindern soll).
- **Eval-Suite** (13 Referenzfragen, s.o.) gegen einen festen Testdatensatz
  — wie in `03-agent-design.md` Abschnitt 8 beschrieben, Zahlen-Assertions
  per Regex-Extraktion + Vergleich mit dem tatsächlichen Tool-Ergebnis.
  Läuft gegen echte LLM-Calls (kein Mock) — kostet Geld pro Lauf, deshalb
  nicht Teil der normalen CI, sondern ein manuell/gezielt getriggerter
  Abnahme-Lauf.

## Global Constraints (gelten für jeden Task, gleiches Muster wie Phase 3)

- `install_rls_listener(session, user_id)` auf jeder Session, die
  `conversation`/`conversation_message`/`metric_daily_value`/
  `custom_metric_definition` liest oder schreibt.
- `ruff` (line-length 100) + `mypy --strict`, conventional commits.
- Kein LLM-API-Call direkt aus einem Router — immer über
  `src/kairos/agent/orchestrator.py`, damit Risikoklassen-Durchsetzung nicht
  umgangen werden kann.
- Tool-Handler geben nie eine rohe Zeitreihe zurück — Hardcap 2.000 Tokens
  pro Tool-Ergebnis (Abschnitt 4.5 aus `03-agent-design.md`, unverändert).
- Externe Inhalte (sobald Mail/Kalendereinladungen als Tool-Input
  vorkommen) werden als Daten markiert übergeben, nie als Anweisung
  interpretiert (Abschnitt 6.2, unverändert — in dieser Phase noch nicht
  scharf, da noch kein Mail-Tool existiert, aber als Grundsatz hier
  verankert).

## Abnahmekriterien (angepasst aus `08-roadmap.md`)

13 von 15 Referenzfragen (alle außer 13, 15) korrekt beantwortet, Zahlen
stimmen exakt mit dem jeweiligen Tool-Ergebnis überein. Median-Input <
15.000 Tokens pro Turn. Jeder `write`/`destructive`-Tool-Aufruf (außer
`remember`) durchläuft nachweislich eine Bestätigung, bevor die Aktion
tatsächlich ausgeführt wird.

## Nötige Doku-Korrekturen (Folgearbeit, nicht Teil des Plans selbst)

- `docs/00-vision-und-scope.md` Zeile ~129: "LLM-Zugang: API-basiert
  (Anthropic Claude)" → "LLM-Zugang: pluggable über litellm, beliebiger
  API-Key pro Nutzer".
- `docs/08-roadmap.md` Phase 4: Abnahme "15/15" → "13/13 (Referenzfragen 13
  und 15 verschoben nach Phase 5)".
- `docs/08-roadmap.md` Phase 5: Abnahme "Referenzfrage 8 und 14" →
  "Referenzfrage 13 und 15" (die aktuelle Nennung von 8/14 ist nach der
  Analyse in dieser Spec falsch — 8 und 14 sind mit dem Phase-4-MVP-Tool-Satz
  beantwortbar, s.o.).

## Offene Detailfragen (noch nicht entschieden, vor der Task-Planung zu klären)

1. Wird `/chat` der neue Standard-Einstieg (Startseite) oder bleibt das
   Dashboard (`/`) die Startseite und Chat ist ein zusätzlicher Nav-Punkt?
2. Konversationsverlauf: eine dauerhafte Liste mehrerer Konversationen
   (wie bei Claude/ChatGPT) oder eine einzige fortlaufende Konversation pro
   Nutzer (einfacher, passt evtl. besser zum "1 Nutzer redet mit seinem
   Assistenten"-Charakter dieses Projekts)?
3. Welches Modell ist der Default für `user_setting.llm_model`, bevor ein
   Nutzer selbst etwas einstellt?
