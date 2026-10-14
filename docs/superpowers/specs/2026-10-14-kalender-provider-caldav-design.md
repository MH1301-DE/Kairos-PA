# Kalender-Provider-Abstraktion & Apple Kalender (CalDAV) — Design-Spec

| | |
|---|---|
| **Datum** | 2026-10-14 |
| **Status** | Design abgestimmt (Brainstorming 2026-10-14). AP 0 (CalDAV-Verifikation gegen echtes iCloud-Konto) offen. |
| **Baut auf** | Phase 3 Kalender (`2026-08-13-phase-3-kalender-design.md`) · Agent-Harness v2 (`2026-10-05-agent-harness-v2-design.md`) · `04-integrationen.md` §4 (CalDAV-Zielbild) · ADR-0003 |
| **Berührt** | Aktivitäten & Workouts (`2026-10-07-aktivitaeten-und-workouts-design.md`): dessen „Google-Termin“ wird zu „Termin im Standardkalender“ |
| **Nicht im Scope** | Generischer Scheduler (eigene Spec, Schnittstelle in §8) · CalDAV-Push · wiederkehrende Termine anlegen · Termine bearbeiten (PATCH) |

---

## 0. Zusammenfassung

Kairos bekommt einen zweiten Kalender-Provider (Apple/iCloud über CalDAV). Leitlinie:
**nur der Connector ist providerspezifisch** — Agent-Tools, API, Frontend, Lagebild und
Planung arbeiten gegen ein gemeinsames `CalendarProvider`-Protokoll.

1. **`CalendarProvider`-Protokoll** + Resolver; Google und CalDAV als Implementierungen.
2. **Standardkalender pro Nutzer** (`user_setting.default_calendar`, Dropdown auf der
   Konfigseite). Jede Kalender-Interaktion nutzt den Standard, außer der Nutzer nennt im
   Chat ausdrücklich einen anderen Kalender.
3. **CalDAV-Connector** (iCloud getestet, generisches CalDAV möglich): Lesen, Anlegen,
   Löschen — dieselben Funktionen wie Google heute.
4. **Konfigseite:** Apple-Login (Apple-ID + App-spezifisches Passwort), Auswahl der
   iCloud-Kalender (Lesen/Schreiben), Standard-Dropdown.
5. **Herausgelöster Sync-Kern** `sync_calendar(session, user_id, provider)`, aufrufbar von
   Button und künftigem Scheduler.

---

## 1. Entscheidungen

### 1.1 Mit dem Nutzer abgestimmt (2026-10-14)

| Thema | Entscheidung |
|---|---|
| Zielnutzer | ein anderer Nutzer der Gruppe (iPhone); getestet wird mit dem iCloud-Konto von Nutzer 0 |
| Funktionsumfang | Lesen **und** Schreiben, Parität zu Google (Sync, Anlegen, Löschen) |
| Mehrere Provider | beide Verbindungen dürfen gleichzeitig bestehen; einer ist **Standard** |
| Auswahlregel | **alle** Kalender-Interaktionen (Termine abfragen, freie Slots, Anlegen, Planung, Kalenderansicht) nutzen den Standard, außer der Nutzer nennt im Chat einen anderen Kalender |
| Agent-Tools | ein und dasselbe Tool für beide Kalender, optionaler Parameter `calendar` |
| Apple-Login | auf der Profil-/Konfigseite, **nicht** über den Chat |
| Standard wählen | Dropdown auf der Konfigseite |
| iCloud-Kalenderauswahl | auf der Konfigseite; wird in `connection.config` gespeichert und beim Bauen an den CalDAV-Client übergeben — **keine** Apple-spezifischen Parameter in den agnostischen Methoden |
| Periodischer Sync | über den geplanten generischen Scheduler (eigene Spec); diese Spec liefert nur einen aufrufbaren Sync-Kern |

### 1.2 Daraus abgeleitet (in dieser Spec festgelegt)

