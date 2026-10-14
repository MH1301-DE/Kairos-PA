# Kalender-Provider-Abstraktion & Apple Kalender (CalDAV) — Design-Spec

| | |
|---|---|
| **Datum** | 2026-10-14 |
| **Status** | Design abgestimmt (Brainstorming 2026-10-14), nach Review vom 2026-10-14 bereinigt. AP 0 (CalDAV-Verifikation gegen echtes iCloud-Konto) offen; ungeprüfte Fakten stehen gesammelt in §12. |
| **Baut auf** | Phase 3 Kalender (`2026-08-13-phase-3-kalender-design.md`) · Agent-Harness v2 (`2026-10-05-agent-harness-v2-design.md`) · `04-integrationen.md` §4 (CalDAV-Zielbild) · ADR-0003 |
| **Berührt** | Aktivitäten & Workouts (`2026-10-07-aktivitaeten-und-workouts-design.md`): deren „Google-Termin“ wird zu „Termin im aufgelösten Kalender“, Kalender-Schreibzugriffe laufen über den Schreibdienst aus §3.5 (Details §11) |
| **Nicht im Scope** | Generischer Scheduler (eigene Spec, Schnittstelle in §8) · CalDAV-Push · wiederkehrende Termine anlegen · Termine bearbeiten (PATCH) · einzelne Instanzen wiederkehrender CalDAV-Termine löschen |

---

## 0. Zusammenfassung

Kairos bekommt einen zweiten Kalender-Provider (Apple/iCloud über CalDAV). Leitlinie:
**nur der Connector ist providerspezifisch** — Agent-Tools, API, Frontend, Lagebild und
Planung arbeiten gegen ein gemeinsames `CalendarProvider`-Protokoll.

1. **`CalendarProvider`-Protokoll** + Resolver; Google und CalDAV als Implementierungen.
2. **Standardkalender pro Nutzer** (`user_setting.default_calendar`, Dropdown auf der
   Konfigseite). Jede Kalender-Interaktion nutzt den Standard, außer der Nutzer nennt im
   Chat ausdrücklich einen anderen Kalender oder wählt ihn in der Kalenderansicht.
3. **CalDAV-Connector** (iCloud getestet, generisches CalDAV möglich): Lesen, Anlegen,
   Löschen — dieselben Funktionen wie Google heute.
4. **Konfigseite:** Apple-Login (Apple-ID + App-spezifisches Passwort), Auswahl der
   iCloud-Kalender (Lesen/Schreiben), Standard-Dropdown.
5. **Herausgelöster Sync-Kern** `sync_calendar(session, user_id, provider)` mit
   Lösch-Abgleich, aufrufbar von Button und künftigem Scheduler.
6. **Kalender-Schreibdienst** (§3.5), über den alle Tools beider Specs anlegen, ersetzen
   und löschen.

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
| Ersetzen (löschen + neu anlegen) | neuer Termin im Kalender des **ersetzten** Termins, nicht im Standard | sonst wandert ein Termin beim Verschieben den Provider (betrifft Workouts-Spec, §11) |
| Plan-Kalender | `plan_propose` merkt sich den aufgelösten Kalender in `plan.calendar`; `plan_commit` schreibt dorthin und hat keinen eigenen Parameter | Blöcke werden gegen genau den Kalender geplant, in den sie geschrieben werden |
| Kalenderansicht | Umschalter (nur wenn beide verbunden) ist die UI-seitige Entsprechung zu „Nutzer nennt einen anderen Kalender“; alle Aktionen der Seite folgen dem angezeigten Kalender | sonst kämen Slots aus dem einen und der Termin landete im anderen Kalender |
| Freie Slots | nur Termine des gewählten Kalenders zählen als belegt | Konsequenz der Auswahlregel; bewusst akzeptiert |
| Login-Kopplung | Google-Login legt weiterhin bei jedem Login eine `google_calendar`-Connection an (`auth/google.py:112-134`, Upsert Zeile 123) | Auth-Fluss unverändert; deshalb muss der Standard eine explizite Einstellung sein, nicht „welche Connection existiert“ |
| Wiederkehrende externe Termine | werden gelesen und expandiert; einzelne Instanzen über CalDAV löschen → `409 recurring_not_supported`. Google-Instanzen (`singleEvents=true`) sind einzeln löschbar und bleiben es | CalDAV: alle Instanzen teilen eine Ressource (`href`), `DELETE` träfe die ganze Serie; Instanz-Löschen erfordert EXDATE-Pflege am Master. Kairos-eigene Termine sind nie wiederkehrend |
| Nutzer-Zeitzone | `app_user.home_timezone` (existiert, NOT NULL, Default `Europe/Berlin`, `db/models.py:38`) | für schwebende iCal-Zeiten |
| Bibliotheken | `caldav` (python-caldav) + `icalendar`; Version und sync- oder `aio`-Client in AP 0 festlegen | python-caldav 3.x bietet beides (`caldav.DAVClient`, `caldav.aio.AsyncDAVClient`); beim synchronen Client gilt das etablierte `asyncio.to_thread`-Muster |

---

