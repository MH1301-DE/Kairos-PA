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
   (Kennzahlen, Statistiken, Auffälligkeiten). Rohe Listen von 3.300 Werten landen
   nie im Kontext; Visualisierungen gehen über `render` und liefern nur eine
   Referenz-ID. Der Zugang zu Zeitreihendaten ist tool-vermittelt, nicht gesperrt.
3. **Kontext ist ein Budget, kein Fass.** Jede Komponente hat ein Limit und hält es.

## 2. Kontextbudget

Zielwert: **Median-Input < 15.000 Tokens pro Turn**, Hardcap 40.000.

| Block | Budget | Herkunft | Cachebar |
|---|---:|---|---|
| System-Prompt (Persona, Policies, Rechenverbot) | 1.500 | statisch | ✅ |
| Core-Tools (8 Stück, immer geladen) | 1.600 | statisch | ✅ |
| Nutzerprofil (Ziele, Verletzungen, Präferenzen) | 400 | DB, ändert sich selten | ✅ |
| **Situation Brief** | 700 | DB, pro Turn generiert | ❌ |
| Abgerufene Memories | 400 | pgvector | ❌ |
| Dynamisch geladene Tools (0–6) | 0–1.200 | Registry | teilweise |
| Konversationshistorie (komprimiert) | 4.000 | Rolling Summary | teilweise |
| Tool-Ergebnisse dieses Turns | 3.000–5.000 | Tools | ❌ |
| **Summe (typisch)** | **≈ 12.000–15.000** | | ~25 % cachebar |