| Thema | Festlegung | Begründung |
|---|---|---|
| Löschen | geht immer an den Provider, aus dem der Termin stammt (`calendar_event.connector`), unabhängig vom Standard | die Zeile kennt ihre Herkunft; ein Parameter wäre nur eine Fehlerquelle |
| Freie Slots | nur Termine des gewählten Kalenders zählen als belegt | Konsequenz der Auswahlregel; bewusst akzeptiert |
| Login-Kopplung | Google-Login legt weiterhin bei jedem Login eine `google_calendar`-Connection an (`auth/google.py`) | Auth-Fluss unverändert; deshalb muss der Standard eine explizite Einstellung sein, nicht „welche Connection existiert“ |
| Wiederkehrende externe Termine | werden gelesen und expandiert; einzelne Instanzen über CalDAV löschen → `409 recurring_not_supported` | Instanz-Löschen erfordert EXDATE-Pflege am Master; Kairos-eigene Termine sind nie wiederkehrend |
| Bibliotheken | `caldav` (python-caldav) + `icalendar`; Versionen beim AP 0 festlegen | synchroner Client → `asyncio.to_thread`, etabliertes Muster |

---

## 2. Ist-Stand (Codeprüfung 2026-10-14)

**Bereits agnostisch:** `GET /api/calendar/events`, `GET /api/calendar/free-slots`,
`query_calendar` und `_free_blocks_by_day` (Planung) lesen nur aus `calendar_event` via
`CalendarEventRepository.list_between()`. Tool-Namen sind neutral. `calendar_event` hat
`connector` und `calendar_id`; `connection.config` (JSONB) existiert bereits.

**Fest an Google gekoppelt:**

| Stelle | Kopplung |
|---|---|
| `routers/calendar.py` `_create_calendar_event` | `_build_google_calendar_client`, `"primary"`, Connector-String `"google_calendar"` |
| `routers/calendar.py` `_delete_calendar_event` | ruft immer den Google-Client, auch für Termine anderer Herkunft |
| `routers/sync.py` | `POST /api/sync/google_calendar/sync`, `_run_calendar_sync_task` mit Google-Client im Router |
| `agent/situation_brief.py` | Datenstand-Zeile kennt nur „Google Cal“ |
| `agent/tools.py` | Beschreibung von `propose_calendar_event` nennt Google Calendar |
| Frontend | `'google_calendar'`-Literale in `+layout.svelte`, `account/+page.svelte`, `sync/+page.server.ts`, `sync/+page.svelte`, `calendar/+page.server.ts` |

**Fehlt:** eine Schreib-API für `user_setting` (siehe HANDOVER, Phase 2: „solange es keine
`user_setting`-Schreib-API gibt“).

**Korrektur an `04-integrationen.md` §4.1:** Die dort genannte Principal-URL
`https://caldav.icloud.com/{apple_id}/` ist nicht die tatsächliche Form. Discovery läuft über
`PROPFIND current-user-principal` gegen `caldav.icloud.com`; Antwort ist ein Pfad mit
numerischer Konto-ID auf einem Shard-Host (`pXX-caldav.icloud.com`). Wird in AP 0
verifiziert und danach in `04` korrigiert.

---

## 3. Architektur

### 3.1 `CalendarProvider`-Protokoll (`src/kairos/calendar/provider.py`)

```python
class CalendarInfo(TypedDict):
    id: str            # Google: "primary"; CalDAV: Collection-URL
    name: str
    writable: bool

class ProviderEvent(TypedDict):
    external_id: str   # Google: Event-ID; CalDAV: UID bzw. "UID#RECURRENCE-ID(UTC)"
    calendar_id: str
    summary: str | None
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    status: str        # confirmed | tentative | cancelled
    recurring: bool
    provider_meta: dict[str, Any]   # CalDAV: {"href", "etag"}; Google: {}

class CalendarProvider(Protocol):
    provider_id: str   # "google_calendar" | "caldav"
    def list_calendars(self) -> list[CalendarInfo]: ...
    def list_events(self, window: Window) -> list[ProviderEvent]: ...
    def create_event(self, *, summary: str, start: datetime, end: datetime,
                     description: str | None) -> ProviderEvent: ...
    def delete_event(self, event: CalendarEvent) -> None: ...
```

