# 03 — Agent-Design

Dieses Dokument behandelt die zweite explizit gestellte Kernfrage: **Wie wird der
Agent effizient und effektiv eingebunden, ohne seinen Kontext vollzupumpen?**

## 1. Grundhaltung

Der Agent ist **Interface und Interpret, nicht Rechenwerk und nicht Datenspeicher.**

Drei Regeln folgen daraus:

1. **Zahlen kommen aus Tools, nie aus dem Modell.** Wenn der Agent eine Zahl nennt,
   die nicht in einem Tool-Ergebnis dieses Turns steht, ist das ein Bug.
2. **Zeitreihen fließen nie als roher Zahlenstrom in den Kontext.** Für Analysen
   über Zeitfenster ruft der Agent ein `analyze_records`-Tool auf — der Server
   rechnet serverseitig und gibt ein strukturiertes, bounded Ergebnis zurück
   (Tageswerte aus der Derived-Zone, max. 60, plus Mittelwert/Min/Max). Rohe Listen
   von 3.300 Werten landen nie im Kontext; Visualisierungen gehen über `render`, das
   eine validierte Chart-Spec an das UI liefert. Der Zugang zu Zeitreihendaten ist
   tool-vermittelt, nicht gesperrt.
3. **Kontext ist ein Budget, kein Fass.** Jede Komponente hat ein Limit und hält es.

## 2. Kontextbudget

Zielwert: **Median-Input < 15.000 Tokens pro Turn**, Hardcap 40.000.

| Block | Budget (Ist) | Herkunft | Cachebar |
|---|---:|---|---|
| System-Prompt: Persona + Gesundheitsregeln | gemessen 163 | statisch (`prompt.py`) | ✅ |
| Kennzahlen-Katalog (`VERFÜGBARE KENNZAHLEN`) | gemessen 469 | statisch (`metric_catalog.py`) | ✅ |
| Core-Tools (12 Stück, immer geladen — siehe 4.2) | **gemessen 1.461** (5.346 Zeichen) | statisch | ✅ |
| Erinnerungen (`agent_memory`, aktive Einträge) | ≤ ~1.500 | DB | ❌ |
| **Situation Brief** | ~700 | DB, pro Turn generiert | ❌ |
| Konversationshistorie | ≤ 12.000 (geschätzt, Schnitt an Turn-Grenzen) | DB | teilweise |
| Tool-Ergebnisse dieses Turns | 3.000–5.000 | Tools | ❌ |

Gemessen mit dem `o200k`-Tokenizer; beim konfigurierten Modell weicht die Zahl leicht
ab. Ein eigener Block „Nutzerprofil“ existiert nicht — Ziele stehen im Lagebild,
Präferenzen in den Erinnerungen.

Nach der [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) wächst der Tool-Satz auf 26 Tools,
geschätzt **4.000–4.500 Tokens** für die Schemas.

**Token-Telemetrie fehlt bisher:** Das `usage`-Objekt von litellm wird weder geloggt
noch gespeichert; der Median-Input ist deshalb nicht gemessen (geplant: Spec G.4).