## 2. Ist-Stand (Codeprüfung 2026-10-14, Stand `78c4ac6`)

**Bereits agnostisch:** `GET /api/calendar/events`, `GET /api/calendar/free-slots`,
`query_calendar`, `_free_blocks_by_day` (Planung) und das Lagebild (`_kalender_lines`) lesen
nur aus `calendar_event` via `CalendarEventRepository.list_between()`. Tool-Namen sind
neutral. `calendar_event` hat `connector` und `calendar_id`; `connection.config` (JSONB)
existiert bereits. Es gibt keine `user_setting`-Schreib-API: `UserSetting` wird in `src/` nur
gelesen (`repositories/user_setting.py:33-46`, `routers/calendar.py:201-217`).

**Fest an Google gekoppelt:**

| Stelle | Kopplung |
|---|---|
| `routers/calendar.py:121-155` `_create_calendar_event` | `_build_google_calendar_client`, `"primary"`, Connector-String `"google_calendar"` |
| `routers/calendar.py:158-184` `_delete_calendar_event` | ruft immer den Google-Client, auch für Termine anderer Herkunft; ohne Client wird nur lokal storniert |
| `routers/sync.py:137-175, 363-445` | `POST /api/sync/google_calendar/sync`, `_run_calendar_sync_task` und `_build_google_calendar_client` im Router |
| `db/models.py:115` + Migration `a3580dcb7b4a` | `calendar_event.calendar_id` Default `'primary'` |
| `repositories/calendar_event.py:18-92` | `upsert_from_records` und `upsert_kairos_event` setzen kein `calendar_id` (also immer `'primary'`) |
| `agent/situation_brief.py:53` | Datenstand-Zeile kennt nur „Google Cal“ |
| `agent/tools.py:571` | Beschreibung von `propose_calendar_event` nennt Google Calendar |
| `scripts/agent_eval_suite.py:131, 261, 329-351` | Eval-Fake ersetzt `_create_calendar_event` mit fester Signatur; Testtermine mit `connector='google_calendar'` |
| Frontend | `'google_calendar'`-Literale in `+layout.svelte:27`, `account/+page.svelte:23`, `sync/+page.server.ts:37`, `sync/+page.svelte:23`, `calendar/+page.server.ts:127` |

**iCloud-Discovery (Arbeitshypothese, wird in AP 0 geprüft):** Die in `04-integrationen.md`
§4.1 genannte Principal-URL `https://caldav.icloud.com/{apple_id}/` ist nach Sekundärquellen
nicht die tatsächliche Form. `PROPFIND current-user-principal` gegen `caldav.icloud.com`
liefert einen Pfad mit numerischer Konto-ID (`/<id>/principal/`); der kontoabhängige
Shard-Host (`pNN-caldav.icloud.com`) erscheint im `calendar-home-set`. python-caldav
behandelt diesen Hostwechsel (`caldav/collection.py`, Setter `calendar_home_set`). `04` wird
erst nach AP 0 korrigiert.

---

## 3. Architektur

### 3.1 `CalendarProvider`-Protokoll (`src/kairos/calendar/provider.py`)

```python
class CalendarInfo(TypedDict):
    id: str            # Google: "primary"; CalDAV: Collection-URL
    name: str
    writable: bool

class ProviderEvent(TypedDict):
    external_id: str   # Google: Event-ID; CalDAV siehe unten
    calendar_id: str
    summary: str | None
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    status: str        # confirmed | tentative | cancelled
    recurring: bool
    provider_meta: dict[str, Any]   # CalDAV: {"href", "etag", "recurring"}; Google: {"recurring"}

class CalendarProvider(Protocol):
    provider_id: str   # "google_calendar" | "caldav"
    def list_calendars(self) -> list[CalendarInfo]: ...
    def list_events(self, window: Window) -> ProviderFetch: ...
    def create_event(self, *, summary: str, start: datetime, end: datetime,
                     description: str | None) -> ProviderEvent: ...
    def delete_event(self, event: CalendarEvent) -> None: ...

class ProviderFetch(TypedDict):
    events: list[ProviderEvent]
    complete_calendars: list[str]   # nur diese Kalender nimmt der Lösch-Abgleich (§3.4)
    failed_calendars: list[str]
```

- `create_event` schreibt in den **konfigurierten** Schreibkalender des Providers
  (Google: `"primary"`, CalDAV: `config.write_calendar`) — kein Kalender-Parameter.
- `delete_event` bekommt die Zeile, damit CalDAV `href`/`etag`/`recurring` aus
  `provider_meta` lesen kann.
- **CalDAV-`external_id`:** Einzeltermin `"{UID}"`; jede Instanz einer Serie
  `"{UID}#{RECURRENCE-ID in UTC}"`, die Erstinstanz `"{UID}#{DTSTART in UTC}"`. Bei
  serverseitiger Expansion trägt die Erstinstanz laut RFC 4791 §9.6.5 keine `RECURRENCE-ID`
  und keine `RRULE`; `recurring` wird deshalb immer aus dem Master bestimmt (§4.2).
- **Google-`recurring`:** aus `recurringEventId` (heute verworfen,
  `google_calendar/normalize.py:24-50`); nur informativ, Google-Instanzen bleiben löschbar.