- Synchron (beide Clients sind synchron); Aufrufer nutzen `asyncio.to_thread`.
- `create_event` schreibt in den **konfigurierten** Schreibkalender des Providers
  (Google: `"primary"`, CalDAV: `config.write_calendar`) — kein Kalender-Parameter.
- `delete_event` bekommt die Zeile, damit CalDAV `href`/`etag` aus `provider_meta` lesen kann.
- Fehler: einheitliche Ausnahmen `ProviderAuthError` (→ `reauth_required`),
  `ProviderUnavailable` (→ 502/503), `RecurringNotSupported` (→ 409).
- Der bestehende `Connector`-Vertrag (`fetch`/`normalize`/`write_back`) bleibt für die
  Ingestion-Seite; die Provider-Implementierungen dürfen intern darauf aufsetzen.

### 3.2 Resolver & Auswahlregel (`src/kairos/calendar/resolve.py`)

```python
async def resolve_calendar(session, user_id, requested: str | None) -> CalendarProvider
async def provider_for_event(session, user_id, event: CalendarEvent) -> CalendarProvider
```

- `requested` ist `None` (→ `user_setting.default_calendar`) oder ein expliziter Wert aus
  dem Chat/der UI.
- Gewählter Provider nicht verbunden oder Status ≠ `active`/`reauth_required` →
  `CalendarNotConnected(provider)` → HTTP 409 `calendar_not_connected`, für den Agenten ein
  klarer Tool-Fehler („Apple Kalender ist nicht verbunden“).
- Ersetzt alle drei Aufrufe von `_build_google_calendar_client`; die Google-Bauleistung
  wandert in `connectors/google_calendar/provider.py`. Das stille `except Exception: return
  None` (HANDOVER, Phase-1-Härtung) wird dabei durch `logger.exception` + typisierte
  Ausnahme ersetzt.

**Lesepfade:** `CalendarEventRepository.list_between()` bekommt einen Pflichtparameter
`connector`. Alle Aufrufer (`/events`, `/free-slots`, `query_calendar`,
`_free_blocks_by_day`) lösen ihn über `resolve_calendar(...).provider_id` auf.

### 3.3 Datenmodell (eine Migration)

| Tabelle | Änderung |
|---|---|
| `user_setting` | `default_calendar TEXT NOT NULL DEFAULT 'google_calendar'`, `CHECK (default_calendar IN ('google_calendar','caldav'))` |
| `calendar_event` | `provider_meta JSONB NOT NULL DEFAULT '{}'` (CalDAV: `href`, `etag`) |
| `connection` | keine Schemaänderung; für `connector='caldav'`: `external_account` = Apple-ID, `credentials_enc` = verschlüsseltes JSON `{username, password, principal_url}`, `config` = `{read_calendars: [url…], write_calendar: url}` |

`calendar_event.calendar_id` speichert bei CalDAV die Collection-URL (Spalte existiert).

### 3.4 Sync-Kern (`src/kairos/calendar/sync.py`)

```python
async def sync_calendar(session, user_id, provider_id: str,
                        window: Window | None = None) -> SyncResult
```

- Holt Termine über `provider.list_events(window)` (Default −7 bis +83 Tage wie heute),
  upsertet nach `(user_id, connector, external_id)`.
- **Lösch-Abgleich:** externe Zeilen des Providers im Fenster, die nicht mehr geliefert
  werden, → `status='cancelled'` (gleiche Semantik wie `mark_deleted`).
- Erwartet eine Session mit installiertem RLS-Listener; kennt weder HTTP noch
  `SyncJobRegistry`.