**Prompt-Caching ist nicht konfiguriert** (kein `cache_control` in `llm_client.py`).
Persona, Katalog und Tool-Schemas (≈ 2.100 Tokens) sind statisch und wären der
naheliegende Cache-Präfix — der wirksamste einzelne Kostenhebel
([07 — Kosten](07-deployment-und-betrieb.md#6-kosten)).

## 3. Der Situation Brief

Statt den Agenten drei Tool-Calls machen zu lassen, um überhaupt zu wissen, wo er
steht, wird ein kompakter Zustandsblock **deterministisch aus der DB gebaut** und
jedem Turn vorangestellt.

```
AKTUELLE LAGE  ·  Max  ·  Di, 28.07.2026, 09:14 (Europe/Berlin)

Datenstand:  Garmin ✓ 07:02 · Google Cal ✓ 09:11 · Apple Cal ⚠ 14 h alt

Erholung:    HRV 62 ms (Baseline 68 ± 7 → unterhalb, 3. Tag in Folge)
             Ruhepuls 48 (7-Tage-⌀ 46, ↑)
             Schlaf 6 h 12 m (Soll 7 h 30 m, Defizit 4 h 40 m/Woche)
             Body Battery bei Aufwachen: 61

Belastung:   CTL 54 · ATL 71 · TSB −17 (ermüdet)
             Letzte 7 Tage: 5 Einheiten, 6 h 20 m, TRIMP 412
             Letzte harte Einheit: gestern, Intervalle 8×400 m

Kalender:    Heute 3 Termine, erster 10:00, letzter endet 18:30
             Freie Blöcke ≥ 60 min: 12:00–13:30, ab 18:30
             Morgen: ganztägig frei

Aktive Ziele: Halbmarathon 11.10.2026 · 45 min/Tag Lernzeit
Hinweise:     Achillessehnenreizung links (seit 03.07., aktiv)
```

Kosten: ~700 Tokens. Ersetzt typischerweise 4–6 Tool-Calls und damit 2–3
LLM-Roundtrips. Der Brief ist **die wichtigste Einzelmaßnahme für Latenz und
Kosten** zugleich.

**Ist:** `build_situation_brief()` (`src/kairos/agent/situation_brief.py`) baut den
Brief immer in voller Form (Datenstand, Erholung, Belastung, Kalender, Ziele); eine
Kalenderquelle „Apple“ gibt es nicht.

*Zielbild (nicht umgesetzt):* adaptiv — bei einer reinen Kalenderfrage wird der
Erholungsblock auf zwei Zeilen gekürzt und umgekehrt; die Auswahl trifft ein billiger
Intent-Klassifikator (Embedding-Nearest-Domain, kein LLM-Call). Geplant ist außerdem
eine Zeile zur letzten Aktivität mit ID (Spec G.5).

## 4. Tool-Architektur

### 4.1 Das Problem

Realistisch entstehen 60–90 Tools (Garmin ~20, Kalender ~15, Planung ~12,
Analyse ~15, Memory/Admin ~10, Mail ~8 optional, plus je Erweiterung mehr). Vollständig geladen sind
das **8.000–12.000 Tokens pro Turn** — dauerhaft, für alle Anfragen, egal ob
relevant. Zusätzlich sinkt die Auswahlgenauigkeit des Modells messbar, je mehr
ähnliche Tools nebeneinander stehen.

### 4.2 Ist-Stand: statisches Core-Tool-Set

Alle Tools sind als `ToolSpec` in `CORE_TOOLS` (`src/kairos/agent/tools.py`)
definiert und werden **bei jedem Turn vollständig** an das Modell übergeben. Es
gibt keine Registry-Tabelle und kein Nachladen; Risikoklasse und
Bestätigungspflicht stehen direkt im `ToolSpec`.

| Tool | Zweck | Klasse | Ausführung |
|---|---|---|---|
| `query_health` | Wert einer Kennzahl an einem Tag (`metric_id`, optional `variant`, `as_of`, Default heute) | `read` | direkt |
| `analyze_records` | Tages-Zeitreihe einer Kennzahl aus `metric_daily_value` über `window_days` (Default 28, max. 60) mit Mittelwert/Min/Max; nur für Kennzahlen mit Zeitreihe | `read` | direkt |
| `query_calendar` | Termine zwischen `from_date` und `to_date`; mit `duration_minutes` zusätzlich freie Blöcke dieser Mindestlänge | `read` | direkt |
| `recall` | Aktive (nicht abgelaufene) Gedächtnis-Einträge; mit `query` als Substring-Filter, ohne `query` die neuesten | `read` | direkt |
| `remember` | Fakt ins Nutzergedächtnis schreiben, optional mit `expires_at` für zeitlich begrenzte Fakten | `write` | **direkt** (Ausnahme, Undo-Chip im UI statt Vorab-Bestätigung) |
| `render` | Validiert eine Chart-Spec (`TimeSeriesChart`, `BarChart`, `Gauge`, `StatCard`, `Table`) und gibt sie ans UI; holt selbst keine Daten | `read` | direkt |
| `propose_calendar_event` | Termin in Google Calendar anlegen (`summary`, `start_at`, `end_at`, `description`) | `write` | Proposal → Bestätigung |
| `delete_calendar_event` | Termin löschen (`event_id`); externe, nicht von Kairos angelegte Termine brauchen zusätzlich `confirm: true` | `destructive` | Proposal → Bestätigung |
| `plan_propose` | Trainingsplan-Entwurf für `weeks` Wochen aus freier Kalenderzeit und aktueller Belastung, optional bis `goal_date` | `read` | direkt (speichert nur einen Entwurf) |
| `plan_commit` | Plan-Entwurf (`plan_id`) als Termine in den Kalender übertragen | `write` | Proposal → Bestätigung |
| `plan_adjust` | Ziel-TRIMP künftiger geplanter Blöcke eines Plans reduzieren (`plan_id`, `reason`); bereits angelegte Kalendertermine werden nicht umbenannt | `write` | Proposal → Bestätigung |
| `plan_progress` | Soll/Ist-TRIMP-Vergleich des aktiven (oder angegebenen) Plans für die laufende Woche | `read` | direkt |

`query_health`, `analyze_records` und `query_calendar` sind bewusst **breit
parametrisiert**, statt in 20 Spezialtools zerlegt zu werden — das ist der
billigste Weg, die Tool-Anzahl zu senken.

`analyze_records` ist der kontrollierte Zugang zu Zeitreihendaten: Der Server
liest die vorberechneten Tageswerte und gibt höchstens 60 Werte plus Statistik
zurück. Das verhindert rohe Zahlenlisten im Kontext, ohne Zeitreihenanalyse zu
verbieten.

#### Geplante Erweiterung: 26 Tools ([Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) §11)

Nicht umgesetzt. Geändert werden:

| Tool | Änderung |
|---|---|
| `render` | `TimeSeriesChart` bekommt `y_format: "pace"` (Achse m:ss, Daten in s/km) |
| `plan_propose` | jeder Block außer Ruhetagen bekommt eine Workout-Struktur (Platzhalter-Templates, Spec E.2) |
| `plan_commit` | legt je Block ein Garmin-Workout an, terminiert es und trägt einen Google-Termin ein |
| `plan_adjust` | skaliert zusätzlich Workout und Termin |

Neu hinzu kommen 14 Tools:

| Tool | Zweck | Klasse | Ausführung |
|---|---|---|---|
| `activity_search` | Aktivitäten nach Zeitraum, Sportprofil, Distanz finden | `read` | direkt (nur DB) |
| `activity_get` | Steckbrief einer Aktivität (ohne ID: die letzte) | `read` | direkt (nur DB) |
| `activity_splits` | Split-Tabelle, eine Zeile je km bzw. Uhr-Runde | `read` | direkt (nur DB) |
| `activity_analyze` | Analysen, u. a. Vergleich zweier Aktivitäten | `read` | direkt (nur DB) |
| `best_efforts` | Lauf-Bestleistungen 800 m bis 100 km | `read` | direkt (nur DB) |
| `workout_list` | Garmin-Workouts auflisten | `read` | direkt (Spiegel, höchstens alle 5 min aufgefrischt) |
| `workout_get` | ein Garmin-Workout mit Schritten | `read` | direkt (Spiegel) |
| `workout_create` | strukturiertes Workout in Garmin anlegen, optional terminieren | `write` | Bestätigung |
| `workout_update` | Workout ändern (ID und Termine bleiben) | `write` | Bestätigung |
| `workout_schedule` | Workout terminieren, plus Google-Termin | `write` | Bestätigung |
| `workout_unschedule` | Termin(e) entfernen, einzeln oder gesammelt | `destructive` | Bestätigung |
| `workout_delete` | Workouts löschen, einzeln, gesammelt oder alle | `destructive` | Bestätigung |
| `activity_update` | Aktivität in Garmin umbenennen / Beschreibung ändern | `write` | Bestätigung |
| `activity_delete` | Aktivität in Garmin löschen | `destructive` | Bestätigung |

### 4.3 Geplant (nicht umgesetzt): zweistufige Tool-Ladung

> **Status:** Konzept. `search_tools`, `load_tools` und `tool_registry` existieren
> im Code nicht. Relevant wird das erst, wenn das Tool-Set deutlich über die
> heutigen 12 wächst.
>
> **Schwelle:** Zweistufiges Laden wird eingeführt, sobald es **mehr als 30 Tools**
> oder **mehr als 6.000 Schema-Tokens** sind. Die geplanten 26 Tools (≈ 4.000–4.500
> Tokens) liegen darunter. Ein CI-Test soll bei mehr als 18.000 Zeichen
> Schema-Summe fehlschlagen (Spec G.3).

**Stufe 1 — Core-Tools** (immer im Kontext) wie in 4.2, ergänzt um
`search_tools` (findet Tools nach Aufgabenbeschreibung) und `load_tools` (lädt
vollständige Schemas in den Kontext).

**Stufe 2 — Registry (nicht im Kontext):**

```sql
tool_registry(
  tool_id, name, pack, version,
  one_liner,          -- 1 Satz, ~15 Tokens  → Rückgabe von search_tools
  when_to_use,        -- 2 Sätze             → Rückgabe von search_tools
  json_schema,        -- vollständig         → nur bei load_tools
  embedding vector,   -- über one_liner + when_to_use
  risk_class,         -- read | write | destructive
  requires_confirmation bool,
  enabled
)
```

**Ablauf (Zielbild):**

```
Nutzer: "Zieh mir mal die Rohdaten meines Laufs von gestern und vergleich die
         Kadenz mit dem letzten Tempolauf."

┌─ Turn 1 ────────────────────────────────────────────────────────────
│ Agent: search_tools(query="Aktivitätsdetails Kadenz vergleichen", k=5)
│ ← [
│     {id:"activity.get_records",  one_liner:"Sekundendaten einer Aktivität"},
│     {id:"activity.compare",      one_liner:"Zwei Aktivitäten kennzahlenweise vergleichen"},
│     {id:"activity.search",       one_liner:"Aktivitäten nach Typ/Zeitraum finden"},
│     ...
│   ]                                                    ≈ 180 Tokens
├─ Turn 2 ────────────────────────────────────────────────────────────
│ Agent: load_tools(["activity.search","activity.compare"])
│ ← Vollständige Schemas                                 ≈ 400 Tokens
├─ Turn 3 ────────────────────────────────────────────────────────────
│ Agent: activity.search(...) → activity.compare(...)
│ ← Kennzahlen-Vergleich, kein Rohdatenstrom             ≈ 350 Tokens
└─ Antwort
```

Kosten dieses Pfades: ~930 Tokens statt ~10.000 für ein vollständiges Tool-Set.
Preis: ein bis zwei zusätzliche LLM-Roundtrips (~1,5 s).

**Optimierungen gegen die Zusatz-Roundtrips (Zielbild):**

Der Suchpfad kostet Latenz. Vier Maßnahmen dämpfen das:

1. **Pack-Prewarming.** Ein Embedding der Nutzernachricht wird gegen
   Pack-Beschreibungen gematcht. Liegt die Ähnlichkeit über Schwellwert, wird das
   Pack (3–6 Tools) direkt vorgeladen — ohne `search_tools`-Roundtrip.
2. **Sticky Loading.** Einmal geladene Tools bleiben für die Session geladen, bis
   ein LRU-Limit (Default 8 Tools) greift.
3. **Nutzungsstatistik.** `tool_registry.usage_count` pro Nutzer; die Top-3 eines
   Nutzers werden dauerhaft in Stufe 1 aufgenommen. Nach einigen Wochen ist der
   Suchpfad für den Alltag praktisch nicht mehr nötig.
4. **`search_tools` gibt Ergebnisse direkt zurück, wenn eindeutig.** Bei einem
   Treffer mit Ähnlichkeit > 0,9 wird das vollständige Schema sofort mitgeliefert
   und `load_tools` entfällt.

### 4.4 Tool-Ausgabekontrakt

**Jedes** Tool gibt dieselbe Hülle zurück (`_envelope` in `tools.py`):

```json
{
  "summary": "5 Läufe in KW30, gesamt 42,1 km, ⌀-Puls 148.",
  "data":     { "...": "strukturiert, begrenzt" },
  "meta": {
    "row_count": 5,
    "truncated": false,
    "coverage":  "5/7 Tage mit Daten",
    "as_of":     "2026-07-28T07:02:00Z"
  }
}
```

`row_count` ist nur gesetzt, wenn `data` eine Liste ist, sonst `null`.

Umgesetzte Regeln:

- **`summary` ist Pflicht** und wird serverseitig erzeugt.
- **Begrenzung pro Tool statt globalem Cap.** `analyze_records` liefert max. 60
  Tageswerte, `render` begrenzt Punkte/Balken/Zeilen im Schema
  (`src/kairos/agent/render_schemas.py`).
- **`render` holt keine Daten selbst.** Der Agent übergibt Zahlen aus einem
  vorherigen Tool-Ergebnis; der Server validiert die Spec und streamt sie als
  `render`-Event ans UI.

Geplant, nicht umgesetzt ([Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) C.0 und G.2):

- **`meta.truncated` wird tatsächlich gesetzt** (das Feld existiert, ist heute aber
  immer `false`). Obergrenzen gelten je Tool und kürzen deterministisch; ein globaler
  Token-Hardcap ist nicht vorgesehen.
- **Tabellen spaltenförmig** (`cols` / `rows`) statt einer Liste von Objekten.
- **Formatierte Werte:** Pace, Dauer, Distanz, Datum und Differenzen formatiert der
  Server zentral (`agent/format.py`); das Modell rechnet nicht.
- **Neue `meta`-Felder:** `next` (Hinweis bzw. Fortsetzung zum Nachladen) und
  `quality` (Datenqualität der Grundlage).
- *Weiterhin nur Idee:* `detail_level`-Parameter (`summary | normal | full`).

## 5. Gedächtnis

**Ist-Stand (Agent-Harness v2):** ein Speicher, die Tabelle `agent_memory`.

| Aspekt | Umsetzung |
|---|---|
| Inhalt | kurze Fakten in Textform, optional mit `expires_at` (NULL = dauerhaft) |
| Injektion | aktive Einträge, neueste zuerst, als Block `ERINNERUNGEN` im Systemprompt (Budget 1.500 geschätzte Tokens, `render_memory_block` in `prompt.py`); Einträge, die nicht mehr ins Budget passen, werden still ausgelassen und sind nur noch über `recall` erreichbar |
| Ablauf | abgelaufene Einträge werden beim Aufbau des Systemprompts gelöscht (`delete_expired`) |
| Abruf per Tool | `recall` filtert per **Substring**, keine Embeddings |
| Schreiben, explizit | `remember()` — sofort gespeichert (`source='agent'`), im UI mit Undo-Chip |
| Schreiben, automatisch | beim Kompaktieren der Historie: Turns, die aus dem Token-Fenster fallen, werden **nach** einer abschließenden Antwort per LLM auf dauerhafte Fakten geprüft (nicht nach einem Proposal oder Fehler; nur Fakten aus Nutzerzeilen; Transkript ≤ 24.000 Zeichen, `memory_extraction.py`). Neue Einträge gehen als `memory`-Event an den Chat und werden wie `remember()` mit `source='agent'` gespeichert |
| Einsehen/Bearbeiten | Seite „Gedächtnis“ im Frontend (`/api/memory`: anlegen, bearbeiten, löschen); dort angelegte Einträge haben `source='user'` |

**Konversationshistorie:** token-budgetiert auf 12.000 geschätzte Tokens
(Zeichen / 4), geschnitten nur an Turn-Grenzen; der neueste Turn bleibt immer
erhalten, auch wenn er allein das Budget sprengt (`history.py`). Tool-Ergebnisse
werden **vollständig** wiedergegeben, nicht auf ihr `summary` gekürzt.
`conversation.compacted_through_seq` markiert den extrahierten Stand: Nachrichten bis
dahin werden gar nicht mehr geladen. Der Wert wird nur nach erfolgreicher Extraktion
fortgeschrieben; schlägt sie fehl, bleibt er stehen und der nächste Turn versucht es
erneut. Eine fortgeschriebene Zusammenfassung gibt es nicht.

*Zielbild (nicht umgesetzt):* getrennte Speicher für Profil, semantische Fakten und
episodische Zusammenfassungen mit Abruf per Embedding (Top-5 / Top-3); ein
nächtlicher Extraktionsjob; automatisch extrahierte Fakten im Status `proposed`, die
der Nutzer erst bestätigt. Heute werden automatisch extrahierte Fakten direkt aktiv —
sie sind aber jederzeit auf der Gedächtnis-Seite sicht- und löschbar.

## 6. Schreibvorgänge und Sicherheit

### 6.1 Risikoklassen

| Klasse | Beispiele | Verhalten |
|---|---|---|
| `read` | Abfragen, Analysen | direkt ausführen |
| `write` | Termin anlegen, Plan in den Kalender übertragen, Plan anpassen (`remember` als Ausnahme, s. u.) | **Proposal → Bestätigung** per Klick im UI (Confirm-Endpoint); ein „ja“ im Chat bestätigt nichts |
| `destructive` | Termin löschen | wie `write`: Proposal → ein Klick auf Bestätigen; beim Löschen **externer** Termine zusätzlich `confirm: true` |

Die Klasse steht im `ToolSpec` (`risk_class`), nicht im Prompt; die Zuordnung je
Tool zeigt die Tabelle in 4.2. Die Durchsetzung erfolgt **serverseitig im
Tool-Dispatcher** (`src/kairos/agent/dispatcher.py`) — ein Agent, der versucht, ein
`write`- oder `destructive`-Tool direkt auszuführen, bekommt ein Proposal-Objekt
zurück, ganz gleich was im Prompt steht. Ausgeführt wird erst über
`POST /api/agent/conversations/{id}/proposals/{tool_call_id}/confirm`. Prompt-basierte Regeln sind hier keine
Sicherheitsmaßnahme.

Abweichungen vom Schema oben, so wie der Code es heute umsetzt:

- **`remember`** ist `write`, läuft aber sofort (`needs_confirmation()` nimmt es
  namentlich aus); das UI zeigt stattdessen einen Undo-Chip.
- **`destructive`** nutzt denselben Bestätigungsweg wie `write`. Die zusätzliche
  Hürde gibt es nur beim Löschen *externer* Termine: Dort verlangt
  `_delete_calendar_event` außerdem `confirm: true`.
- „Plan verwerfen“ und „Verbindung trennen“ sind keine Agent-Tools.

**Geplant ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) G.1): Vorschau-Snapshots.** Heute bestätigt der Nutzer die
rohen Modell-Argumente. Künftig erzeugt ein bestätigungspflichtiges Tool vorab eine
**Vorschau** (`preview`), die in `proposal_snapshot` gespeichert wird: `card` (was
der Nutzer sieht) und `resolved_args` (was ausgeführt wird). Ausgeführt wird nur mit
`resolved_args` — „lösche alle“ wird also bei der Vorschau aufgelöst und kann bei der
Ausführung nicht mehr umfassen. Eine Zustandsmaschine (`pending → executing → done |
rejected | expired`) ersetzt die heutige `FOR UPDATE`-Sperre; veraltete Vorschläge
(> 30 min) werden mit `proposal_stale` abgelehnt, Abstürze zwischen Start und Ende
sind wiederaufnehmbar.