- Fehler: einheitliche Ausnahmen `ProviderAuthError` (→ `reauth_required`),
  `ProviderUnavailable` (→ 502/503), `RecurringNotSupported` (→ 409). Ihre Meldungen sind
  feste Texte ohne URL und ohne Upstream-Antwort (§7).
- Der bestehende `Connector`-Vertrag (`fetch`/`normalize`/`write_back`) bleibt für die
  Ingestion-Seite; die Provider-Implementierungen dürfen intern darauf aufsetzen.

### 3.2 Resolver & Auswahlregel (`src/kairos/calendar/resolve.py`)

```python
async def resolve_calendar(session, user_id, requested: str | None) -> CalendarProvider
async def provider_for_event(session, user_id, event: CalendarEvent) -> CalendarProvider
async def default_calendar(session, user_id) -> str   # ohne user_setting-Zeile: "google_calendar"
```

- `requested` ist `None` (→ `user_setting.default_calendar`) oder ein expliziter Wert aus
  dem Chat/der UI.
- Gewählter oder (bei `provider_for_event`) Herkunfts-Provider nicht verbunden oder Status ≠
  `active`/`reauth_required` → `CalendarNotConnected(provider)` → HTTP 409
  `calendar_not_connected`, für den Agenten ein klarer Tool-Fehler („Apple Kalender ist nicht
  verbunden“). Ein Termin wird dann **nicht** nur lokal storniert (heute
  `routers/calendar.py:181-184`, führt zum Wiederauftauchen beim nächsten Sync).
- Ersetzt alle drei Aufrufe von `_build_google_calendar_client` (`routers/calendar.py:124,
  181`, `routers/sync.py:374`); die Google-Bauleistung wandert in
  `connectors/google_calendar/provider.py`. Das stille `except Exception: return None`
  (HANDOVER, Phase-1-Härtung) wird dabei durch `logger.exception` + typisierte Ausnahme
  ersetzt.
- Der Resolver ist die einzige Stelle außerhalb von `connectors/`, die Provider-Klassen
  importiert (Richtung ADR-0003; ein Import-Linter ist heute nicht konfiguriert).

**Lesepfade:** `CalendarEventRepository.list_between()` bekommt einen Pflichtparameter
`connector`. Alle Aufrufer lösen ihn über den Resolver auf:

| Aufrufer | Kalender |
|---|---|
| `GET /api/calendar/events`, `/free-slots` (`routers/calendar.py:58, 73`) | Query-Parameter `calendar`, sonst Standard |
| `query_calendar` (`agent/tools.py:171`) | Tool-Parameter `calendar`, sonst Standard |
| `_free_blocks_by_day` (`agent/tools.py:278`) | Kalender, den `plan_propose` aufgelöst hat |
| Lagebild `_kalender_lines` (`agent/situation_brief.py:122-123`) | Standard |

### 3.3 Datenmodell (eine Migration)

| Tabelle | Änderung |
|---|---|
| `user_setting` | `default_calendar TEXT NOT NULL DEFAULT 'google_calendar'`, `CHECK (default_calendar IN ('google_calendar','caldav'))` |
| `calendar_event` | `provider_meta JSONB NOT NULL DEFAULT '{}'` (CalDAV: `href`, `etag`, `recurring`; Google: `recurring`) |
| `plan` | `calendar TEXT NULL`, `CHECK (calendar IN ('google_calendar','caldav'))`; NULL = Bestandspläne, werden als `google_calendar` behandelt |
| `connection` | keine Schemaänderung; für `connector='caldav'`: `external_account` = Apple-ID, `credentials_enc` = verschlüsseltes JSON `{username, password}`, `config` = `{server_url, principal_url, read_calendars: [url…], write_calendar: url}` |

`calendar_event.calendar_id` speichert bei CalDAV die Collection-URL (Spalte existiert).
Bestandsdaten: vorhandene `calendar_event`-Zeilen sind alle `google_calendar`/`primary` und
bekommen `provider_meta = '{}'`; vorhandene `user_setting`-Zeilen bekommen den Default;
Nutzer ohne `user_setting`-Zeile behandelt der Resolver als `google_calendar`.

**Code-Änderungen am Datenmodell (gehören zu AP 2):**

| Stelle | Änderung |
|---|---|
| `db/models.py` `UserSetting` | Spalte `default_calendar` + `CheckConstraint` in `__table_args__` |
| `db/models.py` `CalendarEvent`, `Plan` | Spalten `provider_meta`, `calendar` (+ `CheckConstraint`) |
| `repositories/user_setting.py` | `UserSettingData.default_calendar`, `_DEFAULT`; neue Upsert-Funktion `set_default_calendar()` (Zeile muss nicht existieren) |
| `repositories/calendar_event.py` `upsert_from_records` | schreibt `calendar_id` und `provider_meta` bei Insert **und** Update |
| `repositories/calendar_event.py` `upsert_kairos_event` | nimmt `calendar_id` und `provider_meta` entgegen; der Sync-Upsert aktualisiert bei Kairos-Terminen `provider_meta` mit (neue ETag), `source` bleibt `kairos` |

