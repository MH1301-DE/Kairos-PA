# Agent-Harness v2 — Design

**Stand:** 2026-10-05 · **Basis:** Phase-4-MVP (`2026-09-12-phase-4-agent-mvp-design.md`) +
erste Live-Eval (14/15 Tool-Selection, aber 0 echte Daten, 6–21 s bis zur ersten Ausgabe).

## Ziele

1. Das Modell kennt die verfügbaren Kennzahlen und Tools, statt Metrik-IDs zu raten.
2. Vorschläge (Proposals) hinterlassen eine gültige Konversations-Historie.
3. Kaputte Tool-Argumente brechen keinen Turn mehr ab.
4. Kontext ist budgetiert; was aus dem Fenster fällt, wird vorher als Erinnerung gesichert.
   Erinnerungen können ein Ablaufdatum haben.
5. Antworten streamen per SSE, `render`-Ergebnisse erscheinen als Diagramme im Chat.
6. Die Eval-Suite prüft echte Werte statt leerer Datensätze.

Nicht-Ziele: neue Daten-Tools (Aktivitätsliste, Bestzeiten, Lauf-Vergleich — Eval-Fragen 4/7/10
sind mit den heutigen Tools strukturell nicht beantwortbar, eigener Folge-Spec), Embeddings,
Tool-Registry, Proaktivitäts-Job.

## Nutzerentscheidungen (2026-10-05)

| Frage | Entscheidung |
|---|---|
| Kennzahlen-Wissen | über den Systemprompt |
| Kurzzeit-Erinnerungen | Ablaufdatum (`expires_at`), konversationsübergreifend |
| Kontext-Überlauf | Fenster + LLM-Extraktion von Erinnerungen aus herausfallenden Turns |
| Streaming | SSE (vom Agenten entschieden: nur Server→Client nötig, Bestätigungen bleiben POST, geht ohne Zusatzkonfiguration durch Caddy/Vite-Proxy) |

## 1. Kennzahlen-Katalog + Tool-Beschreibungen

- `src/kairos/agent/metric_catalog.py`: handgeschriebene Beschreibung je `metric_id`
  (Bedeutung, Einheit, Form von `value`, Varianten). Test: jede in `build_default_registry()`
  registrierte `metric_id` hat einen Katalogeintrag (verhindert stilles Auseinanderlaufen).
- Systemprompt bekommt einen generierten Block `VERFÜGBARE KENNZAHLEN` (Registry + Katalog
  + benutzerdefinierte Metriken aus `custom_metric_definition`).
- `ToolSpec` bekommt ein Pflichtfeld `description` (deutsch, wann das Tool zu nutzen ist);
  `_to_openai_tool` nutzt es statt `"name (risk_class)"`.

## 2. Proposals an den Tool-Call binden

Heute: Proposal-Tool-Call wird ohne Ergebnis gespeichert, `/confirm` legt ein neues Paar an
und nimmt Tool-Name/Argumente ungeprüft vom Client — jede Konversation ist nach dem ersten
Vorschlag für Anbieter, die Tool-Ergebnisse erzwingen, ungültig.

Neu:
- `Proposal` trägt die `tool_call_id` des Modells.
- Weitere Tool-Calls desselben Batches nach dem Proposal bekommen sofort ein synthetisches
  Ergebnis ("nicht ausgeführt, wartet auf Bestätigung eines anderen Vorschlags").
- `POST /api/agent/conversations/{id}/proposals/{tool_call_id}/confirm` und `.../reject`:
  Server liest Tool-Name + Argumente aus der gespeicherten Assistant-Nachricht, nie vom
  Client. Confirm führt via `dispatch(pending_confirmation=True)` aus, Reject speichert
  "vom Nutzer abgelehnt". Beide speichern das Ergebnis unter **derselben** `tool_call_id`
  und streamen danach eine Fortsetzung des Agenten (gleiches Event-Format wie unten).
- Schreibt der Nutzer weiter, ohne zu entscheiden: offene Proposals bekommen beim nächsten
  Turn ein synthetisches "nicht bestätigt".
- Der History-Loader repariert defensiv jeden Tool-Call ohne Ergebnis (heilt auch bereits
  kaputte Bestands-Konversationen).
- Altes `POST /{id}/confirm` entfällt.

## 3. Ungültige Tool-Argumente

`json.loads` der Argumente wird abgefangen; das Modell bekommt ein Tool-Ergebnis
"Ungültige JSON-Argumente: …" und kann es im nächsten Schleifendurchlauf korrigieren.

## 4. Gedächtnis mit Ablaufdatum + Kontextbudget

**Schema:** `agent_memory.expires_at TIMESTAMPTZ NULL` (NULL = dauerhaft);
`conversation.compacted_through_seq BIGINT NULL` (bis zu welcher Nachricht bereits
extrahiert wurde). Eine Migration.