**Massenoperationen:** `workout_delete`, `workout_unschedule` und `activity_delete`
verarbeiten mehrere Elemente in **einer** Bestätigung; die Vorschau nennt Anzahl und
Elemente, der Fortschritt kommt per SSE-Event `tool_progress`.

### 6.2 Prompt Injection

Inhalte aus Gmail, Kalendereinladungen und Aktivitätsnotizen sind **fremdkontrolliert**.
Maßnahmen:

- Externe Inhalte werden immer in einer Umhüllung übergeben, die sie als Daten
  markiert, und im System-Prompt wird explizit festgehalten, dass darin enthaltene
  Anweisungen nicht befolgt werden.
- Tools, die externe Inhalte liefern, sind `read`; sie können nichts auslösen.
- Jeder Schreibvorgang braucht ohnehin menschliche Bestätigung — das ist die
  eigentliche Absicherung.
- Mail-Inhalte werden vor Übergabe auf Nutztext reduziert (kein HTML, keine Links
  als klickbare Anweisung).

### 6.3 Gesundheitsbezogene Leitplanken

Im System-Prompt fest verankert:

- Keine Diagnosen, keine Aussagen über Krankheitsursachen, keine Medikation.
- Bei auffälligen Mustern (z. B. Ruhepuls > 15 % über Baseline über mehrere Tage,
  SpO₂-Auffälligkeiten): sachlicher Hinweis auf den Befund plus Empfehlung
  ärztlicher Abklärung — ohne eigene Deutung.