### 3.4 Sync-Kern (`src/kairos/calendar/sync.py`)

```python
async def sync_calendar(session, user_id, provider_id: str,
                        window: Window | None = None) -> SyncResult

class SyncResult(TypedDict):
    fetched: int
    upserted: int
    cancelled: int
    failed_calendars: list[str]
    error_code: str | None   # "reauth_required" | "unavailable" | None
```

- Holt Termine über `provider.list_events(window)` (Default −7 bis +83 Tage wie heute,
  `routers/sync.py:157-158`), upsertet nach `(user_id, connector, external_id)` inklusive
  `calendar_id` und `provider_meta`.
- **Lösch-Abgleich:** Zeilen des Providers, die nicht mehr geliefert werden, →
  `status='cancelled'` (gleiche Semantik wie `mark_deleted`). Regeln:
  1. nur für Kalender aus `complete_calendars`, je `(connector, calendar_id)`; ein
     fehlgeschlagener Kalender bleibt unberührt, der Job meldet Teilerfolg;
  2. für beide `source`-Werte (auch extern gelöschte Kairos-Termine);
  3. nicht für Zeilen mit `created_at` nach Abrufbeginn;
  4. nur für Zeilen, die vollständig im um je einen Tag verkleinerten Fenster liegen
     (Ganztags- und schwebende Termine werden serverseitig in der Kalender-Zeitzone
     bewertet, RFC 4791 §9.9, lokal als UTC-Mitternacht gespeichert).
- Der Kern committet selbst, setzt den Verbindungsstatus (Erfolg → `last_ok_at`,
  `ProviderAuthError` → `reauth_required` + `reauth_since`, sonst `last_error`) und hält eine
  Sperre je `(user_id, provider_id)`, die auch der Schreibdienst (§3.5) nimmt.
- Erwartet eine Session mit installiertem RLS-Listener; kennt weder HTTP noch
  `SyncJobRegistry`.
- Router: `POST /api/sync/calendar/sync` mit Body `{"calendar": "google_calendar"|"caldav"|null}`
  ruft den Kern im BackgroundTask; Job-/Cooldown-Logik bleibt im Router.
  `POST /api/sync/google_calendar/sync` bleibt als Alias bis das Frontend umgestellt ist,
  danach entfernen.

### 3.5 Kalender-Schreibdienst (`src/kairos/calendar/write.py`)

```python
async def create_event(session, user_id, req: CreateEventRequest,
                       calendar: str | None) -> CalendarEvent
async def delete_event(session, user_id, event_id: UUID, confirm: bool) -> None
async def replace_event(session, user_id, old: CalendarEvent,
                        req: CreateEventRequest) -> CalendarEvent   # im Herkunftskalender
```

- Einziger Schreibweg für Router, Agent-Tools und die Tools der Workouts-Spec;
  `_create_calendar_event`/`_delete_calendar_event` in `routers/calendar.py` werden dünne
  Hüllen darum. Committet nicht selbst (Harness-v2-Regel: der Bestätigungs-Endpunkt hält
  seine Sperre bis zum eigenen Commit).
- Nimmt die Sync-Sperre aus §3.4, damit ein paralleler Sync einen frisch angelegten Termin
  nicht abgleicht.

---

## 4. CalDAV-Connector (`src/kairos/connectors/caldav/`)

### 4.1 Verbinden

1. Konfigseite → `POST /api/connections/caldav` `{username, password, server_url?}`
   (`server_url` Default `https://caldav.icloud.com`).
2. Backend: Discovery (`current-user-principal` → `calendar-home-set` → Collections mit
   `VEVENT`-Unterstützung) ohne offene DB-Transaktion. Fehlschlag mit 401/403 →
   `400 invalid_credentials`, kein Speichern.
3. Erfolg: Connection anlegen (Upsert-Muster aus `_store_connection`,
   `routers/connections.py:92-131`; alte CalDAV-Zeilen des Nutzers deaktivieren). Wechselt
   die Apple-ID, werden alle `caldav`-Zeilen in `calendar_event` storniert. Antwort enthält
   die Kalenderliste.
4. `PUT /api/connections/caldav/config` `{read_calendars, write_calendar}` — Validierung:
   `write_calendar` muss in der Liste und beschreibbar sein; das Backend nimmt ihn immer in
   `read_calendars` auf (sonst würde der Lösch-Abgleich Kairos-eigene Termine stornieren).
5. Fällt ein Kalender aus `read_calendars` heraus, werden seine Zeilen sofort storniert.
6. `DELETE /api/connections/caldav` → `status='disabled'`, `credentials_enc=NULL`, alle
   `caldav`-Zeilen in `calendar_event` storniert; war `caldav` Standard, fällt der Standard auf
   `google_calendar` zurück (`set_default_calendar`, §3.3).

### 4.2 Lesen

- Pro Kalender in `read_calendars` ein `calendar-query` REPORT mit `time-range` über das
  Fenster. Ein Kalender zählt nur als `complete`, wenn sein Abruf ohne Fehler endet.