**Schreiben:** `remember` bekommt optional `expires_at` (ISO-Datum). Tool-Beschreibung:
zeitlich begrenzte Fakten ("nächste Woche viel Stress", "Knie schmerzt seit gestern") mit
Ablauf, stabile Fakten ohne.

**Lesen:** aktive Erinnerungen (`expires_at IS NULL OR expires_at > now()`) stehen in jedem
Turn im Systemprompt (Block `ERINNERUNGEN`, neueste zuerst, hart begrenzt auf ~1.500 Tokens).
`recall` durchsucht nur aktive. Abgelaufene werden beim Turn-Aufbau gelöscht (verschwinden
also wirklich). Die `/memory`-Seite zeigt das Ablaufdatum an.

**Fenster:** Historie = Nachrichten mit `seq > compacted_through_seq`, geschnitten nur an
Turn-Grenzen (ein Turn = User-Nachricht + alle folgenden Assistant/Tool-Nachrichten), so
dass nie ein Tool-Paar zerrissen wird. Budget für die Historie: 12.000 Tokens
(`litellm.token_counter`), Gesamtziel aus `03-agent-design.md`: Median < 15k, Hardcap 40k.

**Extraktion:** Fallen Turns aus dem Fenster, läuft **nach** Abschluss der Antwort (kein
Einfluss auf Time-to-first-Token) ein nicht-streamender LLM-Aufruf: Eingabe = herausfallende
Turns + aktive Erinnerungen (gegen Dubletten), Ausgabe = JSON-Liste
`[{content, expires_at|null}]`. Ergebnisse als `source='agent'`, danach
`compacted_through_seq` setzen. Schlägt die Extraktion fehl, bleibt `compacted_through_seq`
stehen und sie wird beim nächsten Turn erneut versucht; das Fenster schneidet trotzdem.

## 5. SSE-Streaming + Visualisierung

**Endpoint:** `POST /api/agent/conversations/{id}/stream` (Body `{content}`),
`text/event-stream`. Events:

| Event | Daten |
|---|---|
| `token` | `{text}` |
| `tool_start` | `{id, name}` |
| `tool_end` | `{id, name, summary, ok}` |
| `render` | `{id, component, config}` |
| `memory` | `{id, content, expires_at}` |
| `proposal` | `{tool_call_id, tool_name, summary}` |
| `error` | `{detail}` |
| `done` | `{}` |

- Orchestrator wird ein Async-Generator über `litellm.acompletion(stream=True)`;
  Tool-Call-Deltas werden zusammengesetzt. `run_turn()` bleibt als nicht-streamender
  Wrapper (sammelt Events) für Eval-Suite und Tests.
- `POST /{id}/messages` (nicht-streamend) entfällt; Fehler, die bisher 502/503 waren,
  kommen als `error`-Event, sobald der Stream begonnen hat, davor weiterhin als HTTP-Status.
- **Frontend:** `/chat` sendet per `fetch` direkt an `/api/...` (gleiche Origin, Cookie;
  Vite-Proxy lokal, Caddy produktiv) und liest den Stream; Tokens erscheinen sofort,
  Tool-Status als dezente Zeile ("Frage HRV ab …"), Proposals als Karte mit
  Bestätigen/Ablehnen (die wiederum streamen). Antworten werden als Markdown gerendert
  (`marked` + `DOMPurify`).
- **Visualisierung:** `render` wird auf die Komponenten reduziert, die das Frontend
  wirklich zeichnet: `TimeSeriesChart`, `BarChart`, `Gauge`, `StatCard`, `Table`
  (Scatter/ActivityList entfallen — es gibt kein Tool, das solche Daten liefert). Pro
  Komponente ein festes `config`-Schema in der Tool-Beschreibung, serverseitig validiert.
  Chat zeichnet sie mit dem bestehenden `EChartsBase` (SVG-Renderer). Gespeicherte
  `render`-Ergebnisse werden beim Neuladen einer Konversation wieder angezeigt
  (`GET .../messages` liefert Tool-Nachrichten mit Tool-Namen mit).

## 6. Eval-Suite

- Seed schreibt eine aktive Garmin-`connection`, Wellness-Samples (HR, HRV, Schlaf) und
  ruft die Recompute-Funktionen auf, damit Kennzahlen echte Werte liefern.
- Zusätzlicher Mehrturn-Fall: Vorschlag → Bestätigen → Folgefrage (deckt Abschnitt 2 ab).
- Misst Time-to-first-Token je Fall.

## Reihenfolge

1. Abschnitte 3 + 2 (Fehler), 2. Abschnitt 1, 3. Abschnitt 4, 4. Abschnitt 5,
5. Abschnitt 6 + Live-Eval.