- Keine Empfehlungen zu Gewichtsreduktion, Kalorienzielen oder Nüchterntraining
  ohne ausdrückliche Nachfrage, und dann konservativ.
- Bei Anzeichen für Übertraining oder gestörtes Verhältnis zu Training/Essen wird
  die Belastungsempfehlung nach unten korrigiert, nicht nach oben.

## 7. Proaktivität

> **Zielbild (nicht umgesetzt).** Es gibt keinen Insight-Job, keinen Scheduler und
> kein Web Push. Der Agent antwortet heute nur auf Anfragen.

Der Agent wird nicht nur gefragt, er meldet sich — aber kontrolliert:

- Ein nächtlicher **Insight-Job** wertet die Derived-Zone regelbasiert aus
  (Schwellwerte, Trendbrüche, Zielabweichungen). Das ist deterministisch, kein LLM.
- Nur wenn eine Regel feuert, wird ein LLM-Call ausgelöst, der die Beobachtung
  formuliert.
- Maximal **eine** Push-Meldung pro Nutzer und Tag, konfigurierbar bis "nie".
- Jede Meldung enthält die auslösende Kennzahl, damit sie nachvollziehbar ist.

Das verhindert den häufigsten Fehlschlag solcher Systeme: Der Assistent wird
gesprächig, der Nutzer schaltet ihn stumm.