- **Wiederkehrende Termine:** standardmäßig **clientseitig** aus dem Master expandiert
  (python-caldav 3.x tut das per `recurring-ical-events`). `<C:expand>` nur, wenn AP 0 belegt,
  dass iCloud Instanzen inklusive überschriebener Instanzen liefert (ein Bericht sagt, iCloud
  liefere nur den Master, §12). `recurring` und `provider_meta.recurring` kommen aus dem
  Master (RRULE/RDATE oder überschriebene Instanzen vorhanden). `external_id` siehe §3.1.
- Ganztägig (`DTSTART;VALUE=DATE`) → `all_day=true`, Grenzen wie beim Google-Normalizer
  (UTC-Mitternacht, Ende exklusiv; fehlt `DTEND`, dauert der Termin einen Tag).
  `TZID`/`VTIMEZONE` → Umrechnung nach UTC; schwebende Zeiten → `app_user.home_timezone`.
- `STATUS:CANCELLED` → `cancelled`, `TENTATIVE` → `tentative`.
- Optimierung (nicht Pflicht für v1): `sync-collection` (RFC 6578) bzw. ctag/ETag, falls
  AP 0 Unterstützung bestätigt; Token in `sync_state`.

### 4.3 Schreiben & Löschen

- **Anlegen:** neue UID (`uuid4@kairos`), `PUT {write_calendar}/{uid}.ics` mit
  `If-None-Match: *` (RFC 4791 §5.3.2); ETag aus der Antwort, fehlt sie oder ist sie schwach,
  per Folge-PROPFIND `getetag` (RFC 4791 §5.3.4); Ergebnis in `provider_meta`.
- **Löschen:** `provider_meta.recurring` → `RecurringNotSupported`; ebenso, wenn eine
  zweite Zeile denselben `href` trägt (Verteidigung in der Tiefe: alle Instanzen einer Serie
  teilen eine Ressource). Sonst `DELETE {href}` mit `If-Match: {etag}`. 412 (Termin extern
  geändert) → einmal neu laden und erneut versuchen; 404 → lokal als gelöscht markieren.
- Externe Termine behalten die bestehende Bestätigungspflicht (`needs_confirmation`). Ob das
  Löschen eines eingeladenen Termins eine Absage an den Organisator auslöst, klärt AP 0
  (§12); trifft es zu, nennt die Vorschau das.

### 4.4 Fehler & Reauth

- 401/403 → `connection.status='reauth_required'`, `reauth_since` setzen (App-spezifisches
  Passwort widerrufen oder Apple-ID-Passwort geändert; Letzteres widerruft laut Apple alle
  app-spezifischen Passwörter); Konfigseite zeigt „neu verbinden“.
- Netzwerk/5xx → `ProviderUnavailable`, `connection.last_error` (fester Text, §7).

---

## 5. Agent

- `query_calendar`, `propose_calendar_event`, `plan_propose` erhalten einen optionalen
  Parameter
  `calendar: {"type": "string", "enum": ["google", "apple"]}` mit der Beschreibung „Nur
  setzen, wenn der Nutzer ausdrücklich einen Kalender nennt; sonst gilt der Standard.“
  Mapping `google → google_calendar`, `apple → caldav` an einer Stelle.
- `plan_propose` speichert den aufgelösten Provider in `plan.calendar`; `plan_commit` hat
  **keinen** Parameter und schreibt in `plan.calendar`.
- `delete_calendar_event`: kein Parameter (Herkunft aus der Zeile).
- `plan_adjust`: schreibt in dieser Spec keine Kalendertermine (Stand `agent/tools.py:372-397`).
  Die Workouts-Spec ändert das (Ersatz-Termine); dann gilt `replace_event` (§3.5, §11).
- **Vorschau:** Bei Bestätigungs-Tools löst der Dispatcher den Kalender beim Erzeugen des
  Proposals auf und schreibt den Provider in die gespeicherten Argumente; Vorschau
  („Termin in Apple Kalender anlegen: …“) und Ausführung nutzen denselben Wert, auch wenn der
  Nutzer zwischendurch den Standard ändert. Dafür braucht `_summarize`
  (`agent/dispatcher.py:56-64`) Session und Nutzer.
- **Lagebild:** Datenstand `Kalender: Apple ✓ (Standard) · Google ✓`; nicht verbundene
  Provider werden nur genannt, wenn sie Standard sind. Die Zeilen „Heute/Morgen“ zählen
  Termine des Standardkalenders.
- Tool-Beschreibungen nennen keinen konkreten Anbieter mehr.

---

## 6. API & Frontend

| Endpunkt | Änderung |
|---|---|
| `GET /api/connections` | zusätzlich `calendar: {default, providers: [{id, label, status, account}]}` |
| `GET/PATCH /api/settings/calendar` | neu: `{default_calendar}` (erste `user_setting`-Schreib-API, bewusst schmal, Upsert) |
| `GET /api/calendar/events`, `/free-slots` | optionaler Query-Parameter `calendar` |
| `POST /api/calendar/events` | optionales Feld `calendar` |
| `POST /api/sync/calendar/sync` | neu (siehe §3.4) |
| `POST/PUT/DELETE /api/connections/caldav[...]` | neu (siehe §4.1) |

