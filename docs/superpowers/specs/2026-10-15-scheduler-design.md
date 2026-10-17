# Generischer Scheduler — Design-Spec

| | |
|---|---|
| **Datum** | 2026-10-15 |
| **Status** | Nutzerentscheidungen vom 2026-10-14 eingearbeitet; Ist-Stand am Code geprüft (Stand `78c4ac6`). Offene Fragen an Max in §14. |
| **Baut auf** | Agent-Harness v2 (`2026-10-05-agent-harness-v2-design.md`) · Kalender-Provider/CalDAV (`2026-10-14-kalender-provider-caldav-design.md`, Fassung aus PR #3, §8 „Schnittstelle zum geplanten Scheduler“) · ADR-0001, ADR-0003 · Brainstorming-Entscheidungen D29–D34 (`2026-10-13-brainstorming-entscheidungen.md`, Branch `claude/stufe1-spec-brainstorming`) |
| **Ersetzt** | Zielbild „Scheduler (arq)“ in `01-architektur.md` §5.1 und `04-integrationen.md` §6, auskommentierte `worker`/`scheduler`-Skizze in `deploy/docker-compose.yml:109-116` (ADR-0007 in AP 8) |
| **Nicht im Scope** | siehe §13 |

---

## 0. Zusammenfassung

Der Nutzer legt auf einer neuen Seite **„Scheduler“** Jobs an: einen Zeitplan und eine
Kette fest definierter Aktionen mit festen Parametern, z. B. „täglich 08:00 Garmin-Sync,
Kalender-Sync, dann den Agenten fragen: Was gibt es Neues, was schlägst du für heute vor?“
oder „sonntags 18:00 Wochenanalyse“.

1. **Aktions-Registry** (§5): vier fest definierte Aktionen (`garmin.sync`,
   `calendar.sync`, `metrics.recompute`, `agent.prompt`), je Name + Pydantic-
   Parameterschema + HTTP-freie Service-Funktion. Das Frontend erzeugt das Formular aus
   dem Schema.
2. **In-Process-Loop** im FastAPI-`lifespan` (§3): alle 30 s fällige Jobs aus der DB
   holen und ausführen. Teilt Locks und Cooldowns mit den Sync-Buttons, weil er im selben
   Prozess läuft. Linux-cron wird verworfen (§2).
3. **Zeitpläne** als Liste von Cron-Ausdrücken einer eingeschränkten Teilmenge + Zeitzone
   (Default `Europe/Berlin`), eigener kleiner Rechner mit definierter Sommerzeit-Regel
   (§7.2). Die UI bietet nur Presets.
4. **Garmin inkrementell** (§6): der Scheduler übergibt je Datenart den Start
   `backfill_complete_to − 1 Tag` und das Ende „morgen 00:00 UTC“; ein neuer Modus in
   `SyncService` umgeht die Abdeckungslogik, die heute einen zweiten Lauf am selben Tag
   verschluckt und den aktuellen Tag nie holt.
5. **Agent-Schritt** (§8): `run_turn` in einer festen Konversation je Job; der Kontext
   wird per `conversation.compacted_through_seq` zurückgesetzt (Default: vor jedem Lauf,
   die letzte Antwort geht als Zitat in den nächsten Prompt), vorher werden
   Nutzeraussagen wie heute als Erinnerungen gesichert.
6. **Zwei Tabellen** (§4): `scheduled_job`, `scheduled_job_run`, beide mit RLS. Fällige
   Jobs aller Nutzer findet eine `SECURITY DEFINER`-Funktion, die nur IDs liefert.

---

## 1. Entscheidungen

### 1.1 Mit dem Nutzer abgestimmt (2026-10-14)

| Frage | Entscheidung |
|---|---|
| Aufrufart | Aktions-Registry mit HTTP-freien Service-Funktionen, kein HTTP-Aufruf eigener Endpunkte (CalDAV-Spec §8) |
| Ausführungsort | In-Process-Loop im FastAPI-`lifespan`; Linux-cron bewertet und verworfen (§2) |
| Zeitpläne | wiederkehrend: jeden Freitag, jeden Sonntag, täglich um 8 Uhr, mehrmals täglich (feste Uhrzeiten oder alle N Minuten/Stunden). Speicherung als Cron-Ausdruck + Zeitzone (Default `Europe/Berlin`); die UI bietet Presets statt roher Cron-Syntax |
| Aktionen v1 | fest definiert: `garmin.sync`, `calendar.sync`, `metrics.recompute`, `agent.prompt` (fester Prompt-Text) |
| Ketten | geordnete Schrittliste, sequenziell, Abbruch beim ersten Fehler; keine Verzweigungen |
| Bedingung „nur bei neuen Daten“ | entfällt; der Agent-Schritt läuft immer |
| Ziel der Agent-Antwort | eine feste Konversation je Job; ihr Kontext wird von Zeit zu Zeit geleert |
| Konfiguration | eigene Frontend-Seite „Scheduler“ |
| Garmin-Zeitraum | der Scheduler übergibt den Startwert aus dem letzten erfolgreichen Lauf, statt jedes Mal das Default-Fenster zu prüfen |

### 1.2 In dieser Spec festgelegt

| Thema | Festlegung | Begründung |
|---|---|---|
| Zeitplan-Speicherung | `cron_exprs text[]` (1–6 Ausdrücke) statt eines einzelnen Ausdrucks | „08:00 und 19:30“ ist mit einem Cron-Ausdruck nicht darstellbar; die Liste bleibt Cron-Syntax |
| Cron-Teilmenge | Minute und Stunde: Zahl, Liste, Bereich, `*/N`, `A-B/N`; Tag und Monat nur `*`; Wochentag: `*`, Zahl, Liste, Bereich. `*/N` bei Minuten nur für Teiler von 60, bei Stunden nur für Teiler von 24 | deckt alle Presets ab; `*/45` hieße in Cron „:00 und :45“, nicht „alle 45 Minuten“, und wird deshalb abgelehnt |
| Cron-Rechner | eigenes Modul mit `zoneinfo`, keine Bibliothek | eingeschränkte Teilmenge, Sommerzeit-Regel selbst definiert und getestet, keine neue Abhängigkeit; Bibliotheken (z. B. `croniter`, `cronsim`) erst, wenn rohe Cron-Syntax nötig wird |
| Tick | 30 s | Genauigkeit ±30 s reicht für Syncs und Briefings; eine Abfrage pro Tick auf einen Index |
| Verpasste Läufe | einmal nachholen (Trigger `catch_up`), danach nächster regulärer Termin | Nutzerentscheidung „einmal nachholen, nicht alle“ |
| Überlappung desselben Jobs | Termin wird übersprungen (Lauf mit Status `skipped`, Grund `overlap`) | Nutzerentscheidung |
| Mehrere Jobs desselben Nutzers gleichzeitig fällig | nacheinander; ein fälliger Job wartet bis zum nächsten Tick, wenn für den Nutzer schon ein Lauf aktiv ist | verhindert parallele Garmin-Zugriffe desselben Kontos |
| Cooldown- oder Lock-Treffer | Schritt `skipped`, Kette läuft weiter | die Daten sind dann gerade frisch geholt worden; „übersprungen“ ist kein Fehler (Nutzerentscheidung) |
| Mindestabstand | `garmin.sync` ≥ 60 min, `agent.prompt` ≥ 60 min, `calendar.sync` ≥ 15 min, `metrics.recompute` ≥ 15 min; geprüft beim Speichern | Garmin: Cooldown 300 s und Cloudflare-Vorfall (`routers/sync.py:45-49`), D29 schlägt „tagsüber alle 2 h“ vor; Kalender: CalDAV-Spec §10 „≥ 15 min“; Agent: Kosten |
| Agent-Schritte je Job | höchstens einer | eine Konversation, eine Antwort je Lauf |
| Tageslimit | höchstens 12 geplante Agent-Schritte je Nutzer und Tag (`SCHEDULER_AGENT_RUNS_PER_DAY`), darüber `skipped` | Kostendeckel; `07` §6.2 nennt ein Tageslimit als Hebel, gebaut ist keins |
| Jobs je Nutzer | höchstens 10 | Schutz gegen Fehlbedienung |
| Kontext-Reset-Default | vor jedem Lauf (`context_reset_every = 1`), letzte Antwort als Zitat im Prompt | Begründung §8.3; als offene Frage in §14 |
| Lauf-Historie | die 200 neuesten Läufe je Job | bei „alle 2 h“ gut zwei Wochen |

---

## 2. In-Process vs. Linux-cron

| Kriterium | In-Process-Loop (gewählt) | Linux-cron |
|---|---|---|
| Einstieg je Lauf | Funktionsaufruf im laufenden API-Prozess | neuer Prozess je Lauf: entweder CLI-Einstieg (`python -m kairos.scheduler run <job>`, eigener DB-Pool, eigener Import der App) oder HTTP gegen die eigene API |
| Authentifizierung | keine nötig, `user_id` kommt aus der Job-Zeile, RLS per `install_rls_listener` | HTTP: jeder Endpunkt hängt an `current_user` (Session-Cookie, `auth/deps.py`) → Service-Token + Nutzer-Impersonation, also ein neuer, sicherheitskritischer Auth-Pfad. CLI: braucht keinen, aber dupliziert die Service-Verdrahtung |
| Ergebnis sichtbar | Rückgabewert der Service-Funktion | HTTP: Sync-Endpunkte antworten `202` und arbeiten im BackgroundTask (`routers/sync.py:116, 169`), der Aufrufer sieht das Ergebnis nicht |
| Locks und Cooldowns | dieselben `asyncio.Lock`s und Cooldowns wie der Button (`SyncJobRegistry`, `ingestion/job_registry.py:48-108`) | CLI-Prozess hat eine eigene, leere Registry: ein paralleler Button-Klick läuft ungebremst gegen Garmin. Der Garmin-Cooldown existiert wegen einer echten Cloudflare-Sperre (HANDOVER, „Cloudflare-IP-Ban-Vorfall“) |
| Zeitpläne | in der DB, je Nutzer, von der Scheduler-Seite editierbar | in der crontab des Containers/Hosts; die Seite müsste die crontab schreiben (Dateirechte, Container-Neustart verliert sie) oder cron ruft minütlich einen „Dispatcher“, der doch wieder die DB liest — dann ist cron nur ein Timer |
| Zeitzone/Sommerzeit | je Job, in Python berechnet | eine Zeitzone je crontab (`CRON_TZ` nur bei manchen cron-Implementierungen) |
| Betrieb | nichts Neues; im Container läuft heute nur uvicorn (`deploy/Dockerfile:38`) | cron-Daemon im Container oder auf dem Host, Logs getrennt von der App |
| Ausfallverhalten | stirbt mit der API; verpasste Läufe holt der Loop beim Start einmal nach (§7.3) | läuft weiter, wenn die API hängt; verpasste Läufe bei Host-Ausfall gehen ohne anacron verloren |

**Ergebnis:** cron spart keinen Code (Registry und Job-Tabelle braucht es in beiden
Varianten), verliert aber die gemeinsamen Locks und die editierbaren Zeitpläne und braucht
entweder einen Impersonation-Pfad oder eine zweite Verdrahtung. Verworfen.

### 2.1 Wann ein eigener Prozess nötig wird

Der In-Process-Loop setzt **genau einen** API-Prozess voraus. Das ist heute so
(`deploy/Dockerfile:38` und `deploy/docker-compose.yml:53` starten uvicorn ohne
`--workers`; `--reload` in `Makefile:23` startet ebenfalls nur eine App-Instanz). Ein
Wechsel wird nötig, sobald eine dieser Bedingungen eintritt:

- mehrere uvicorn-/gunicorn-Worker oder eine zweite API-Instanz (dann liefe der Loop
  N-mal, und die `asyncio.Lock`s schützen nur innerhalb eines Prozesses);
- der Scheduler soll in einen eigenen Container (z. B. um API-Deploys von laufenden
  Jobs zu entkoppeln);
- Agent-Läufe werden so zahlreich, dass sie die API spürbar verlangsamen (Event-Loop,
  DB-Pool `pool_size=10, max_overflow=5`, `db/session.py:7`).

**Was dann zu tun ist** (die Spec legt die Grundlage schon jetzt):

1. **Claim:** bereits mehrprozessfähig — `SELECT … FOR UPDATE SKIP LOCKED` auf die
   Job-Zeile und der Laufzustand in der DB (§7.1). Keine Änderung.
2. **Sync-Locks:** die `asyncio.Lock`s je `(user_id, connector, kind)` durch
   Postgres-Advisory-Locks ersetzen: `pg_try_advisory_lock(hashtextextended(user_id ||
   connector || kind, 0))` auf einer eigenen Verbindung, die für die Dauer des Syncs
   gehalten wird (Session-Lock, weil ein Garmin-Sync je Datenart committet, also über
   mehrere Transaktionen läuft); Fehlschlag → `SyncBusy`.
3. **Cooldowns:** von `time.monotonic()` im Speicher in die DB (`sync_state` je
   Connector oder eigene Spalte) oder nach Redis (`SET … NX EX 300`); Redis läuft bereits.
4. **Abbruch-Erkennung:** statt „alle laufenden Läufe beim Start sind abgebrochen“
   (§7.3) eine Heartbeat-Spalte mit Lease-Timeout.
5. **`/sync`-Statusseite** und Aktiv-Konversations-Schutz (§8.5) aus der DB statt aus dem
   Prozessspeicher.

---

## 3. Overhead-Bewertung: lohnt der generische Scheduler auch für einen simplen Sync?

**Ja, solange Aktionen Funktionsaufrufe sind und der Loop im API-Prozess läuft.**

**Was der generische Teil kostet:**

- Laufzeit: eine indizierte Abfrage alle 30 s (`scheduler_due_jobs`, §4.3), bei 1–5
  Nutzern und ≤ 10 Jobs je Nutzer vernachlässigbar. Ein Sync-Schritt ruft dieselbe
  Funktion wie der Button; dazu kommen zwei kleine Schreibvorgänge in
  `scheduled_job_run` je Schritt.
- Code: Registry, Zeitplanrechner, Loop, zwei Tabellen, eine Seite. Ein
  „nur-Garmin-täglich“-Spezialfall bräuchte Zeitplan, Lauf-Historie, Nachhol- und
  Überlappungslogik ebenso; der generische Teil ist nur die Registry (Name + Schema +
  Funktion).

**Wo echter Overhead läge und wie die Spec ihn klein hält:**

| Quelle | Größe | Gegenmaßnahme |
|---|---|---|
| Eigener Prozess + Queue (arq-Worker, Redis-Queue, Zielbild `04` §6) | zweiter Container, Locks und Cooldowns müssten nach Postgres/Redis (§2.1), getrennte Logs | nicht gebaut; In-Process-Loop |
| HTTP-Aufruf eigener Endpunkte | Service-Token, Impersonation, kein Ergebnis bei `202` | Aktions-Registry |
| LLM-Kosten eines Agent-Schritts | Schätzung (nicht gemessen, Token-Telemetrie fehlt, `03` §2): ≈ 4,3 k statischer Kontext + Prompt, 3–5 LLM-Runden mit wachsenden Tool-Ergebnissen → ≈ 30–40 k Input- und ≈ 1–2 k Output-Tokens je Lauf ≈ 0,08–0,10 $ bei 2 $/10 $ je MTok (`07` §6). Täglicher Job ≈ 2,5–3 $/Monat, wöchentlicher ≈ 0,4 $/Monat. Mit voller 12 k-Historie kämen je Runde bis zu 12 k Tokens hinzu, also etwa eine Verdopplung | Kontext-Reset vor jedem Lauf (§8.3), höchstens ein Agent-Schritt je Job, Mindestabstand 60 min, Tageslimit 12 je Nutzer, keine Extraktions-LLM-Anfrage, wenn es nichts zu extrahieren gibt (§8.3). Prompt-Caching (`03` §2) wäre der nächste Hebel, gehört aber nicht hierher |
| Laufzeit eines Agent-Schritts | Median 20 s Gesamtzeit, 2–8 Tool-Aufrufe (Live-Eval 2026-10-06, HANDOVER) | läuft asynchron im Hintergrund, Timeout 5 min (§8.4); niemand wartet darauf |
| Garmin-Requests | inkrementell ≈ 2 Tagesfenster × 10 Datenarten ≈ 20 Requests + FIT-Downloads der Aktivitäten dieser Tage + Token-Login | Start aus `sync_state` statt Default-Fenster (§6), Mindestabstand 60 min, gemeinsamer Cooldown |

---

## 4. Datenmodell (eine Migration)

### 4.1 `scheduled_job`

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` NOT NULL, FK `app_user` ON DELETE CASCADE | RLS |
| `name` | `text` NOT NULL, CHECK Länge 1–80 | |
| `cron_exprs` | `text[]` NOT NULL, CHECK `cardinality BETWEEN 1 AND 6` | Teilmenge aus §1.2, validiert im Code |
| `timezone` | `text` NOT NULL DEFAULT `'Europe/Berlin'` | gegen `zoneinfo.available_timezones()` validiert; neue Jobs übernehmen `app_user.home_timezone` (`db/models.py:37`) |
| `enabled` | `boolean` NOT NULL DEFAULT `true` | |
| `steps` | `jsonb` NOT NULL | `[{"action": "garmin.sync", "params": {…}}, …]`, 1–8 Einträge, je Aktion gegen ihr Schema validiert |
| `conversation_id` | `uuid` NULL, FK `conversation` ON DELETE SET NULL | feste Konversation des Agent-Schritts; fehlt sie, legt der nächste Lauf eine neue an |
| `context_reset_every` | `smallint` NOT NULL DEFAULT 1, CHECK 0–30 | Kontext-Reset alle N Agent-Läufe; 0 = nie (dann nur das Fenster aus `history.py`) |
| `agent_runs_since_reset` | `smallint` NOT NULL DEFAULT 0 | |
| `next_run_at` | `timestamptz` NULL | NULL, wenn `enabled = false` |
| `running_since` | `timestamptz` NULL | gesetzt beim Claim, geleert am Laufende |
| `last_run_id` | `uuid` NULL | Anzeige in der Liste |
| `last_status` | `text` NULL | Kopie aus dem letzten Lauf |
| `last_success_at` | `timestamptz` NULL | für den Prompt-Kopf (§8.2) |
| `consecutive_failures` | `smallint` NOT NULL DEFAULT 0 | Anzeige; kein automatisches Abschalten in v1 |
| `created_at`, `updated_at` | `timestamptz` NOT NULL DEFAULT `now()` | |

Index: `(next_run_at) WHERE enabled AND running_since IS NULL`.

### 4.2 `scheduled_job_run`

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` | `uuid` PK | |
| `job_id` | `uuid` NOT NULL, FK `scheduled_job` ON DELETE CASCADE | |
| `user_id` | `uuid` NOT NULL, FK `app_user` ON DELETE CASCADE | RLS ohne Join, gleiches Muster wie `conversation_message.user_id` (`db/models.py:441-445`) |
| `trigger` | `text` NOT NULL, CHECK IN (`schedule`, `catch_up`, `manual`) | |
| `scheduled_for` | `timestamptz` NULL | geplanter Termin; NULL bei `manual` |
| `started_at`, `finished_at` | `timestamptz` | |
| `status` | `text` NOT NULL, CHECK IN (`running`, `ok`, `failed`, `skipped`, `interrupted`) | |
| `skip_reason` | `text` NULL | `overlap`, `all_steps_skipped` |
| `steps` | `jsonb` NOT NULL | Schnappschuss der Schritte mit Ergebnis: `[{"action", "params", "status": "ok"\|"skipped"\|"failed"\|"not_run", "started_at", "finished_at", "summary", "data", "error_code"}]` |
| `prompt_message_seq` | `bigint` NULL | `seq` der vom Scheduler geschriebenen Nutzer-Nachricht (§8.3) |

Index: `(job_id, started_at DESC)`. Nach jedem Lauf werden ältere als die 200 neuesten
Läufe des Jobs gelöscht.

Lauf-Status: `ok` = kein Schritt `failed` (übersprungene Schritte erlaubt);
`failed` = ein Schritt `failed`, Rest `not_run`; `skipped` = Überlappung oder alle
Schritte übersprungen; `interrupted` = Prozess endete während des Laufs.

### 4.3 RLS und fällige Jobs aller Nutzer

Beide Tabellen: `ENABLE` + `FORCE ROW LEVEL SECURITY` + Policy `tenant_isolation`
(`user_id = current_setting('app.current_user_id', true)::uuid`), Muster aus
`alembic/versions/7c1b2e4f9a3d_goal_table.py`.

Der Loop muss fällige Jobs **aller** Nutzer finden, eine Abfrage ohne
`app.current_user_id` sieht unter FORCE RLS aber nichts. Heute fällt das nicht auf, weil
die App-Rolle Superuser ist (HANDOVER, Phase 3 „App-DB-Rolle ist Superuser“); unter der
Least-Privilege-Rolle `kairos_app` aus den Tests (`tests/conftest.py:50-62`) würde der Loop
leer laufen. Deshalb zwei `SECURITY DEFINER`-Funktionen, die nur IDs und Zeitpunkte
liefern, nie Inhalte:

```sql
CREATE FUNCTION scheduler_due_jobs(p_now timestamptz, p_limit int)
RETURNS TABLE (job_id uuid, user_id uuid, next_run_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT id, user_id, next_run_at FROM scheduled_job
  WHERE enabled AND running_since IS NULL AND next_run_at <= p_now
  ORDER BY next_run_at LIMIT p_limit
$$;

CREATE FUNCTION scheduler_mark_interrupted(p_now timestamptz)
RETURNS TABLE (job_id uuid, user_id uuid) ...  -- setzt running-Läufe auf interrupted,
                                               -- leert running_since (§7.3)
```

Alles Weitere (Claim, Schritte, Ergebnis) läuft in einer Session mit
`install_rls_listener(session, user_id)` für den Nutzer des Jobs.

### 4.4 ORM und Repository

- `db/models.py`: `ScheduledJob`, `ScheduledJobRun` mit allen CHECKs in `__table_args__`
  (sonst schlägt `autogenerate` Löschungen vor, vgl. HANDOVER Phase 2).
- `src/kairos/scheduler/repository.py`: `ScheduledJobRepository` (CRUD, `claim`,
  `finish_run`, `prune_runs`) und die zwei Funktionsaufrufe.
- Migration auf dem dann aktuellen Alembic-Head (Stufe 1 der Workouts-Spec baut die
  Kette ohne TimescaleDB neu; auf `main` ist der Head heute `7a1c2e9d4b30`).

---

## 5. Aktions-Registry (`src/kairos/scheduler/actions.py`)

```python
class StepOutcome(BaseModel):
    status: Literal["ok", "skipped"]
    summary: str                 # feste deutsche Kurzmeldung, keine Upstream-Texte
    data: dict[str, Any] = {}    # Zahlen für Historie und Agent-Prompt

class ActionSkipped(Exception): ...           # Cooldown, Lock, Tageslimit, Konversation aktiv
class ActionFailed(Exception):                 # code + feste Meldung, Details nur im Log
    def __init__(self, code: str, message: str) -> None: ...

@dataclass(frozen=True)
class ActionContext:
    user_id: UUID
    job: ScheduledJob
    run_id: UUID
    trigger: str
    now: datetime                # injizierbare Uhr (§11)
    previous: list[StepRecord]   # Ergebnisse der Schritte davor
    registry: SyncJobRegistry

@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str                   # "Garmin synchronisieren"
    description: str
    params: type[BaseModel]
    timeout_s: float
    min_interval_s: int
    run: Callable[[ActionContext, BaseModel], Awaitable[StepOutcome]]

ACTIONS: dict[str, ActionSpec]
```

- Jede `run`-Funktion öffnet ihre Session selbst über `async_session_factory()` und ruft
  zuerst `install_rls_listener(session, ctx.user_id)` — derselbe Wrapper, den die
  CalDAV-Spec §7 fordert. Die Service-Funktionen erwarten eine fertige Session.
- `GET /api/scheduler/actions` liefert `name`, `label`, `description` und
  `params.model_json_schema()`; das Frontend baut daraus das Formular (§9.2).
- Parameter werden beim Speichern **und** beim Ausführen validiert (eine spätere
  Schemaänderung macht einen alten Job sonst still kaputt); ungültig → Schritt `failed`,
  `error_code = "invalid_params"`.

### 5.1 Die vier Aktionen

| Aktion | Parameter (Pydantic) | Ruft auf | Heute |
|---|---|---|---|
| `garmin.sync` | `kinds: list[GarminKind] \| None = None` (None = alle 10 in `_ALL_KINDS`-Reihenfolge) | `sync_garmin(session, user_id, plan, registry, trigger_source)` (neu, §5.2) mit inkrementellem Plan (§6); danach Recompute wie heute | Logik steckt in `_run_backfill_task` (`routers/sync.py:201-271`), Cooldown/Lock-Prüfung im Endpunkt (`:77-100`) |
| `calendar.sync` | `calendar: Literal["google_calendar", "caldav"] \| None = None` (None = Standardkalender) | `sync_calendar(session, user_id, provider_id, window=None)` aus der CalDAV-Spec §3.4 | auf `main` nicht vorhanden; Logik steckt in `_run_calendar_sync_task` (`routers/sync.py:363-408`). **Übergang** siehe §5.3 |
| `metrics.recompute` | `days: int = Field(60, ge=1, le=730)` | `recompute_daily_tables(session, user_id, start, end)` (neu, bündelt die drei Funktionen aus `repositories/metrics_recompute.py` + Commit) | der Endpunkt ruft die drei Funktionen direkt (`routers/metrics.py:32-47`) |
| `agent.prompt` | `prompt: str = Field(min_length=1, max_length=2000)` | `run_turn(session, user_id=…, conversation_id=…, user_message=…)` (`agent/orchestrator.py:68-99`), umrahmt von §8 | `run_turn` existiert HTTP-frei, hat aber außer Tests keinen Aufrufer |

`timeout_s` / `min_interval_s`: `garmin.sync` 3600 s / 3600 s (der erste Lauf nach langer
Pause kann viele Tagesfenster holen, §6), `calendar.sync` 120 s / 900 s,
`metrics.recompute` 300 s / 900 s, `agent.prompt` 300 s / 3600 s.

### 5.2 Herauslösen aus `routers/sync.py`

Neues Modul `src/kairos/ingestion/garmin_sync.py`:

```python
class SyncCooldown(Exception): retry_after_s: int
class SyncBusy(Exception): ...

def acquire_trigger(registry, user_id, connector, cooldown_s) -> None
    # prüft und setzt den Cooldown in einem Schritt; wirft SyncCooldown

@dataclass
class GarminSyncPlan:
    kinds: list[str]
    ranges: dict[str, tuple[datetime, datetime]]   # je Datenart [from, to)
    respect_coverage: bool                          # Button: True, Scheduler: False (§6)

async def sync_garmin(session, user_id, plan, *, registry, jobs: list[SyncJob]) -> GarminSyncResult
    # = Rumpf von _run_backfill_task: Client bauen, je Datenart Lock nehmen
    #   (belegt -> Ergebnis "skipped"), run_backfill bzw. run_incremental,
    #   Commit je Datenart, danach _recompute_after_sync

class GarminSyncResult(TypedDict):
    kinds: dict[str, KindResult]   # status, windows_processed, from, to, error_code
    recomputed_from: date | None
    error_code: str | None         # "not_connected" | "reauth_required" | None
```

- Der Endpunkt `POST /api/sync/garmin/backfill` wird zur Hülle: `acquire_trigger` →
  429, alle Datenarten gelockt → 409, Jobs anlegen, BackgroundTask öffnet Session +
  RLS und ruft `sync_garmin`. Verhalten für den Button unverändert.
- Der Scheduler ruft `acquire_trigger` ebenfalls; `SyncCooldown` → Schritt `skipped`
  („Garmin wurde gerade erst synchronisiert“). Datenarten, deren Lock belegt ist, sind im
  Ergebnis `skipped`; sind **alle** belegt, ist der Schritt `skipped`.
- Der Scheduler legt dieselben `SyncJob`-Einträge in der Registry an. Damit erscheinen
  Scheduler-Syncs auf `/sync` (der offene Punkt aus CalDAV-Spec §8).
- **Feste Fehlertexte:** heute landet `str(exc)` in `job.error` und damit in der UI
  (`routers/sync.py:264, 406`). `sync_garmin` und das Lauf-Ergebnis speichern
  `error_code` + feste Meldung, die Ausnahme geht mit `logger.exception` ins Log.
- **Registry aufräumen:** `SyncJobRegistry._jobs` wird nie geleert
  (`job_registry.py:50, 80`); mit einem Scheduler, der alle 2 h zehn Einträge anlegt,
  wächst der Speicher und `GET /api/sync/status` unbegrenzt. Neu: `prune(older_than=24 h)`
  für beendete Jobs bei jedem `create_jobs`.

### 5.3 `calendar.sync` vor und nach der CalDAV-Umsetzung

- **Liegt `sync_calendar` (CalDAV-Spec AP 3) schon vor:** direkt aufrufen; der Kern hält
  seine eigene Sperre je `(user_id, provider_id)` und committet selbst. Der Cooldown
  (`_GOOGLE_CALENDAR_SYNC_COOLDOWN_SECONDS`) bleibt Sache des Aufrufers, also prüft die
  Aktion ihn wie der Router.
- **Sonst (Übergang, nur Google):** AP 1 dieser Spec löst den Rumpf von
  `_run_calendar_sync_task` als `sync_google_calendar(session, user_id, window=None) ->
  SyncResult` nach `src/kairos/calendar/sync.py` heraus, mit **derselben Signatur und
  demselben Rückgabetyp** wie `sync_calendar` (ohne Lösch-Abgleich, ohne
  `provider_id`). CalDAV-Spec AP 3 ersetzt die Funktion an dieser Stelle; die Aktion ändert
  sich nicht. `calendar = "caldav"` wird bis dahin beim Speichern abgelehnt.

---

## 6. Garmin inkrementell

### 6.1 Was `SyncService.run_backfill` heute spart — und was nicht

Geprüft an `ingestion/service.py:135-236`, `repositories/sync_state.py:136-190` und
`connectors/garmin/connector.py:22-49`:

1. **Spart:** Überlappt die Anfrage den abgedeckten Bereich
   `[backfill_complete_from, backfill_complete_to]` auf einer Seite, wird sie auf die
   unabgedeckte Seite gekürzt, mit einem Tag Überlappung (`service.py:175-180`). Ein
   Button-Klick mit dem Default-Fenster (`from = heute − 24×30 Tage`, nicht 15 Monate:
   `_DEFAULT_BACKFILL_MONTHS = 24`, `routers/sync.py:43, 87-90`) holt deshalb heute schon
   nur die Lücke seit dem letzten Lauf.
2. **Spart zu viel:** Ist der Bereich ganz abgedeckt, wird nichts geholt
   (`service.py:164-173`). Ein zweiter Lauf am selben Tag holt also nichts.
3. **Holt den aktuellen Tag nie:** `to` ist „heute 00:00 UTC“ (`routers/sync.py:87`), das
   letzte Fenster ist `[gestern, heute)`, und der Connector fragt das Datum von
   `window.start` ab (`connector.py:24`). Der Schlaf der letzten Nacht (bei Garmin unter
   dem heutigen Datum) fehlt damit in jedem Morgen-Sync.
4. **Läuft voll, wenn die Anfrage beide Seiten überragt:** Ist eine Datenart nur für
   einen kürzeren Zeitraum abgedeckt als das Default-Fenster (HANDOVER nennt Datenarten,
   die anfangs nur ~4 Monate hatten), läuft wieder der volle Bereich
   (`service.py:176-180` greift dann nicht) — bei einem Zeitplan jedes Mal.
5. **Merge ohne Lückenprüfung:** `mark_backfill_complete` verschmilzt per
   `LEAST`/`GREATEST` (`sync_state.py:172-179`). Ein Lauf, der *nicht* an
   `backfill_complete_to` anschließt, würde die Lücke dazwischen als abgedeckt markieren.

### 6.2 Was der Scheduler übergibt

Je Datenart `k` aus `kinds`:

| Fall | `from` | `to` |
|---|---|---|
| `backfill_complete_to` gesetzt | `backfill_complete_to − 1 Tag` | morgen 00:00 UTC |
| nie synchronisiert | heute − 1 Tag | morgen 00:00 UTC |

- Das ist der „Startwert aus dem letzten erfolgreichen Lauf“ der Nutzerentscheidung,
  aber **je Datenart aus `sync_state`** statt aus `scheduled_job_run`: so zählen auch
  Button-Syncs, und eine Datenart, die im letzten Lauf scheiterte, holt ihre Lücke nach.
- Ein Tag Überlappung wie heute: der Randtag kann beim letzten Lauf unvollständig gewesen
  sein. `to = morgen 00:00` nimmt den heutigen Tag mit; `backfill_complete_to` wird damit
  „morgen“, und der nächste Lauf beginnt wieder bei „heute“.
- **Keine Obergrenze** für die Lücke: wegen Punkt 5 darf der Scheduler nur
  anschließend holen. Nach langer Pause dauert der erste Lauf entsprechend (z. B. 30 Tage
  × 10 Datenarten × 1,5 s Throttle ≈ 8 min plus Latenz); dafür der Timeout von 60 min.
- „Nie synchronisiert“ startet bewusst **keinen** Zwei-Jahres-Backfill; der bleibt eine
  Button-Aktion. Ein späterer Button-Backfill füllt die ältere Seite korrekt auf
  (`service.py:179-180`).

### 6.3 Neuer Modus `run_incremental`

`SyncService.run_incremental(connector, user_id, kind, from_date, to_date, …)` — wie
`run_backfill`, aber **ohne** Short-Circuit, ohne Kürzung und ohne gespeicherten Cursor
(`service.py:155-182` entfallen). Am Ende `mark_backfill_complete(from, to)`; der Merge ist
korrekt, weil `from ≤ backfill_complete_to`. Callbacks (`on_progress`,
`on_windows_total`), Throttle und Commit je Datenart wie heute. `sync_garmin` wählt den
Modus über `GarminSyncPlan.respect_coverage`.

**Recompute:** unverändert `_recompute_after_sync` für `[frühestes geholtes Fenster,
heute]` (`routers/sync.py:268-285`), in `sync_garmin` verschoben. Ein eigener
`metrics.recompute`-Schritt ist nach `garmin.sync` deshalb nicht nötig; er dient z. B.
einem wöchentlichen Recompute über 60 Tage.

**Tagesgrenzen:** Fenster sind heute UTC-Tage. Stufe 1 der Workouts-Spec (A.8) schneidet
Tageswerte nach `app_user.home_timezone`; die Fenster-Logik hier bleibt davon unberührt,
nur „morgen 00:00“ ist dann in der Zeitzone des Nutzers zu bilden, falls A.8 auch die
Abruf-Fenster umstellt.

---

## 7. Laufzeitverhalten

### 7.1 Loop und Claim (`src/kairos/scheduler/loop.py`, `runner.py`)

```
lifespan-Start:
  scheduler_mark_interrupted(now)                 # §7.3
  task = create_task(loop.run_forever())          # nur wenn SCHEDULER_ENABLED
lifespan-Ende:
  task.cancel(); laufende Läufe -> interrupted (best effort)

tick(now):                                        # alle SCHEDULER_TICK_SECONDS (30)
  for (job_id, user_id, due) in scheduler_due_jobs(now, limit=20):
      if user_id in active_users: continue        # Nutzer hat schon einen Lauf -> nächster Tick
      if semaphore voll: break                    # SCHEDULER_MAX_PARALLEL_RUNS (2)
      Session mit RLS(user_id):
          SELECT ... FROM scheduled_job WHERE id = :job_id
            AND enabled AND next_run_at <= :now FOR UPDATE SKIP LOCKED
          (keine Zeile -> anderer Claim oder geändert -> weiter)
          trigger = "catch_up" wenn now - due > 2 Ticks, sonst "schedule"
          next_run_at = next_occurrence(cron_exprs, timezone, after=now)
          running_since = now; INSERT scheduled_job_run(status=running, scheduled_for=due)
          COMMIT
      create_task(run_job(job, run))
```

- `next_occurrence(after=now)` überspringt alle verpassten Termine; zusammen mit dem
  einen Claim ergibt das „einmal nachholen, nicht alle“.
- **Überlappung:** Ein laufender Job hat `running_since` gesetzt und taucht in
  `scheduler_due_jobs` nicht auf. Am Laufende prüft der Runner: liegt `next_run_at` schon
  in der Vergangenheit, wurde mindestens ein Termin während des Laufs fällig → ein Lauf
  `skipped` mit `skip_reason = overlap` wird protokolliert und `next_run_at` neu berechnet.
- `run_job` führt die Schritte nacheinander aus, jeweils mit `asyncio.wait_for(…,
  timeout_s)`, und schreibt nach jedem Schritt den Zwischenstand in
  `scheduled_job_run.steps` (eigener Commit, damit die Seite Fortschritt zeigt).
  `ActionSkipped` → `skipped`, weiter; `ActionFailed`, Timeout oder unerwartete Ausnahme
  → `failed`, restliche Schritte `not_run`.
- Am Ende: `running_since = NULL`, `last_*` setzen, `consecutive_failures` hoch- bzw.
  zurücksetzen, `prune_runs`.
- Ein Timeout bricht die Coroutine ab, nicht einen bereits laufenden `to_thread`-Aufruf
  (Garmin-Fetch, LLM-Extraktion); der endet im Hintergrund, sein Ergebnis wird verworfen,
  die offene Transaktion zurückgerollt.

### 7.2 Zeitplan-Rechner (`src/kairos/scheduler/schedule.py`)

Reine Funktionen, keine DB:

```python
def parse(expr: str) -> CronSpec                   # wirft InvalidSchedule mit deutscher Meldung
def next_occurrence(exprs: list[str], tz: str, after: datetime) -> datetime   # UTC
def min_gap(exprs: list[str], tz: str, start: datetime, days: int = 14) -> timedelta
def describe(exprs: list[str], tz: str) -> str     # "Täglich 08:00", "Sonntags 18:00",
                                                   # "Alle 2 Stunden, 08–20 Uhr"
```

- Berechnung tageweise in der lokalen Zeitzone: für jeden Tag ab `after` alle passenden
  `(Stunde, Minute)`-Paare aufsteigend, je Paar `datetime(…, tzinfo=ZoneInfo(tz),
  fold=0)` → UTC; erster Wert `> after` gewinnt; Minimum über alle Ausdrücke.
- **Sommerzeit-Regel** (aus PEP 495 mit `fold=0`, getestet an den Umstellungen
  2026-03-29 und 2026-10-25 in `Europe/Berlin`):
  - **Nicht existierende Zeit** (Frühjahr, 02:30): Lauf um 03:30, also um die Länge der
    Lücke verschoben.
  - **Doppelte Zeit** (Herbst, 02:30): nur der erste Durchgang.
  - **Intervalle** werden in Wanduhrzeit gerechnet: `0 */1 * * *` läuft in der
    Herbstnacht einmal um 02:00, nicht zweimal; im Frühjahr fällt 02:00 auf 03:00 und
    damit mit dem 03:00-Termin zusammen (ein Lauf).
- `min_gap` prüft beim Speichern den Mindestabstand der strengsten Aktion des Jobs über die
  nächsten 14 Tage (fängt auch zwei Ausdrücke ab, die nur 5 min auseinanderliegen).
- **Presets der UI** und ihre Ausdrücke:

| Preset | Ausdrücke |
|---|---|
| Täglich um HH:MM | `MM HH * * *` |
| Bestimmte Wochentage um HH:MM (z. B. jeden Freitag, jeden Sonntag) | `MM HH * * 5`, `MM HH * * 0` bzw. Liste |
| Mehrmals täglich zu festen Uhrzeiten | ein Ausdruck je Uhrzeit, bis 6 (gleiche Minute → zusammengefasst, `0 8,12,18 * * *`) |
| Alle N Minuten (N ∈ 15, 20, 30) | `*/N * * * *`, optional mit Stundenbereich `*/N 8-20 * * *` |
| Alle N Stunden (N ∈ 1, 2, 3, 4, 6, 8, 12) | `0 */N * * *` bzw. `0 8-20/N * * *` |

Die UI liest einen gespeicherten Job über dieselbe Teilmenge zurück in ein Preset; nicht
abbildbare Ausdrücke kann es nicht geben, weil der Server nur die Teilmenge annimmt.
Wochentage folgen Cron (0 = Sonntag).

### 7.3 Neustart und verpasste Läufe

- Beim Start setzt `scheduler_mark_interrupted` alle `running`-Läufe auf `interrupted`
  und leert `running_since` ihrer Jobs. Das ist nur mit genau einem Prozess korrekt
  (§2.1, Punkt 4).
- Jobs mit `next_run_at < now` werden im ersten Tick geclaimt (Trigger `catch_up`) und
  laufen einmal; `next_run_at` springt auf den nächsten Termin nach `now`.
- Der erste Tick startet 15 s nach dem Start, damit Migrationen und Verbindungsaufbau durch
  sind (`migrate` läuft vorher als eigener Dienst, `deploy/docker-compose.yml:67`).
- `uvicorn --reload` (Entwicklung) startet bei jeder Codeänderung neu; laufende Läufe
  enden dann als `interrupted`. Lokal kann `SCHEDULER_ENABLED=false` gesetzt werden.

### 7.4 „Jetzt ausführen“

`POST /api/scheduler/jobs/{id}/run` startet `run_job` sofort (Trigger `manual`), ändert
`next_run_at` nicht, gilt nicht als Termin und antwortet `202` mit der Lauf-ID; läuft der
Job schon → `409 job_running`. Cooldowns, Locks und das Tageslimit gelten auch hier, ein
Klick direkt nach einem Sync liefert also übersprungene Schritte, keinen Fehler.

### 7.5 Konfiguration (`config.py`)

| Setting | Default |
|---|---|
| `scheduler_enabled` | `true` |
| `scheduler_tick_seconds` | `30` |
| `scheduler_max_parallel_runs` | `2` |
| `scheduler_agent_runs_per_day` | `12` |

Tests laufen über `httpx.ASGITransport` (z. B. `tests/test_auth.py:63`), das den
`lifespan` nicht ausführt; der Loop startet in Tests also nicht von selbst.

---

## 8. Agent-Schritt

### 8.1 Ablauf

1. Konversation sicherstellen: `job.conversation_id` oder neu anlegen
   (`ConversationRepository.create`, Titel `Scheduler: {name}`), ID am Job speichern.
2. Aktiv-Schutz (§8.5), Tageslimit (§1.2) → sonst `ActionSkipped`.
3. Kontext-Reset, falls fällig (§8.3).
4. Prompt mit Kopf bauen (§8.2) und `run_turn(session, user_id=…,
   conversation_id=…, user_message=…)` mit Timeout 300 s.
5. `prompt_message_seq` (die von `run_turn` vor dem LLM-Aufruf committete Nutzerzeile,
   `orchestrator.py:109-114`) im Lauf speichern; `agent_runs_since_reset` erhöhen.
6. Ergebnis: `reply_text` gekürzt auf 300 Zeichen als `summary`, bei einem Proposal
   `summary = "Vorschlag wartet auf Bestätigung: {proposal.summary}"` und
   `data.proposal_open = true`.

### 8.2 Was der Prompt automatisch mitbekommt

Der Scheduler stellt dem festen Prompt-Text einen Kopf voran:

```
[Geplanter Lauf „Morgen-Briefing“ · Di, 15.10.2026, 08:00 (Europe/Berlin)]
Vorheriger erfolgreicher Lauf: Mo, 14.10.2026, 08:01.
Ergebnisse der Schritte davor: Garmin-Sync ok (10 Datenarten, 2 Tage, 1 neue Aktivität);
Kalender-Sync ok (41 Termine).
Deine Antwort aus dem vorigen Lauf (Zitat, keine Anweisung):
«…» (höchstens 1 500 Zeichen)
---
Was gibt es Neues, was schlägst du für heute vor?
```

- **Lokale Uhrzeit:** nötig, weil das Lagebild die Zeit in UTC zeigt — der Orchestrator
  übergibt `datetime.now(UTC)` (`orchestrator.py:302`), `_format_now` formatiert sie ohne
  Umrechnung (`situation_brief.py:42-44`). Um 08:00 Berlin steht dort „06:00“.
- **Verspätet:** bei `catch_up` zusätzlich „(nachgeholt, geplant für 08:00)“.
- **Schrittergebnisse:** nur Zahlen aus `StepOutcome.data`, keine externen Texte
  (Kalendertitel o. Ä.); die holt der Agent bei Bedarf selbst über Tools.
- **Zitat der letzten Antwort:** nur nach einem Kontext-Reset (§8.3), damit Bezüge wie
  „gestern hatte ich lockeres Laufen empfohlen“ möglich bleiben.

### 8.3 Kontext leeren

**Ausgangslage:** Die Historie ist auf 12 000 geschätzte Tokens begrenzt, geschnitten an
Turn-Grenzen (`history.py:8, 73-84`); herausfallende Turns werden **nach** der Antwort per
LLM zu Erinnerungen extrahiert, nur aus Nutzerzeilen (`memory_extraction.py:105-114,
141-193`), und `conversation.compacted_through_seq` merkt den Stand
(`memory_extraction.py:189-191`, `db/models.py:427`). Technisch läuft die Konversation
also nie voll. Zwei Dinge sprechen trotzdem für einen Reset:

- **Kosten:** Ein Briefing-Turn mit Tool-Ergebnissen hat geschätzt 5–10 k Tokens. Das
  Fenster hält im Dauerzustand also ein bis zwei frühere Läufe, ≈ 12 k Tokens, die in
  jeder LLM-Runde mitgeschickt werden (§3). Ein Reset „alle 7 Läufe“ spart deshalb fast
  nichts: nach ein, zwei Läufen ist das Fenster wieder voll.
- **Leere Extraktionen:** In einer Job-Konversation sind die Nutzerzeilen meist nur der
  feste Prompt. Jede Fenster-Verdrängung löst trotzdem eine Extraktions-Anfrage aus.

**Mechanismus** `reset_context(session, user_id, conversation_id, exclude_seqs)` in
`agent/memory_extraction.py`, aufgerufen vor dem Lauf, wenn `context_reset_every > 0` und
`agent_runs_since_reset >= context_reset_every`:

1. Offene Proposals mit „nicht bestätigt“ schließen — dieselbe Logik wie
   `_load_llm_messages` (`orchestrator.py:281-298`), dafür als Funktion
   `close_open_proposals` herausgelöst. Ohne diesen Schritt blieben sie hinter der
   Reset-Grenze für immer offen, und eine spätere Bestätigung liefe ohne den zugehörigen
   Aufruf in der Historie (`repair_history` verwirft Ergebnisse ohne Aufruf).
2. Alle Turns nach `compacted_through_seq` extrahieren, aber nur Nutzerzeilen, deren
   `seq` **nicht** in `exclude_seqs` (die `prompt_message_seq` der Läufe dieses Jobs)
   liegt. Bleibt keine Zeile übrig, **keine** LLM-Anfrage. Gleicher Prompt und gleiche
   Kappung wie `compact_conversation`.
3. `compacted_through_seq = max(seq)` setzen, `agent_runs_since_reset = 0`, Commit.
4. Scheitert die Extraktion: kein Reset, Warnung im Log, Schritt läuft mit dem
   bisherigen Kontext weiter; der nächste Lauf versucht es erneut (gleiche Haltung wie
   `compact_conversation`, das bei Fehlern `compacted_through_seq` nicht verschiebt).

**Default `context_reset_every = 1`** (Reset vor jedem Lauf, letzte Antwort als Zitat im
Kopf, §8.2): jeder Lauf startet mit ≈ 4–5 k Tokens statt bis zu 17 k; die Kontinuität
bleibt über das Zitat und die Erinnerungen erhalten; was der Nutzer zwischen zwei Läufen
im Job-Chat sagt, wird beim nächsten Reset extrahiert. Werte bis 30 und 0 („nie“) sind
einstellbar. Die Entscheidung liegt bei Max (§14, Frage 1).

**Chat-Ansicht:** Die Nachrichtenliste zeigt weiterhin die letzten 200 Nachrichten
(`routers/agent.py:85`). `GET …/messages` liefert zusätzlich `seq` je Nachricht und
`compacted_through_seq` der Konversation; `/chat` zeigt an dieser Stelle eine Trennlinie
„Ab hier neuer Kontext“.

### 8.4 Proposals, Fehler, Timeouts

- **Proposals** bleiben offen; der Nutzer bestätigt oder verwirft sie später im Chat über
  die bestehenden Endpunkte (`routers/agent.py:168-233`). Der nächste Lauf schließt sie
  als „nicht bestätigt“ (beim Reset nach §8.3, ohne Reset wie heute in
  `_load_llm_messages`). Die Scheduler-Seite zeigt „Vorschlag wartet“ am Lauf, mit Link
  in die Konversation. Kein automatisches Bestätigen (die automatische Entlastung D32 ist
  nicht Teil dieser Spec).
- **Fehler:** `run_turn` wirft `AgentTurnError("no_llm_provider_configured" |
  "llm_provider_error")` (`orchestrator.py:92-93, 222-229`) → Schritt `failed` mit diesem
  Code und fester Meldung. Die Nutzerzeile ist dann schon gespeichert (Commit vor dem
  LLM-Aufruf, `orchestrator.py:114`) und bleibt ohne Antwort stehen; der nächste Turn
  verarbeitet das wie heute.
- **Timeout 300 s:** `stream_completion` hat kein eigenes Timeout
  (`llm_client.py:240-259`). Bei Abbruch wird die laufende Tool-Runde zurückgerollt
  (eine Transaktion je Runde, `orchestrator.py:179-216`), bereits committete Runden
  bleiben.

### 8.5 Gleichzeitiger Chat in derselben Konversation

Schreibt der Nutzer gerade in der Job-Konversation, würden zwei `_run_loop`s
Nachrichten verschränken. `_run_loop` trägt die `conversation_id` für seine Dauer in eine
prozessweite Menge `active_conversations` ein (try/finally); der Agent-Schritt ist
`skipped` („Konversation gerade aktiv“), wenn sie belegt ist. Prozessspeicher genügt, weil
Chat und Scheduler im selben Prozess laufen (§2.1, Punkt 5).

---

## 9. API & Frontend

### 9.1 Endpunkte (`src/kairos/routers/scheduler.py`)

Alle mit `current_user` + `install_rls_listener`.

| Endpunkt | Inhalt |
|---|---|
| `GET /api/scheduler/actions` | Registry: `name`, `label`, `description`, `schema`, `min_interval_s` |
| `POST /api/scheduler/preview` | `{cron_exprs, timezone}` → `{label, next: [5 Zeitpunkte, lokal und UTC], errors}` für die Live-Vorschau im Editor |
| `GET /api/scheduler/jobs` | Liste: `id`, `name`, `label`, `enabled`, `next_run_at`, `last_status`, `last_run_at`, `running`, `conversation_id`, `steps` (nur Aktionsnamen), `consecutive_failures` |
| `POST /api/scheduler/jobs` | anlegen; Validierung: Teilmenge, Zeitzone, Schemas, Mindestabstand, ≤ 1 Agent-Schritt, ≤ 10 Jobs; `422` mit feldgenauen deutschen Meldungen |
| `GET/PUT /api/scheduler/jobs/{id}` | lesen/ersetzen; `next_run_at` wird neu berechnet. Änderungen wirken ab dem nächsten Lauf, ein laufender Lauf nutzt seinen Schnappschuss |
| `PATCH /api/scheduler/jobs/{id}` | `{enabled}`; aus → `next_run_at = NULL`, an → ab jetzt neu berechnet (kein Nachholen) |
| `DELETE /api/scheduler/jobs/{id}` | `409 job_running`, solange ein Lauf aktiv ist; die Konversation bleibt erhalten |
| `POST /api/scheduler/jobs/{id}/run` | §7.4 |
| `GET /api/scheduler/jobs/{id}/runs?limit=20` | Lauf-Historie mit Schritt-Ergebnissen |
| `GET /api/agent/conversations` | zusätzlich `scheduled_job_id` je Konversation (für ein Badge in der Chat-Liste) |

### 9.2 Seite „Scheduler“ (`web/src/routes/scheduler/`)

Im Designsystem „Ruhe“ (`web/src/lib/design/kairos-tokens.json`, `Kachel.svelte`,
`StatusPill.svelte` mit Form statt nur Farbe). Navigationseintrag „Scheduler“ in
`web/src/routes/+layout.svelte:70-74`, in Desktop-Leiste und Mobil-Drawer.

- **Liste:** je Job eine Karte mit Name, Zeitplan-Label („Täglich 08:00“), nächster Lauf
  (relativ und absolut), letzter Status als `StatusPill` (ok = neutral, übersprungen =
  attention, fehlgeschlagen = deviation, mit Text), Schalter An/Aus, „Jetzt ausführen“
  (mit Pending-Zustand, vgl. HANDOVER „kein Feedback, dass ich den Button gedrückt habe“),
  Link „Konversation öffnen“ → `/chat?c={conversation_id}` (Parameter existiert,
  `web/src/routes/chat/+page.server.ts:8`), Badge „Vorschlag wartet“.
- **Leerzustand:** zwei Vorlagen als Startpunkt, ohne DB-Seed: „Morgen-Briefing“
  (täglich 08:00: `garmin.sync`, `calendar.sync`, `agent.prompt` „Was gibt es Neues, was
  schlägst du für heute vor?“) und „Wochenanalyse“ (sonntags 18:00: `garmin.sync`,
  `agent.prompt` „Erstelle eine Wochenanalyse: Trainingslast, Erholung, Schlaf, Abgleich
  mit meinen Zielen, Empfehlung für die nächste Woche.“).
- **Editor** (eigene Route `/scheduler/new`, `/scheduler/{id}`):
  - Name.
  - Zeitplan: Preset-Auswahl (§7.2) mit passenden Feldern (Uhrzeit, Wochentage als
    Umschalter, Liste fester Uhrzeiten, Intervall + optionaler Stundenbereich),
    Zeitzone (vorbelegt aus `home_timezone`, einklappbar), Live-Vorschau der nächsten
    fünf Läufe über `/preview`. Rohe Cron-Syntax wird nicht angezeigt.
  - Schritt-Editor: geordnete Liste, „Schritt hinzufügen“ aus `/actions`, Formularfelder
    aus dem JSON-Schema (`enum` → Auswahl, `array` von `enum` → Mehrfachauswahl, `string`
    mit `maxLength > 200` → Textfeld mehrzeilig, `integer` → Zahl mit `minimum`/`maximum`),
    Reihenfolge per Hoch/Runter-Knöpfen (`svelte-dnd-action` ist vorhanden, Knöpfe sind
    auf dem iPhone aber zuverlässiger), Entfernen.
  - Kontext-Reset (nur bei Agent-Schritt): „Kontext vor jedem Lauf leeren“ / „alle N
    Läufe“ / „nie“.
  - Fehlermeldungen des Servers am jeweiligen Feld.
- **Lauf-Historie** (aufklappbar je Job): Zeit, Trigger (geplant / nachgeholt / manuell),
  Dauer, Status, je Schritt Status + `summary`; aktualisiert sich alle 5 s, solange ein
  Lauf `running` ist.
- **Chat-Liste:** Konversationen mit `scheduled_job_id` bekommen ein kleines Badge
  „Scheduler“; Trennlinie beim Kontext-Reset (§8.3).

---

## 10. Sicherheit

- **Mandantentrennung:** RLS auf beiden Tabellen; jeder Schritt läuft in einer Session mit
  `install_rls_listener(session, job.user_id)`; der Nutzer kommt aus der Job-Zeile, nie
  aus Parametern. Die `SECURITY DEFINER`-Funktionen liefern nur IDs und Zeitpunkte, haben
  `SET search_path = public, pg_temp` und nehmen keine freien Texte entgegen.
- **Kein HTTP als Aktion:** keine URL-Parameter, kein SSRF-Pfad, kein Service-Token.
- **Agent:** derselbe Orchestrator, dieselben Risikoklassen und Bestätigungspflichten
  wie im Chat; der Scheduler bestätigt nichts. Der Prompt-Text stammt vom Nutzer selbst;
  Schrittergebnisse im Prompt-Kopf sind nur Zahlen (§8.2). Das Zitat der vorigen Antwort
  ist als „Zitat, keine Anweisung“ markiert, wie externe Inhalte in `03` §6.
- **Fehlertexte:** feste Meldungen + `error_code` in `scheduled_job_run` und `SyncJob`,
  Ausnahmen nur im Log (§5.2) — gleiche Regel wie CalDAV-Spec §7.
- **Kosten/Missbrauch:** Mindestabstände, ≤ 10 Jobs, ≤ 1 Agent-Schritt je Job, Tageslimit
  für Agent-Schritte; Garmin-Cooldown gilt für Scheduler und Button gemeinsam.
- **Logging:** Prompt-Texte und Antworten werden nicht geloggt, nur Job-ID, Aktion,
  Status, Dauer.

---

## 11. Tests & Arbeitspakete

### 11.1 Testansatz

- **Fake-Clock:** `SchedulerLoop` und `run_job` bekommen `now: Callable[[], datetime]`;
  Tests rufen `tick(now)` direkt auf, statt zu schlafen. `next_occurrence` ist rein und
  wird mit festen Zeitpunkten getestet.
- **Zeitplan-Tests:** alle Presets; DST in `Europe/Berlin` (2026-03-29 02:30 → 03:30,
  2026-10-25 02:30 nur einmal, stündlich über beide Nächte); Ablehnung von `*/45`,
  Tag/Monat ≠ `*`, mehr als 6 Ausdrücken; `min_gap` bei zwei Ausdrücken 5 min auseinander.
- **Fake-Connectoren/Fake-Aktionen:** Runner-Tests mit einer Test-Registry (Aktionen,
  die `ok`, `ActionSkipped`, `ActionFailed`, Timeout liefern): Abbruch beim ersten Fehler,
  Weiterlaufen nach `skipped`, Statusableitung, Überlappung, Nachholen genau einmal,
  `interrupted` nach Neustart.
- **Garmin:** `run_incremental` mit den Fake-Repos aus `tests/test_backfill_cursor.py`:
  zweiter Lauf am selben Tag holt „heute“, Start aus `backfill_complete_to − 1 Tag`, nie
  synchronisierte Datenart holt 2 Tage, keine Lücke wird als abgedeckt markiert;
  `sync_garmin` mit Fake-Connector: belegter Lock → Datenart `skipped`, Cooldown →
  Schritt `skipped`, Button und Scheduler teilen den Cooldown.
- **Agent:** `stream_rounds`/`stream_forever` aus `tests/agent_stream_helpers.py`:
  Prompt-Kopf, Proposal → `proposal_open`, `AgentTurnError` → `failed`; `reset_context`:
  schließt offene Proposals, extrahiert nur Nicht-Scheduler-Nutzerzeilen, keine
  LLM-Anfrage ohne solche Zeilen, kein Reset bei Extraktionsfehler.
- **testcontainers:** Migration, RLS beider Tabellen unter der Rolle `kairos_app`,
  `scheduler_due_jobs` findet Jobs aller Nutzer unter `kairos_app`, ohne Inhalte zu
  liefern; zwei parallele Claims auf denselben Job → genau einer gewinnt (`SKIP LOCKED`).
- **API:** Validierungsfehler je Feld, `409 job_running`, Nutzer A sieht Jobs von B nicht.
- **Frontend:** Vitest für Preset ↔ Cron-Abbildung und Schema → Formular;
  `npm run check` 0/0.

### 11.2 Arbeitspakete

| AP | Inhalt | Abnahme |
|---|---|---|
| 1 | **Service-Kerne:** `garmin_sync.py` (`acquire_trigger`, `sync_garmin`, `GarminSyncPlan`), `SyncService.run_incremental`, `recompute_daily_tables`, Kalender-Übergang `sync_google_calendar` (entfällt, wenn CalDAV-AP 3 schon da ist), Router als Hüllen, feste Fehlertexte, `SyncJobRegistry.prune` | 413+ Tests grün, Button-Verhalten unverändert (bestehende Router-Tests), neue Tests aus §11.1 „Garmin“ |
| 2 | **Zeitplan-Modul** `scheduler/schedule.py` | Tests aus §11.1 „Zeitplan“ |
| 3 | **Migration, ORM, Repository** inkl. `SECURITY DEFINER`-Funktionen | Migrations-/RLS-/Claim-Tests unter `kairos_app` |
| 4 | **Aktions-Registry** + vier Aktionen; Agent-Teil: Prompt-Kopf, `close_open_proposals`, `reset_context`, `active_conversations`, Tageslimit | Tests aus §11.1 „Agent“; Aktionen mit Fake-Diensten |
| 5 | **Runner + Loop + `lifespan`** (`api.py` hat heute keinen, `api.py:16`), Settings, Abbruch-Erkennung, Überlappung, Nachholen, Semaphore, Timeouts | Runner-Tests mit Fake-Clock; manuell: Job „alle 15 min `calendar.sync`“ läuft lokal zweimal, Neustart währenddessen → `interrupted`, danach einmal `catch_up` |
| 6 | **API** §9.1 inkl. `seq`/`compacted_through_seq` in `GET …/messages` und `scheduled_job_id` in der Konversationsliste | API-Tests |
| 7 | **Frontend** §9.2 | `npm run check` 0/0, Vitest grün, manueller Test auf dem iPhone |
| 8 | **Doku:** ADR-0007 „Scheduler im API-Prozess“ (ersetzt das arq-Zielbild), `01` §5.1/§5.2 und §8, `03` §7 (Ist: Scheduler mit Agent-Schritt, Insight-Job weiter Zielbild), `04` §6, `07` §1 und §6 (Kosten je geplantem Agent-Lauf), `08`, HANDOVER, Kommentar in `deploy/docker-compose.yml:97-116`, CalDAV-Spec §8 (offener Punkt erledigt) | `rg -n "Scheduler \(arq\)\|kein Scheduler\|keinen Scheduler" docs` trifft nur noch historisch markierte Stellen |

Reihenfolge: AP 1 und AP 2 unabhängig voneinander zuerst, dann 3 → 4 → 5 → 6 → 7 → 8.
Abschluss wie bisher mit Whole-Branch-Review und einem Real-Data-Lauf (eine Woche
„Morgen-Briefing“ und „Garmin alle 2 h, 08–20 Uhr“ gegen das echte Konto). Nahtstellen für
das Review: AP 1 ↔ AP 4 (Cooldown-/Lock-Ausnahmen werden zu `skipped`, nicht zu `failed`),
AP 4 ↔ AP 6 (Reset-Grenze und Chat-Trennlinie), AP 5 ↔ AP 3 (Claim unter RLS),
diese Spec ↔ CalDAV-Spec (Signatur von `sync_calendar`).

---

## 12. Risiken & offene Punkte

- **Ein-Prozess-Annahme** (§2.1): wer später `--workers` setzt, bekommt doppelte Läufe
  und wirkungslose Locks, ohne dass ein Test das bemerkt. Gegenmaßnahme: Kommentar im
  `Dockerfile`/Compose an der uvicorn-Zeile, und der Loop loggt beim Start eine Warnung,
  wenn `WEB_CONCURRENCY` > 1 gesetzt ist.
- **Garmin-Login je Lauf:** `_build_garmin_client` meldet sich bei jedem Sync mit dem
  gespeicherten Token neu an (`routers/sync.py:327-330`). Bei „alle 2 h“ sind das
  ≈ 7 Logins am Tag. Das ist der Token-Login, nicht der SSO-Login, der den Cloudflare-Bann
  auslöste; belastbar gemessen ist das nicht. Der Client-Cache mit TTL aus der
  Workouts-Spec D.7 (`GarminClientProvider`) würde das entschärfen.
- **FIT-Downloads:** Jeder Lauf lädt die FIT-Dateien aller Aktivitäten der geholten Tage
  neu (`connector.py:65-89`), bei „alle 2 h“ also dieselbe Aktivität mehrfach am Tag. Mit
  Stufe 1 (`fit_payload_id`, Workouts-Spec A.2) lässt sich das überspringen; bis dahin
  hingenommen.
- **Button-Backfill nach Scheduler-Lauf** holt nichts mehr für „gestern/heute“, weil
  `backfill_complete_to` dann schon „morgen“ ist; das ist gewollt (der Scheduler holt diese
  Tage), kann aber überraschen. Die `/sync`-Seite zeigt den Scheduler-Lauf daneben (§5.2).
- **Lagebild in UTC** (§8.2): der Prompt-Kopf gleicht es für geplante Läufe aus, der Chat
  sieht weiter UTC. Eigener kleiner Fix, nicht Teil dieser Spec.
- **Kosten nicht gemessen:** die Schätzungen in §3 und §8.3 beruhen auf `03` §2 und der
  Live-Eval; Token-Telemetrie fehlt (Workouts-Spec G.4).
- **Keine Benachrichtigung:** Ohne Web Push sieht der Nutzer Ergebnisse und Fehler nur auf
  der Scheduler-Seite und im Chat (§14, Frage 3).
- **Reihenfolge zu anderen Specs:** Die Scheduler-Spec ist Teil von Stufe 2 (D29–D34).
  D29 „Workout-Abgleich“ und D30 „Reaktionen“ brauchen Stufe 1 und sind hier keine
  Aktionen; die Registry nimmt sie später ohne Umbau auf.

---

## 13. Nicht-Ziele

- Frei konfigurierbare HTTP-Endpunkte als Aktion
- Verzweigungen oder Parallelität in Ketten
- Web Push
- Regelbasierter Insight-Job aus `docs/03` §7
- Eigener Worker-Container mit arq

Außerdem nicht in v1: automatische Reaktionen und Entlastung (D30, D32), rohe
Cron-Eingabe in der UI, automatisches Abschalten nach wiederholten Fehlern.

---

## 14. Offene Fragen an Max

1. **Kontext-Reset-Default:** vor jedem Lauf mit Zitat der letzten Antwort (Empfehlung,
   §8.3: spart pro Lauf bis zu 12 k Tokens je LLM-Runde) oder „alle 7 Läufe“ (mehr
   Gesprächsverlauf sichtbar für den Agenten, kostet geschätzt etwa das Doppelte)?
2. **Nachholen ohne Zeitgrenze?** Ein Morgen-Briefing, das wegen eines Ausfalls erst um
   23:00 nachgeholt wird, ist wenig nützlich. Vorschlag: so lassen (einmal nachholen) oder
   nur nachholen, wenn der Termin höchstens 6 h zurückliegt.
3. **Fehlerhinweis außerhalb der Scheduler-Seite:** Soll ein fehlgeschlagener letzter Lauf
   zusätzlich als Punkt am Navigationseintrag „Scheduler“ erscheinen? Vorschlag: ja.
4. **Grenzen:** Mindestabstand Garmin 60 min (D29 schlägt „alle 2 h“ vor), höchstens 12
   geplante Agent-Schritte je Nutzer und Tag, höchstens 10 Jobs — passen die Werte?
5. **Reihenfolge:** Scheduler vor oder nach der CalDAV-Umsetzung? Davor braucht es den
   Google-Übergang aus §5.3 (klein, wird später ersetzt); danach entfällt er.