## 8. Evaluierung

Ohne Messung driftet Agentenverhalten unbemerkt. Deshalb ab V1:

- **Referenzfragen-Suite** (`scripts/agent_eval_suite.py`): **16 Fälle** — die 15
  Fragen aus [00](00-vision-und-scope.md) plus ein Mehrschritt-Fall (Vorschlag →
  Bestätigen → Folgefrage), mit echten Seed-Daten. **Live-Stand 2026-10-06: 15/16**
  Tool-Accuracy; Frage 7 (beste 5-km-Zeit) ist mangels Aktivitäts-Tool nicht
  beantwortbar, Frage 10 nur eingeschränkt. Die Suite läuft manuell, nicht in CI.
- **Geplant:** Fälle 17–26 aus der [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) §12.1
  (Aktivitäts-Fragen, Workouts, Plan → Garmin); die Schreibfälle laufen gegen
  Fake-Clients.
- **Assertions:** genannte Zahlen müssen exakt mit dem Tool-Ergebnis übereinstimmen
  (Regex-Extraktion + Vergleich). Das fängt Halluzinationen zuverlässig.
- **Tool-Selection-Accuracy:** Wurde das erwartete Tool gewählt?
- **Token-Telemetrie — fehlt noch.** Ziel: Input-Tokens pro Turn als Zeitreihe;
  steigt der Median über 20k, ist etwas kaputt. Heute wird `usage` nicht erfasst
  (geplant: Spec G.4). Die Eval-Suite misst bereits TTFT und Gesamtzeit (Median 10,2 s
  bzw. 20 s, 2026-10-06).