**Frontend:**
- Konfigseite (`/account`): Abschnitt „Kalender“ mit Standard-Dropdown (nur verbundene
  Provider wählbar), Apple-Verbinden-Formular mit Hinweis auf App-spezifisches Passwort
  (Link `appleid.apple.com`, Hinweis auf Zugriff auf Mail/Kontakte/Kalender und Widerruf),
  danach Kalenderauswahl (Lesen: Mehrfachauswahl, Schreiben: Einfachauswahl, der
  Schreibkalender ist immer als gelesen markiert), Status/„neu verbinden“/„trennen“.
- `/calendar`: zeigt den Standardkalender; Umschalter nur sichtbar, wenn beide verbunden
  sind. **Alle** Aktionen der Seite übergeben den angezeigten Kalender als `calendar`:
  Terminliste, „Freie Slots vorschlagen“ und deren Bestätigung, das Anlege-Formular
  (`calendar/+page.server.ts:31, 59, 83, 96`) und „Synchronisieren“.
- `/sync`, `+layout.svelte`: alle `'google_calendar'`-Literale durch die
  `calendar`-Struktur aus `/api/connections` ersetzen.

---

## 7. Sicherheit

- Das App-spezifische Passwort gibt Zugriff auf **Mail, Kontakte und Kalender** des
  iCloud-Kontos („access information like mail, contacts, and calendars“,
  support.apple.com/102654). Gespeichert nur verschlüsselt (Envelope, DEK des Nutzers), nie
  geloggt, nie an das LLM, nie im Chat. Der Onboarding-Text sagt das offen und nennt den
  Widerruf unter `appleid.apple.com`.
- **Fehlertexte:** Handler-Ausnahmen gehen heute als `"Fehler: {exc}"` in den LLM-Kontext
  und die gespeicherte Konversation (`agent/orchestrator.py:267-268`,
  `routers/agent.py:195`) und als `str(exc)` an die UI (`routers/sync.py:406`). Provider-
  Ausnahmen tragen deshalb feste Meldungen ohne URL (enthält die Konto-ID) und ohne
  Upstream-Text; Details nur serverseitig auf WARNING, ohne Request-/Response-Body.
- **python-caldav-Logging:** Die Bibliothek loggt auf DEBUG jede Anfrage samt Body
  (`caldav/base_client.py`, „sending request“) und schreibt mit `PYTHON_CALDAV_COMMDUMP` den
  kompletten Austausch in Temp-Dateien (`caldav/lib/error.py`). Logger `caldav` auf
  mindestens WARNING; `PYTHON_CALDAV_COMMDUMP` wird im Deployment nie gesetzt.
- Alle neuen Endpunkte und der Sync-Kern laufen mit `install_rls_listener`; eine künftige
  Aktions-Registry (§8) installiert ihn im Wrapper, bevor sie `sync_calendar` aufruft.
- `06-sicherheit-und-datenschutz.md` §„Apple/iCloud“ wird vom Zielbild auf Ist-Stand gezogen;
  §5.2 („Tokens, keine Passwörter“) gilt für CalDAV nicht mehr und wird angepasst.

---

## 8. Schnittstelle zum geplanten Scheduler (nicht im Scope)

Abgestimmte Richtung: **ein generischer Scheduler**, keine dienstspezifischen Jobs. Ein Job
ist `(user_id, aktion, parameter, zeitplan)`, z. B. Kalender-Sync mit Provider oder
Agent-Lauf mit Prompt.

**Empfehlung für die Scheduler-Spec:** Aktionen nicht als HTTP-Aufruf der Frontend-API
ausführen, sondern über eine Aktions-Registry, die dieselben Service-Funktionen aufruft wie
die Endpunkte (`calendar.sync → sync_calendar(...)`, `garmin.backfill → ...`,
`agent.run → Orchestrator mit Prompt`). Gründe:
- Jeder Endpunkt hängt an `current_user` (Session-Cookie, `auth/deps.py:8-14`); ein
  HTTP-Scheduler bräuchte Service-Token plus Nutzer-Impersonation.
- Sync-Endpunkte antworten `202` und arbeiten im BackgroundTask (`routers/sync.py:137,
  169-175`) — der Scheduler sähe das Ergebnis nicht.
- Generik bleibt gleich: Registry-Eintrag = Aktionsname + Parameterschema; das Frontend kann
  aus demselben Schema das Formular erzeugen.

**Was diese Spec dafür liefert:** `sync_calendar(session, user_id, provider_id, window)` als
HTTP-freie Funktion, die selbst committet, den Verbindungsstatus pflegt, eine Sperre je
`(user_id, provider_id)` hält und ein `SyncResult` zurückgibt (§3.4). Der Registry-Wrapper
öffnet die Session und installiert den RLS-Listener. **Offen für die Scheduler-Spec:**
`SyncJobRegistry` und die Sperre sind In-Process-`asyncio.Lock`s — läuft der Scheduler in
einem eigenen Prozess, schützen sie nicht gegen einen parallelen Button-Klick (z. B.
Postgres-Advisory-Lock je `(user_id, connector, kind)`). Scheduler-Läufe erscheinen nicht
auf der `/sync`-Seite, solange Jobs nur im `SyncJobRegistry` stehen.