Die ersten drei Blöcke (≈ 3.500 Tokens) sind über eine Session hinweg identisch und
werden über **Prompt-Caching** abgewickelt. Das ist der wirksamste einzelne
Kostenhebel ([07 — Kosten](07-deployment-und-betrieb.md#kosten)).

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

**Adaptiv:** Bei einer reinen Kalenderfrage wird der Erholungsblock auf zwei Zeilen
gekürzt und umgekehrt. Die Auswahl trifft ein billiger Intent-Klassifikator
(Embedding-Nearest-Domain, kein LLM-Call).

## 4. Tool-Architektur

### 4.1 Das Problem

Realistisch entstehen 60–90 Tools (Garmin ~20, Kalender ~15, Planung ~12,
Analyse ~15, Memory/Admin ~10, Mail ~8 optional, plus je Erweiterung mehr). Vollständig geladen sind
das **8.000–12.000 Tokens pro Turn** — dauerhaft, für alle Anfragen, egal ob
relevant. Zusätzlich sinkt die Auswahlgenauigkeit des Modells messbar, je mehr
ähnliche Tools nebeneinander stehen.

### 4.2 Die Lösung: zweistufige Tool-Ladung

**Stufe 1 — Core-Tools (immer im Kontext, 8 Stück, ~1.600 Tokens):**

| Tool | Zweck |
|---|---|
| `search_tools` | Findet Tools nach Aufgabenbeschreibung |
| `load_tools` | Lädt vollständige Schemas in den Kontext |
| `query_health` | Abfrage der Derived-Zone (Metrik, Zeitraum, Aggregat) |
| `analyze_records` | Serverseitige Analyse über Canonical-Zeitreihen (Aktivitäts- oder Wellness-Window); gibt Statistiken + Auffälligkeiten zurück, keine Rohliste |
| `query_calendar` | Termine/freie Blöcke in einem Zeitraum |
| `recall` | Semantische Suche im Nutzergedächtnis |
| `remember` | Fakt ins Nutzergedächtnis schreiben |
| `render` | Chart/Tabelle/Karte im UI erzeugen (gibt Spec zurück, keine Daten) |

Diese acht decken erfahrungsgemäß den Großteil der Alltagsanfragen ab.
`query_health`, `analyze_records` und `query_calendar` sind bewusst **breit
parametrisiert**, statt in 20 Spezialtools zerlegt zu werden — das ist der
billigste Weg, die Tool-Anzahl zu senken.

`analyze_records` ist der kontrollierte Zugang zu Zeitreihendaten: Der Agent
spezifiziert Fenster, Metriken und gewünschte Statistiken; der Server führt die
Analyse aus und gibt ein bounded Ergebnis zurück (Hard-Cap: 2.000 Tokens).
Das verhindert rohe Zahlenlisten im Kontext, ohne Zeitreihenanalyse zu verbieten.

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

### 4.3 Ablauf

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

### 4.4 Optimierungen gegen die Zusatz-Roundtrips

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

### 4.5 Tool-Ausgabekontrakt

**Jedes** Tool gibt dieselbe Hülle zurück:

```json
{
  "summary": "5 Läufe in KW30, gesamt 42,1 km, ⌀-Puls 148.",
  "data":     { "...": "strukturiert, begrenzt" },
  "meta": {
    "row_count": 5,
    "truncated": false,
    "coverage":  "5/7 Tage mit Daten",
    "as_of":     "2026-07-28T07:02:00Z",
    "cursor":    null
  }
}
```

Erzwungene Regeln:

- **Hardcap 2.000 Tokens pro Tool-Ergebnis.** Darüber wird gekürzt und
  `truncated: true` gesetzt. Der Agent muss dann bewusst nachladen.
- **`summary` ist Pflicht** und wird serverseitig erzeugt. Bei stark gekürzten
  Ergebnissen ist `summary` oft die einzige Information, die der Agent braucht.
- **`detail_level`-Parameter** (`summary | normal | full`) an jedem lesenden Tool.
  Default ist `normal`.
- **Keine Zeitreihen als Zahlenlisten.** Wer eine Kurve will, ruft `render` auf; das
  Tool schreibt die Daten in ein Chart-Objekt und gibt dem Agenten nur eine
  Referenz-ID plus Kennzahlen zurück.

## 5. Gedächtnis

Drei getrennte Speicher — bewusst nicht ein einziger "Memory-Blob":

| Typ | Inhalt | Größe | Injektion |
|---|---|---|---|
| **Profil** | Alter, Größe, HF-Zonen, Ziele, Präferenzen, Verletzungen | ~400 Tok | immer |
| **Semantisch** | Kuratierte Fakten ("trainiert ungern vor 7 Uhr", "hat Ruderergo") | je ~20 Tok | Top-5 via Embedding |
| **Episodisch** | Zusammenfassungen abgeschlossener Konversationen | je ~80 Tok | Top-3 via Embedding |

**Schreibpfad:** Explizit über `remember()` — oder automatisch durch einen
nächtlichen Extraktionsjob, der Konversationen auf dauerhaft relevante Fakten
prüft. Automatisch extrahierte Fakten landen im Status `proposed` und werden dem
Nutzer im Dashboard zur Bestätigung angeboten. **Kein stilles Lernen** — der Nutzer
muss jederzeit einsehen und löschen können, was das System über ihn zu wissen glaubt.

**Konversationshistorie:** Rolling Compaction. Die letzten 6 Nachrichten wörtlich,
alles davor als fortgeschriebene Zusammenfassung (max. 400 Tokens). Tool-Ergebnisse
älterer Turns werden auf ihr `summary`-Feld reduziert — das allein spart in langen
Sessions den Großteil des Kontexts.

## 6. Schreibvorgänge und Sicherheit

### 6.1 Risikoklassen

| Klasse | Beispiele | Verhalten |
|---|---|---|
| `read` | Abfragen, Analysen | direkt ausführen |
| `write` | Termin anlegen, Plan speichern, Memory schreiben | **Proposal → Bestätigung** |
| `destructive` | Termin löschen, Plan verwerfen, Verbindung trennen | Proposal + explizite Bestätigung, kein "ja" per Chat ausreichend |

Die Klasse steht in der Registry, nicht im Prompt. Die Durchsetzung erfolgt
**serverseitig im Tool-Dispatcher** — ein Agent, der versucht, ein `write`-Tool
direkt auszuführen, bekommt ein Proposal-Objekt zurück, ganz gleich was im Prompt
steht. Prompt-basierte Regeln sind hier keine Sicherheitsmaßnahme.

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

- **Referenzfragen-Suite** (die 15 Fragen aus [00](00-vision-und-scope.md)) gegen
  einen fixen Testdatensatz, automatisiert bei jedem Prompt- oder Tool-Change.
- **Assertions:** genannte Zahlen müssen exakt mit dem Tool-Ergebnis übereinstimmen
  (Regex-Extraktion + Vergleich). Das fängt Halluzinationen zuverlässig.
- **Tool-Selection-Accuracy:** Wurde das erwartete Tool gewählt?
- **Token-Telemetrie:** Input-Tokens pro Turn als Zeitreihe. Steigt der Median über
  20k, ist etwas kaputt.