- Router: `POST /api/sync/calendar/sync` mit Body `{"calendar": "google_calendar"|"caldav"|null}`
  ruft den Kern im BackgroundTask; Job-/Lock-/Cooldown-Logik bleibt im Router.
  `POST /api/sync/google_calendar/sync` bleibt als Alias bis das Frontend umgestellt ist,
  danach entfernen.

---

## 4. CalDAV-Connector (`src/kairos/connectors/caldav/`)

### 4.1 Verbinden

1. Konfigseite → `POST /api/connections/caldav` `{username, password, server_url?}`
   (`server_url` Default `https://caldav.icloud.com`).
2. Backend: Discovery (`current-user-principal` → `calendar-home-set` → Collections mit
   `VEVENT`-Unterstützung). Fehlschlag mit 401 → `400 invalid_credentials`, kein Speichern.
3. Erfolg: Connection anlegen (Upsert-Muster aus `_store_connection`, alte CalDAV-Zeilen des
   Nutzers deaktivieren), Antwort enthält die Kalenderliste.
4. `PUT /api/connections/caldav/config` `{read_calendars, write_calendar}` — Validierung:
   `write_calendar` muss in der Liste und beschreibbar sein.
5. `DELETE /api/connections/caldav` → `status='disabled'`, `credentials_enc=NULL`; war
   `caldav` Standard, fällt der Standard auf `google_calendar` zurück.

### 4.2 Lesen

- Pro Kalender in `read_calendars` ein `calendar-query` REPORT mit `time-range` über das
  Fenster.
- **Wiederkehrende Termine:** serverseitig per `<C:expand>`, falls iCloud das korrekt
  liefert (AP 0); sonst clientseitig (`recurring-ical-events` o. ä.). Instanzen bekommen
  `external_id = "{UID}#{RECURRENCE-ID in UTC}"`, `recurring=true`.
- Ganztägig (`DTSTART;VALUE=DATE`) → `all_day=true`, Grenzen wie beim Google-Normalizer.
  `TZID`/`VTIMEZONE` → Umrechnung nach UTC; schwebende Zeiten → Zeitzone des Nutzers
  (bis eine Nutzer-Zeitzone existiert: `Europe/Berlin`, als offener Punkt markiert).
- `STATUS:CANCELLED` → `cancelled`, `TENTATIVE` → `tentative`.
- Optimierung (nicht Pflicht für v1): `sync-collection` (RFC 6578) bzw. ctag/ETag, falls
  AP 0 Unterstützung bestätigt; Token in `sync_state`.

### 4.3 Schreiben & Löschen

- **Anlegen:** neue UID (`uuid4@kairos`), `PUT {write_calendar}/{uid}.ics` mit
  `If-None-Match: *`; ETag aus der Antwort (bzw. per Folge-PROPFIND) in `provider_meta`.
- **Löschen:** `DELETE {href}` mit `If-Match: {etag}`. 412 (Termin extern geändert) →
  einmal neu laden und erneut versuchen; 404 → lokal als gelöscht markieren.
  `recurring=true` → `RecurringNotSupported`.
- Externe Termine behalten die bestehende Bestätigungspflicht (`needs_confirmation`).

### 4.4 Fehler & Reauth

- 401/403 → `connection.status='reauth_required'`, `reauth_since` setzen (App-spezifisches
  Passwort widerrufen oder Apple-ID-Passwort geändert); Konfigseite zeigt „neu verbinden“.
- Netzwerk/5xx → `ProviderUnavailable`, `connection.last_error`.

---

## 5. Agent

- `query_calendar`, `propose_calendar_event`, `plan_propose`, `plan_commit` erhalten einen
  optionalen Parameter
  `calendar: {"type": "string", "enum": ["google", "apple"]}` mit der Beschreibung „Nur
  setzen, wenn der Nutzer ausdrücklich einen Kalender nennt; sonst gilt der Standard.“
  Mapping `google → google_calendar`, `apple → caldav` an einer Stelle.