---

## 9. Arbeitspakete

| AP | Inhalt | Abnahme |
|---|---|---|
| **0** | **CalDAV-Verifikation** mit iCloud-Konto von Nutzer 0 (Skript unter `scripts/`, Zugangsdaten nur lokal): alle Punkte aus §12. Anonymisierte Fixtures nach `tests/fixtures/caldav/`. | jeder Punkt aus §12 belegt oder widerlegt und hier nachgetragen; `04` §4 korrigiert; Bibliotheksversion gepinnt |
| 1 | Protokoll, Typen, Ausnahmen; Google-Provider aus bestehendem Code (inkl. `recurring` aus `recurringEventId`) | bestehende Kalendertests grün, keine Verhaltensänderung |
| 2 | Migration (`default_calendar`, `provider_meta`, `plan.calendar`); ORM-Modelle und Repository-Änderungen aus §3.3 inkl. `set_default_calendar`; Resolver; `list_between(connector=…)` mit allen vier Aufrufern aus §3.2; Schreibdienst §3.5; Router + Planung auf Resolver | 413+ Tests grün; Google-Pfad unverändert; Test: Nutzer ohne `user_setting`-Zeile → `google_calendar` |
| 3 | Sync-Kern herauslösen, `POST /api/sync/calendar/sync`, Lösch-Abgleich, Verbindungsstatus | Integrationstests: extern gelöschter Termin → `cancelled`; extern gelöschter Kairos-Termin → `cancelled`; vorhandener Kairos-Termin überlebt; fehlgeschlagener Kalender storniert nichts; während des Syncs angelegter Termin bleibt |
| 4 | CalDAV-Provider (Lesen) gegen Fixtures | Normalizer-Tests auf echten AP-0-Shapes; Serie mit Master vor dem Fenster und überschriebener Instanz; Erstinstanz trägt `UID#DTSTART` |
| 5 | CalDAV-Provider (Anlegen/Löschen) + Verbinden/Config/Trennen-Endpunkte | Roundtrip gegen echtes iCloud manuell, Fixtures automatisiert; Test: Instanz einer Serie löschen → 409, kein `DELETE` abgesetzt; Schreibkalender landet immer in `read_calendars` |
| 6 | Settings-API, Agent-Parameter, `plan.calendar`, Vorschau im Dispatcher, Lagebild, Tool-Texte; Eval-Fake auf Provider-Ebene (`FakeCalendarProvider` über den Resolver) statt Patch von `_create_calendar_event` | Dispatcher-Tests gegen echte `TOOLS_BY_NAME`; Eval-Fall „trag das in meinen Apple Kalender ein“; Eval setzt keinen HTTP-Aufruf an einen Kalender ab; Test: `ProviderAuthError` erreicht den LLM-Kontext nur mit fester Meldung |
| 7 | Frontend: Konfigseite, Kalenderansicht (alle Aktionen mit `calendar`), Literale entfernen | `npm run check` 0/0, Vitest grün, manueller Test auf iPhone |
| 8 | Doku: `01`, `04` (§4.1 Discovery, §4.2 ctag-Poll, §4.3 RRULE-JSONB und `dedup_group` entfallen zugunsten Import-Expansion und Auswahlregel), `06` (§3 Apple, §5.2), `08`, HANDOVER; Workouts-Spec nach §11 | `rg -n "Google-Termin\|Google-Kalendertermin" docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` liefert nur noch als historisch markierte Stellen |

Abschluss wie bisher mit Whole-Branch-Review (Kompositionsfehler zwischen APs, vgl.
HANDOVER-Lektionen) und einem Real-Data-Lauf. Bekannte Nahtstellen, auf die das Review
achten soll: AP 3 ↔ AP 5 (Lesemenge vs. Schreibkalender), AP 2/6 ↔ AP 7 (`calendar`-Parameter
der Kalenderseite), AP 6 ↔ Eval-Suite, diese Spec ↔ Workouts-Spec (§11).

---

## 10. Risiken & offene Punkte

- **iCloud-Verhalten unverifiziert** — alle Punkte in §12; genau dafür AP 0 vor jeder
  Implementierung.
- **Gleiche UID in zwei Kalendern:** `uq_calendar_event (user_id, connector, external_id)`
  (`db/models.py:132`) erlaubt das nicht. Für iCloud berichtet python-caldav, dass eine UID
  nur in einem Kalender liegen kann; bei generischem CalDAV müsste `external_id` die
  Collection enthalten.
- **Google-Kalender-Scope beim Login** wird auch von Apple-Nutzern angefragt; optionaler
  Scope wäre eine eigene Auth-Änderung (nicht in dieser Spec).
- **Rate-Limits von iCloud** sind nicht dokumentiert; Sync nur auf Anforderung bzw. später
  per Scheduler mit moderatem Intervall (≥ 15 min).
