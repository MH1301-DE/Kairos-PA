# Phase 3 — Kalender: Design-Spezifikation

> Autonome Session (volle Entscheidungsfreigabe durch den Nutzer, siehe
> `docs/HANDOVER.md`). Offene Roadmap-Fragen vor Phase 3 (`docs/08-roadmap.md`,
> Abschnitt 3) wurden hier selbstständig beantwortet — jede Entscheidung ist
> unten explizit mit Begründung dokumentiert, keine stillschweigenden Annahmen.

## Ziel

Ein Google-Kalender-Termin kann von Kairos gelesen, vorgeschlagen, angelegt,
geändert und gelöscht werden — nachvollziehbar in der Kairos-UI und korrekt im
echten Google Calendar des Nutzers. Das ist die Abnahme aus dem Roadmap
(Phase 3), reduziert auf einen einzelnen Kalender-Provider (siehe
Scope-Entscheidung 1).

## Scope-Entscheidungen (autonom, mit Begründung)

**1. Nur Google Calendar für dieses MVP — kein CalDAV/iCloud-Connector.**
Nutzer 0 (der Betreiber) authentifiziert sich bereits über Google OAuth für den
Login; ein CalDAV/iCloud-Connector betrifft laut Roadmap explizit den
Apple-Watch-Nutzer aus Phase 6+ ("Nutzer 2–5 gestaffelt"). Der Roadmap-Leitsatz
selbst ("erst wenn eine Phase für einen Nutzer stabil läuft, kommen weitere
dazu") rechtfertigt, CalDAV auf den Zeitpunkt zu verschieben, an dem ein
Nutzer mit iCloud-Kalender tatsächlich onboarded wird. Der `Connector`-Protokoll-
Vertrag (`src/kairos/connectors/base.py`, bereits vorhanden) ist provider-
agnostisch genug, dass ein CalDAV-Connector später ohne Kernumbau ergänzt
werden kann.

**2. Google-OAuth-Token wird wiederverwendet, kein separater Consent-Screen.**
Wichtiger Fund beim Codelesen: `src/kairos/auth/google.py`s Login-Flow fordert
bereits `SCOPES = "openid email profile https://www.googleapis.com/auth/calendar"`
mit `access_type=offline` + `prompt=consent` an — der Kalender-Scope wird also
bei JEDEM Login bereits mit angefragt. Das beantwortet die roadmap-eigene
Warnung ("Google-OAuth-Verifizierung … der einzige Punkt, der eine geplante
Integration ganz kippen könnte", `08-roadmap.md` Frage 7) positiv: die
OAuth-App ist technisch bereits kalenderfähig. **Die eigentliche Lücke:**
`callback()` verwirft `tokens` (inkl. `refresh_token`) nach der einmaligen
Login-Nutzung sofort — nichts wird persistiert. Diese Spec schließt genau
diese Lücke (siehe Task 1), statt eine neue OAuth-UI zu bauen.

**3. `primary_write_calendar` = Googles `"primary"`-Kalender, keine Auswahl-UI.**
Für ein Einzelnutzer-MVP ist ein Kalender-Auswahldialog Overhead ohne
Gegenwert. `"primary"` ist eine feste, dokumentierte Google-Calendar-API-
Konstante (kein Lookup nötig). Eine spätere Auswahl-UI ist eine rückwärts-
kompatible Erweiterung (neue Spalte in `user_setting`, Default bleibt
`"primary"`), kein Architektur-Risiko.

**4. Kein Watch-Channel-Push (Google-Webhooks) — nur Fallback-Poll.**
Watch-Channels brauchen eine öffentlich erreichbare HTTPS-URL für Googles
Push-Benachrichtigungen. Genau wie das bereits dokumentierte Produktions-
Deployment-Gap (Caddy/Dockerfiles, siehe `docs/HANDOVER.md`) existiert diese
Infrastruktur noch nicht. Fallback-Poll (periodischer `syncToken`-Abgleich,
identisch zum bestehenden Garmin-Backfill-Job-Muster) deckt die Abnahme
vollständig ab und ist bereits im Roadmap selbst als Fallback vorgesehen, nicht
als Notlösung.

**5. Gmail bleibt außen vor.** Gehört laut Checkliste zu Phase 6, nicht Phase 3
— hier nur der Vollständigkeit halber bestätigt, keine eigene Entscheidung
nötig.

**6. Freizeitberechnung ist eine reine Funktion, keine Datenbank-Kennzahl.**
Analog zum Metrics-Layer-Muster aus Phase 2 (`src/kairos/metrics/formulas/`):
Termine + Präferenzen rein, freie Blöcke raus, zur Abfragezeit berechnet statt
vorab materialisiert — es gibt keinen Grund, hier vom bewährten Muster
abzuweichen.

**7. Proposal-Bestätigung ist ein manueller UI-Flow, kein Agent-Tool.** Phase 4
(Agent, Tool-Calling) kommt erst danach — Phase 3 baut die Datenbank- und
API-Schicht, die Phase 4 später als Tool aufruft, testet sie aber über eine
von Menschen bedienbare UI (passend zur Roadmap-Abnahme: "Ein Termin kann
angelegt, geändert und gelöscht werden").

## Datenmodell

### Neue Tabelle: `calendar_event`

```
id            UUID PK
user_id       UUID FK app_user, RLS-Spalte
connector     TEXT NOT NULL            -- 'google_calendar' (einziger Wert vorerst)
external_id   TEXT NOT NULL            -- Google Event-ID; Upsert-Schlüssel
calendar_id   TEXT NOT NULL DEFAULT 'primary'
summary       TEXT
description   TEXT
location      TEXT
start_at      TIMESTAMPTZ NOT NULL
end_at        TIMESTAMPTZ NOT NULL
all_day       BOOLEAN NOT NULL DEFAULT false
status        TEXT NOT NULL DEFAULT 'confirmed'   -- confirmed | tentative | cancelled
source        TEXT NOT NULL DEFAULT 'external'    -- 'external' (von Google gelesen) | 'kairos' (von Kairos angelegt)
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()

UNIQUE (user_id, connector, external_id)   -- Dedup-Schlüssel, siehe unten
FORCE ROW LEVEL SECURITY (Muster wie alle anderen Tenant-Tabellen)
```

**Dedup-Strategie:** Kairos-geschriebene Termine bekommen ihre `external_id`
sofort nach der erfolgreichen Google-API-Antwort zugewiesen (nicht erst beim
nächsten Sync). Der nächste Poll-Zyklus sieht dieselbe `external_id` wieder und
macht ein `ON CONFLICT DO UPDATE` statt eines Inserts — kein Doppel-Eintrag,
keine Sync-Schleife, kein Fuzzy-Matching nötig. Identisch zum bereits
etablierten `on_conflict_do_update`-Muster in
`src/kairos/repositories/canonical.py`.

### Bestehende Tabellen — wiederverwendet, nicht neu erfunden

- **`connection`**: neue Zeile mit `connector='google_calendar'`,
  `credentials_enc` = envelope-verschlüsselter `refresh_token` (exakt das
  Muster, das `_store_connection` in `src/kairos/routers/connections.py` für
  Garmin bereits nutzt — `kek_from_settings`/`wrap_dek`/`encrypt` sind
  fertige, getestete Bausteine).
- **`sync_state`**: hat bereits eine `sync_token`-Spalte
  (`src/kairos/db/models.py:134`) — exakt das Feld, das Googles inkrementelles
  Sync-Protokoll braucht. `(user_id, connector='google_calendar',
  kind='events')` als Schlüssel, kein Schema-Änderung nötig.
- **`user_setting`**: um vier nullable Spalten erweitert:
  `work_hours_start` (Time), `work_hours_end` (Time),
  `calendar_buffer_minutes` (SmallInteger, Default 15),
  `min_free_block_minutes` (SmallInteger, Default 30). Sinnvolle Defaults, ein
  Nutzer kann sie später über eine Einstellungen-Seite ändern (nicht Teil
  dieses Plans — YAGNI, es gibt noch keine Einstellungen-UI im ganzen Projekt).

## Backend-Architektur

### `src/kairos/connectors/google_calendar/`

Spiegelt exakt die Struktur von `connectors/garmin/`:

- **`client.py`** — dünner `httpx`-Wrapper um die Google Calendar API v3
  (`GET/POST/PATCH/DELETE https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events...`),
  inkl. Token-Refresh-Logik (`refresh_token` → neuer `access_token` via
  `https://oauth2.googleapis.com/token`, analog zum bestehenden
  Token-Austausch in `auth/google.py`). Exceptions für erwartbare Fehlerfälle
  (`TokenExpired`, `UpstreamUnavailable`), analog zu
  `connectors/garmin/client.py`s `InvalidCredentials`/`UpstreamUnavailable`.
- **`connector.py`** — `GoogleCalendarConnector`, implementiert das
  `Connector`-Protokoll (`fetch`/`normalize`/`write_back`) aus
  `connectors/base.py`. `write_back` ist hier *nicht* der No-Op-Stub, den
  Garmin hat — echtes Erstellen/Ändern/Löschen von Events.

### `src/kairos/calendar/free_time.py`

Reine Funktion: `compute_free_blocks(events: list[CalendarEventRow], window: Window, prefs: CalendarPrefs) -> list[FreeBlock]`.
Sortiert Termine nach Startzeit, läuft das Fenster ab, sammelt Lücken ≥
`min_free_block_minutes` außerhalb bestehender Termine (± `calendar_buffer_minutes`
Puffer) und innerhalb `work_hours_start`/`work_hours_end`, falls gesetzt.

### `src/kairos/routers/calendar.py`

- `GET /api/calendar/events?from=&to=` — gelesene + geschriebene Termine im
  Zeitraum (aus `calendar_event`, nicht live von Google — Sync-Job hält die
  Tabelle aktuell, analog zum bestehenden Metrics-Read-Pfad).
- `GET /api/calendar/free-slots?from=&to=&duration_minutes=` — ruft
  `compute_free_blocks` auf, liefert Vorschlagskandidaten.
- `POST /api/calendar/events` — legt einen Termin an: schreibt zuerst über
  `GoogleCalendarConnector.write_back` an Google, dann sofort einen
  `calendar_event`-Datensatz mit der von Google zurückgegebenen `external_id`
  und `source='kairos'` (Dedup-Grundlage, siehe oben).
- `PATCH /api/calendar/events/{id}` / `DELETE /api/calendar/events/{id}` —
  analog, schreibt erst an Google, dann lokal nach.

### Sync-Job

Erweitert den bestehenden `src/kairos/routers/sync.py`-Mechanismus (gleicher
`SyncJobRegistry`/`SyncJob`-Ledger-Ansatz wie Garmin) um
`connector='google_calendar'`, `kind='events'`. Nutzt `sync_state.sync_token`:
erster Lauf ohne Token = Vollsync + Token merken; jeder weitere Lauf nutzt
Googles inkrementelles `syncToken`-Protokoll (nur Deltas, per Google-API-
Vertrag deutlich günstiger als ein Vollabgleich).

### Token-Persistierung (Nachrüstung in `auth/google.py`)

`callback()` bekommt eine zusätzliche, kleine Ergänzung: nach dem bestehenden
`AppUser`-Upsert wird — analog zu `_store_connection` in
`routers/connections.py` — eine `connection`-Zeile mit
`connector='google_calendar'` und dem verschlüsselten `refresh_token`
angelegt/aktualisiert. Kein neuer Endpunkt, keine neue UI — die Ergänzung
läuft bei jedem Login automatisch mit.

## Frontend

- **`/calendar`** (neue SvelteKit-Route, `web/src/routes/calendar/`) — nutzt
  das in der vorherigen Session etablierte Design-System (`app.css`-Tokens,
  `.tile`/`.btn`/`.field`-Klassen), keine neue visuelle Sprache.
  - Liste der nächsten Termine (aus `GET /api/calendar/events`).
  - Freie-Slots-Anzeige für einen wählbaren Zeitraum
    (`GET /api/calendar/free-slots`), mit einem "Vorschlagen"-Formular
    (Titel, Dauer) und Bestätigen-Button pro Slot, der `POST
    /api/calendar/events` auslöst.
  - Löschen/Ändern über einfache Inline-Aktionen an bestehenden Terminen.
- Navigation (`+layout.svelte`) bekommt einen vierten Link "Kalender".

## Testing-Strategie

- Unit-Tests für `compute_free_blocks` (reine Funktion, viele Randfälle:
  Termine am Rand des Fensters, Ganztags-Termine, leeres Fenster, Puffer-
  Überlappung) — Muster wie die bestehenden `metrics/formulas/`-Tests.
- Backend-Router-Tests für `calendar.py` (gemockter `GoogleCalendarConnector`,
  analog zu `test_connections_router.py`).
- Integrationstest für den Dedup-Pfad (Kairos legt Termin an → Sync-Lauf sieht
  dieselbe `external_id` erneut → Update statt Duplikat), analog zum
  Garmin-Duplikat-Test aus dem Dashboard-Frontend-Fix-Wave
  (`tests/test_connections_integration.py`).
- Frontend: Vitest-Komponententests für die Slot-Liste/Formular-Logik;
  **kein** neuer Playwright-E2E-Test in diesem Plan — die Kalender-Seite hat
  keine vergleichbar verzweigte Logik wie der Onboarding-MFA-Retry-Flow, der
  die einzige E2E-Investition im Dashboard-Frontend-Plan war (bewusste
  Konsistenz mit dieser bereits getroffenen Entscheidung).

## Global Constraints (gelten für jeden Task dieses Plans)

- `install_rls_listener(session, user_id)` auf jeder Session, die
  `calendar_event`/`connection`/`sync_state`/`user_setting` liest oder
  schreibt (CLAUDE.md, nicht verhandelbar).
- Backend: `ruff` (line-length 100) + `mypy --strict`, conventional commits.
- Frontend: Svelte-5-Runes-Syntax, `credentials: 'include'` auf jedem Fetch,
  neue Seiten nutzen die bestehenden `app.css`-Design-Tokens statt eigener
  Farben/Abstände.
- Google-API-Antworten werden nie ungeprüft vertraut — Felder wie `start`
  können `date` (Ganztags) oder `dateTime` (Uhrzeit) sein; beide Fälle müssen
  explizit behandelt werden (kein Blindzugriff auf `dateTime`).
- Kein Watch-Channel/Webhook-Code in diesem Plan (siehe Scope-Entscheidung 4)
  — nur Poll-basierter Sync.

## Abnahmekriterien (aus Roadmap übernommen, an reduzierten Scope angepasst)

Ein Termin kann über die Kairos-UI vorgeschlagen und bestätigt werden, taucht
danach korrekt im echten Google Calendar des Nutzers auf, und eine Änderung
oder Löschung in Kairos spiegelt sich ebenso im echten Kalender. Ein erneuter
Sync-Lauf erzeugt keine Duplikate (verifiziert per Integrationstest, siehe
Testing-Strategie).