- `delete_calendar_event`: kein Parameter (Herkunft aus der Zeile).
- `plan_adjust`: schreibt keine Kalendertermine (unverändert).
- Bei Bestätigungs-Tools wird der aufgelöste Kalender in die Vorschau übernommen
  („Termin in Apple Kalender anlegen: …“), damit der Nutzer bestätigt, was er sieht.
- **Lagebild:** `Kalender: Apple ✓ (Standard) · Google ✓`; nicht verbundene Provider
  werden nur genannt, wenn sie Standard sind.
- Tool-Beschreibungen nennen keinen konkreten Anbieter mehr.

---

## 6. API & Frontend

| Endpunkt | Änderung |
|---|---|
| `GET /api/connections` | zusätzlich `calendar: {default, providers: [{id, label, status, account}]}` |
| `GET/PATCH /api/settings/calendar` | neu: `{default_calendar}` (erste `user_setting`-Schreib-API, bewusst schmal) |
| `GET /api/calendar/events`, `/free-slots` | optionaler Query-Parameter `calendar` |
| `POST /api/calendar/events` | optionales Feld `calendar` |
| `POST /api/sync/calendar/sync` | neu (siehe §3.4) |
| `POST/PUT/DELETE /api/connections/caldav[...]` | neu (siehe §4.1) |

**Frontend:**
- Konfigseite (`/account`): Abschnitt „Kalender“ mit Standard-Dropdown (nur verbundene
  Provider wählbar), Apple-Verbinden-Formular mit Hinweis auf App-spezifisches Passwort
  (Link `appleid.apple.com`), danach Kalenderauswahl (Lesen: Mehrfachauswahl, Schreiben:
  Einfachauswahl), Status/„neu verbinden“/„trennen“.
- `/calendar`: zeigt den Standardkalender; Umschalter nur sichtbar, wenn beide verbunden
  sind. „Synchronisieren“ ruft den neuen Endpunkt für den angezeigten Kalender.
- `/sync`, `+layout.svelte`: alle `'google_calendar'`-Literale durch die
  `calendar`-Struktur aus `/api/connections` ersetzen.

---

## 7. Sicherheit

- Das App-spezifische Passwort gibt Zugriff auf **Mail, Kontakte und Kalender** des
  iCloud-Kontos (nicht nur Kalender). Gespeichert nur verschlüsselt (Envelope, DEK des
  Nutzers), nie geloggt, nie an das LLM, nie im Chat. Der Onboarding-Text sagt das offen und
  nennt den Widerruf unter `appleid.apple.com`.
- Alle neuen Endpunkte und der Sync-Kern laufen mit `install_rls_listener`.
- `06-sicherheit-und-datenschutz.md` §„Apple/iCloud“ wird vom Zielbild auf Ist-Stand gezogen.

---

## 8. Schnittstelle zum geplanten Scheduler (nicht im Scope)

Abgestimmte Richtung: **ein generischer Scheduler**, keine dienstspezifischen Jobs. Ein Job
ist `(user_id, aktion, parameter, zeitplan)`, z. B. Kalender-Sync mit Provider oder
Agent-Lauf mit Prompt.

**Empfehlung für die Scheduler-Spec:** Aktionen nicht als HTTP-Aufruf der Frontend-API
ausführen, sondern über eine Aktions-Registry, die dieselben Service-Funktionen aufruft wie
die Endpunkte (`calendar.sync → sync_calendar(...)`, `garmin.backfill → ...`,
`agent.run → Orchestrator mit Prompt`). Gründe:
- Jeder Endpunkt hängt an `current_user` (Session-Cookie); ein HTTP-Scheduler bräuchte
  Service-Token plus Nutzer-Impersonation.
- Sync-Endpunkte antworten `202` und arbeiten im BackgroundTask — der Scheduler sähe das
  Ergebnis nicht.
- Generik bleibt gleich: Registry-Eintrag = Aktionsname + Parameterschema; das Frontend kann
  aus demselben Schema das Formular erzeugen.