- `plan_commit`-Teilfehler (Termine 1..N−1 angelegt, lokale Zeilen zurückgerollt,
  HANDOVER) gilt für CalDAV genauso; die Behebung steht in der Workouts-Spec D.6
  („Keine Exception bei Element-Fehlern“).
- **Offene Nutzerentscheidungen (Review 2026-10-14):** Instanzen wiederkehrender
  Apple-Termine in v1 ablehnen oder per EXDATE unterstützen; app-spezifisches Passwort
  akzeptieren oder zuerst Apples App-Autorisierung prüfen; Reihenfolge gegenüber der
  Workouts-Spec (§11).

---

## 11. Abgleich mit der Workouts-Spec

Die Workouts-Spec legt Kalendertermine nicht nur in `plan_commit` an, sondern auch beim
Terminieren, Verschieben, Ändern und Entfernen von Workouts und in `plan_adjust`
(`2026-10-07-aktivitaeten-und-workouts-design.md:19-20, 956, 988, 1015-1021, 1049, 1094,
1180`). Für alle diese Stellen gilt:

| Workouts-Spec | Mit dieser Spec |
|---|---|
| „Google-Termin anlegen“ (`workout_create`, `workout_schedule`, `plan_commit`) | `create_event` (§3.5) mit dem aufgelösten Kalender; bei `plan_commit` `plan.calendar` |
| „Google-Termine ersetzen (löschen + neu anlegen)“ (`workout_update`, `workout_schedule(replace_schedule_id)`, `plan_adjust`) | `replace_event` — der neue Termin entsteht im Kalender des alten |
| „verknüpften Google-Termin löschen“ (`workout_unschedule`, `workout_delete`) | `delete_event` nach Herkunft |
| D.5 „Google nicht verbunden“ | „Kalender nicht verbunden“ (`CalendarNotConnected` für den aufgelösten Kalender) |
| Tool-Beschreibungen und Eval-Fälle 22–26 („Google-Termin“) | „Kalendertermin“ |

Beide Specs schreiben `plan_commit` um. Empfohlene Reihenfolge: diese Spec zuerst, damit die
Workouts-Spec direkt auf den Schreibdienst aufsetzt (Nutzerentscheidung offen, §10).

---

## 12. Fakten, die AP 0 klären muss

Stand der Belege (Review 2026-10-14):

| # | Frage | Stand |
|---|---|---|
| 1 | Discovery: `current-user-principal` (Pfad `/<id>/principal/`?), `calendar-home-set` auf `pNN-caldav.icloud.com`?, Redirects, Umgang von python-caldav damit | Sekundärquellen stützen die Hypothese in §2; nicht primär belegt |
| 2 | Kalenderliste: `supported-calendar-component-set` (Erinnerungslisten), Schreibrecht über `current-user-privilege-set`, geteilte/abonnierte/Geburtstags-Kalender | offen |
| 3 | `calendar-query` mit `time-range`: wird eine Serie geliefert, deren Master vor dem Fenster beginnt? (RFC 4791 §7.4 verlangt es) | offen |
| 4 | `<C:expand>`: Instanzen statt Master? überschriebene Instanzen? `RECURRENCE-ID` der Erstinstanz? | ein Bericht: iCloud liefert nur den Master (python-caldav Issue #3); offen |
| 5 | `sync-collection` (RFC 6578) und `getctag`: unterstützt, Token-Lebensdauer | keine belastbare Quelle |
| 6 | `PUT {uid}.ics` mit `If-None-Match: *`: akzeptiert, `Location`-Umschreibung, ETag im Header (stark/schwach) | RFC 4791 §5.3.4 erlaubt fehlende ETag; iCloud offen |
| 7 | `DELETE` mit `If-Match`: 412 bei veralteter ETag, 404 bei schon gelöschtem Termin | offen |
| 8 | Löschen eines eingeladenen Termins: Absage an den Organisator? (für Google ohne `sendUpdates`, `google_calendar/client.py:109-117`, ebenso prüfen) | offen |
| 9 | Gleiche UID in zwei Kalendern abgelehnt? | python-caldav Issue #3: ja; offen |
| 10 | Ganztags-, `TZID`- und schwebende Beispiele; `calendar-timezone` der Kalender | offen |
| 11 | Fehlercodes: widerrufenes Passwort (401 oder 403), Konto ohne 2FA, Drosselung (429/503, `Retry-After`) | offen |
| 12 | Apples App-Autorisierung für Drittanbieter-Apps (support.apple.com/121539, seit 2025-10-21): für Kairos nutzbar? | offen |
| 13 | python-caldav-Version (3.4.0 aktuell) und Abhängigkeiten (`niquests`, `lxml`, `recurring-ical-events`, `dnspython`, `pyyaml`) gegen den bestehenden Stack; sync oder `aio` | offen |

Belegt und ohne AP 0 verwendbar: App-spezifisches Passwort erfordert 2FA, gibt Zugriff auf
Mail, Kontakte und Kalender, maximal 25 aktiv, Wechsel des Hauptpassworts widerruft alle
(support.apple.com/102654); `If-None-Match: *` beim Anlegen (RFC 4791 §5.3.2); Pflichten des
Servers bei `<C:expand>` (RFC 4791 §9.6.5).