**Was diese Spec dafür liefert:** `sync_calendar(session, user_id, provider_id, window)` als
HTTP-freie Funktion. **Offen für die Scheduler-Spec:** `SyncJobRegistry` nutzt
In-Process-`asyncio.Lock`s — läuft der Scheduler in einem eigenen Prozess, schützen sie nicht
gegen einen parallelen Button-Klick (z. B. Postgres-Advisory-Lock je
`(user_id, connector, kind)`).

---

## 9. Arbeitspakete

| AP | Inhalt | Abnahme |
|---|---|---|
| **0** | **CalDAV-Verifikation** mit iCloud-Konto von Nutzer 0 (Skript unter `scripts/`, Zugangsdaten nur lokal): Discovery-Pfad, Kalenderliste, `calendar-query` mit/ohne `expand`, `sync-collection`-Unterstützung, PUT/DELETE-Roundtrip mit ETag, Ganztags-/Zeitzonen-/Wiederholungs-Beispiele. Anonymisierte Fixtures nach `tests/fixtures/caldav/`. | Befunde in §2/§4 dieser Spec nachgetragen; `04` §4 korrigiert |
| 1 | Protokoll, Typen, Ausnahmen; Google-Provider aus bestehendem Code | bestehende Kalendertests grün, keine Verhaltensänderung |
| 2 | Migration (`default_calendar`, `provider_meta`); Resolver; `list_between(connector=…)`; Router + Planung auf Resolver | 413+ Tests grün; Google-Pfad unverändert |
| 3 | Sync-Kern herauslösen, `POST /api/sync/calendar/sync`, Lösch-Abgleich | Integrationstest: extern gelöschter Termin → `cancelled` |
| 4 | CalDAV-Provider (Lesen) gegen Fixtures | Normalizer-Tests auf echten AP-0-Shapes |
| 5 | CalDAV-Provider (Anlegen/Löschen) + Verbinden/Config/Trennen-Endpunkte | Roundtrip gegen echtes iCloud manuell, Fixtures automatisiert |
| 6 | Settings-API, Agent-Parameter, Lagebild, Tool-Texte | Dispatcher-Tests gegen echte `TOOLS_BY_NAME`; Eval-Fall „trag das in meinen Apple Kalender ein“ |
| 7 | Frontend: Konfigseite, Kalenderansicht, Literale entfernen | `npm run check` 0/0, Vitest grün, manueller Test auf iPhone |
| 8 | Doku: `01`, `04`, `06`, `08`, HANDOVER; Workouts-Spec „Google-Termin“ → „Standardkalender“ | — |

Abschluss wie bisher mit Whole-Branch-Review (Kompositionsfehler zwischen APs, vgl.
HANDOVER-Lektionen) und einem Real-Data-Lauf.

---

## 10. Risiken & offene Punkte

- **iCloud-Verhalten unverifiziert** (Discovery, `expand`, `sync-collection`, ETag nach PUT)
  — genau dafür AP 0 vor jeder Implementierung.
- **Keine Nutzer-Zeitzone** im Modell; schwebende iCal-Zeiten brauchen eine. Bis dahin fest
  `Europe/Berlin`. Hängt mit dem bekannten UTC-Tagesschnitt-Befund zusammen.
- **Google-Kalender-Scope beim Login** wird auch von Apple-Nutzern angefragt; optionaler
  Scope wäre eine eigene Auth-Änderung (nicht in dieser Spec).
- **Rate-Limits von iCloud** sind nicht dokumentiert; Sync nur auf Anforderung bzw. später
  per Scheduler mit moderatem Intervall (≥ 15 min).
- `plan_commit`-Teilfehler (Termine 1..N−1 angelegt, lokale Zeilen zurückgerollt,
  HANDOVER) gilt für CalDAV genauso; Kompensation bleibt Thema der Workouts-Spec
  (gemeinsamer Schreibdienst).
