# 04 — Integrationen

> **Stand 2026-10-08.** Beschreibt den Ist-Stand im Code. Nicht gebaute Teile sind als
> **Zielbild (nicht umgesetzt)** markiert. Gebaut sind die Connectoren `garmin` und
> `google_calendar`; CalDAV und Gmail nicht.

Dieses Dokument beschreibt alle externen Dienste, mit denen Kairos kommuniziert:
Auth-Flows, abzurufende Datentypen, Rate-Limits, Sync-Strategien und bekannte
Risiken. Jede Integration ist ein **in-process Python-Modul** unter
`kairos/connectors/`, das das gemeinsame `Connector`-Protocol implementiert
([ADR-0003](adr/ADR-0003-connector-architektur.md)).

---

## 1. Gemeinsame Infrastruktur (Connector-Contract)

Alle Connectoren implementieren denselben Contract. Neue Connectoren entstehen durch
Implementierung dieses Interfaces — der Kern ändert sich nicht.

```python
# src/kairos/connectors/base.py — synchron; der SyncService ruft fetch() per
# asyncio.to_thread() auf, damit der Event Loop nicht blockiert
class Connector(Protocol):
    connector_id: str           # 'garmin' | 'google_calendar'

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope: ...

    def normalize(self, kind: str, payload: JSONValue) -> list[CanonicalRecord]: ...

    def write_back(
        self, user_id: UUID, kind: str, records: Sequence[CanonicalRecord]
    ) -> WriteResult: ...
```

`write_back()` ist für Garmin ein No-op und für Google Calendar implementiert, wird
aber nirgends aufgerufen. Schreibzugriffe laufen über Domänen-Funktionen
(`routers/calendar.py`), die den Client direkt nutzen; für Garmin-Workouts ist
dasselbe Muster geplant ([Spec]({SPEC}) E11).

### Gemeinsame Eigenschaften

- **Watermark-basiert.** Pro `(user_id, connector, kind)` wird `synced_through`
  in `sync_state` gehalten. Kein Vollabzug im Normalbetrieb.
- **Idempotent.** Jeder Record hat einen stabilen `external_id`; Upsert per
  `ON CONFLICT` (`DO UPDATE` für `activity`/`daily_summary`, `DO NOTHING` für
  `wellness_sample`/`sleep_session`/`activity_record`). Wiederholte Ausführung ist
  sicher.
- **Idempotenter Raw-Store.** `raw_payload` dedupliziert über `content_hash`. Ein
  zweiter identischer API-Call belastet das Archiv nicht.
- **Fehlerbehandlung — offen.** `sync_failure` existiert, wird aber nie
  geschrieben (`SyncService` ohne `sync_failure_repo`, `routers/sync.py:221`). Ein
  fehlgeschlagenes Fenster bricht den Job dieses Kinds ab und wird geloggt; die
  Wiederholung erfolgt erst beim nächsten manuellen Sync.
- **Ein Jobtyp für alles.** Es gibt keinen getrennten inkrementellen Sync: jede
  Auslösung ist ein Backfill über einen Datumsbereich, der bereits abgedeckte
  Bereiche überspringt (`sync_state.backfill_complete_from/_to`).

### Retry-Strategie

**Ist:** keine automatische Wiederholung. `SyncService._is_retryable()` klassifiziert
nur (`ValueError`/`PermissionError` = nicht wiederholbar) für den nie aufgerufenen
`sync_failure`-Pfad. Lehnt Garmin den Token ab, wird die Verbindung sofort
`reauth_required`.

*Zielbild (nicht umgesetzt):*

```
Fehlerklasse           Backoff                    Max-Retries
─────────────────────────────────────────────────────────────
Rate-limit (429)       Retry-After aus Header     unbegrenzt
Transient (5xx, net)   Exponential 30 s → 30 min  10
Auth-Fehler (401)      sofort → Reauth-Flag        1 (dann Stop)
Client-Fehler (4xx)    kein Retry                  —
```

---

## 2. Garmin Connect (`kairos/connectors/garmin`)

### 2.1 Auth

Garmin bietet **keine offizielle Public API** für Consumer-Daten. Die einzige
praktikable Option ist die inoffizielle Connect-API, angesprochen über
[`garminconnect`](https://github.com/cyberjunky/python-garminconnect) ≥ 0.3.17 mit
`curl_cffi` (TLS-Fingerprint). `garth` ist seit März 2026 nicht mehr nutzbar
(Cloudflare-Sperre) und weder installiert noch importiert.

Auth-Flow:

```
1. Nutzer gibt Garmin-Credentials im Onboarding-UI ein (HTTPS)
2. Garmin(email, password, return_on_mfa=True).login() — nur über den Widget-Flow
   (widget+cffi); der mobile clientId wird von Garmin seit 2026-10 mit 429 abgelehnt
3. Bei MFA: Kairos zeigt im UI ein Eingabefeld für den OTP-Code → resume_login()
4. Das Token-JSON (nicht das Passwort) wird mit dem DEK des Nutzers verschlüsselt
   in connection.credentials_enc gespeichert. Das Passwort wird nie gespeichert.
5. Jeder Sync: Garmin().login(token_json) — nur Token-Login (inline, da > 512 Zeichen)
6. Lehnt Garmin den Token ab: connection.status = 'reauth_required',
   reauth_since gesetzt; der Nutzer verbindet unter Konto & Sync neu
```

Ein Login mit Zugangsdaten kann außerhalb des Onboardings nicht ausgelöst werden,
weil kein Passwort vorliegt. Ein vom Client erneuertes Token wird heute nicht
zurückgeschrieben (geplant: [Spec]({SPEC}) D.7).

Risiken und Gegenmaßnahmen: Siehe [ADR-0004](adr/ADR-0004-garmin-zugang.md).

### 2.2 Rate-Limits

Garmin dokumentiert keine offiziellen Limits.

**Ist-Drosselung (Lesen):**

| Stelle | Wert | Beleg |
|---|---|---|
| Pause zwischen zwei Tagesfenstern | 1,5 s (`garmin_backfill_throttle_seconds`) | `config.py:21`, `routers/sync.py:247` |
| FIT-Downloads innerhalb eines Fensters | **keine Pause** — alle Aktivitäten des Tages direkt hintereinander | `connector.py:74-89`; Fix geplant: 2,0 s (`GARMIN_FIT_DOWNLOAD_PAUSE_S`, Spec A.5) |
| Erneutes Auslösen eines Garmin-Backfills | 300 s Cooldown je Nutzer → 429 mit `Retry-After` | `routers/sync.py:49,78-84` |
| Gleiches Kind parallel | gesperrt (Lock je Nutzer, Connector, Kind) → 409 | `ingestion/job_registry.py` |

Eine automatische Reaktion auf HTTP 429 von Garmin (Stopp + Wartezeit) gibt es beim
Lesen nicht; ein Fehler bricht den Job des betroffenen Kinds ab.

**Geplante Schreib-Limits** ([Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) D.7, für Workouts und Aktivitäten):
mindestens 1,0 s zwischen zwei Schreib-Requests (`GARMIN_WRITE_MIN_INTERVAL_S`),
höchstens 300 pro Nutzer und Stunde (`GARMIN_WRITE_MAX_PER_HOUR`), bei 429 sofortiger
Stopp und 15 min Sperre; Anlegen/Terminieren nie automatisch wiederholen, Ändern/
Löschen einmal nach 2 s bei 5xx oder Netzfehler.

### 2.3 Abzurufende Datentypen

Alle Endpunkte werden für den Zeitraum `[window_start, window_end]` (täglich)
abgerufen. Endpunkte, die Garmin-intern pro Tag aggregieren, werden als einzelner
Call pro Tag und Nutzer ausgeführt.

Die Kinds stehen in `_ALL_KINDS` (`src/kairos/routers/sync.py:53-57`) und laufen in
dieser Reihenfolge (`activity_list` vor `activity_fit`, FK auf `activity.id`):

| Kind | `garminconnect`-Methode | Zieltabelle | Hypertable |
|---|---|---|---|
| `hr_intraday` | `get_heart_rates(date)` | `wellness_sample` (metric: hr) | ✅ |
| `sleep` | `get_sleep_data(date)` | `sleep_session` | — |
| `stress` | `get_all_day_stress(date)` | `wellness_sample` (metric: stress) | ✅ |
| `body_battery` | `get_body_battery(start, end)` | `wellness_sample` (metric: body_battery) | ✅ |
| `hrv` | `get_hrv_data(date)` | `wellness_sample` (metric: hrv_5min) | ✅ |
| `respiration` | `get_respiration_data(date)` | `wellness_sample` (metric: respiration) | ✅ |
| `spo2` | `get_spo2_data(date)` | `wellness_sample` (metric: spo2) | ✅ |
| `daily_summary` | `get_stats(date)` | `daily_summary` | — |
| `activity_list` | `get_activities_by_date(start, end)` | `activity` | — |
| `activity_fit` | `get_activities_by_date` + `download_activity(id, ORIGINAL)` (ZIP → FIT → dekodiert) | `activity_record` | ✅ |

- `activity_fit` speichert **keine FIT-Dateien und nutzt keinen Object Store**; im
  `raw_payload` liegen nur die dekodierten Messages `record`, `session`, `lap`.
- **Nicht abgerufen** werden `activity_details` (Einzelabruf je Aktivität) und
  `body_composition` (Gewicht/Körperzusammensetzung); eine Tabelle
  `body_composition` gibt es nicht.

**Geräte der Nutzergruppe** (bestätigt):

| Gerät | Nutzer | body_battery | hrv | spo2 | training_readiness |
|---|---|---|---|---|---|
| Forerunner 265S | 2× | ✅ | ✅ | ✅ | ✅ |
| VivoActive 5 | 2× | ✅ | ✅ | ✅ | ✅ |
| **Apple Watch** | **1×** | **❌** | **❌** | **❌** | **❌** |

**Apple Watch:** Nutzt nicht Garmin Connect, sondern Apple HealthKit. Der Garmin-Connector ist für diese Person nicht anwendbar. Gesundheitsdaten erfordern einen separaten `connectors.apple_health`-Connector — geplant für Phase 6+. Bis dahin hat dieser Nutzer nur Kalender-Funktionalität.

**Ist:** Alle 10 Kinds werden für jeden Nutzer abgerufen. Fehlt ein Typ auf einem
Gerät, liefert Garmin eine leere Antwort; es entstehen schlicht keine Zeilen. Eine
Spalte `metric_def.available` oder eine Verfügbarkeit je Nutzer gibt es nicht
(Zielbild).

### 2.4 Normalisierung

```
raw_payload (JSONB, gzip)
    │
    ▼  connector.normalize()
┌───────────────────────────────────────┐
│  Extraktion + Typkonvertierung        │
│  Plausibilitätsprüfung → quality-Flag │
│  Timezone-Konvertierung → UTC         │
│  external_id-Ableitung                │
└───────────────────────────────────────┘
    │
    ▼
Canonical Records → Repository.upsert()
```

**Plausibilitätsgrenzen** (Werte außerhalb → `wellness_sample.quality = 'suspect'`,
Text in `varchar(16)`, Default `'ok'`):

| Metrik | Min | Max | Status |
|---|---|---|---|
| Herzfrequenz | 25 bpm | 230 bpm | **umgesetzt** (`normalize.py:34-35,57`) |
| SpO₂ | 70 % | 100 % | Zielbild — nicht geprüft |
| Schlaf gesamt | 30 min | 16 h | Zielbild — nicht geprüft |
| Stress | 0 | 100 | Zielbild — nicht geprüft |
| HRV (5-min-Fenster) | 5 ms | 200 ms | Zielbild — nicht geprüft |

Suspect-Werte werden **nicht gelöscht**. **Offen:** Die Tagesaggregate schließen sie
noch nicht aus (`metrics_recompute.py` filtert `quality` nicht), und dem Agenten
werden sie nicht gesondert markiert.

### 2.5 Backfill-Strategie

**Ist** (`SyncService.run_backfill`, `ingestion/service.py`; Auslösung über
`POST /api/sync/garmin/backfill`):

```
Backfill(user_id, connector='garmin', kinds, from_date, to_date)
    ├─ Default-Zeitraum: 24 Monate bis heute (_DEFAULT_BACKFILL_MONTHS)
    ├─ Cursor: tageweise rückwärts laufend (neueste Daten zuerst), in sync_state
    ├─ Bereits abgedeckte Bereiche werden übersprungen (backfill_complete_from/_to)
    ├─ Rate: 1,5 s Pause zwischen Tagesfenstern (FIT-Downloads ohne Pause, s. 2.2)
    ├─ Fortsetzbar: ein abgebrochener Lauf setzt beim Cursor wieder an
    ├─ Danach: Recompute der Derived-Tabellen für den geholten Zeitraum
    └─ Fortschritt auf der Sync-Seite (Fenster erledigt / gesamt je Kind)
```

Ein Zeitfenster „nur nachts“ gibt es nicht (kein Scheduler); der Backfill läuft
sofort nach dem Auslösen. Eine Restzeit-Schätzung wird nicht angezeigt.

**Volumen:** 24 Monate ≈ 730 Fenster × 10 Kinds ≈ 7.300 Fenster je Nutzer plus ein
FIT-Download je Aktivität; bei 1,5 s Pause ≈ 3 h reine Wartezeit je Nutzer.

### 2.6 Workouts (Schreiben) — geplant

Nicht umgesetzt; vollständig beschrieben in der [Spec Aktivitäten & Workouts](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md)
Teil D. Kurzfassung:

- **Methoden** (laut `garminconnect`-README, in 0.3.17 noch zu verifizieren — AP 0):
  `upload_running_workout`/`upload_cycling_workout`, `get_workout_by_id`,
  `update_workout`, `delete_workout`, `schedule_workout(id, datum)`,
  `unschedule_workout(schedule_id)`.
- **Spiegel:** `garmin_workout` und `garmin_workout_schedule`; Lese-Tools frischen
  höchstens alle 5 min auf, Garmin bleibt führend.
- **Schreibdienst:** gemeinsamer `GarminClientProvider` (nur Token-Login), ein Lock je
  Nutzer, Drosselung und 429-Sperre wie in 2.2; jede Workout-JSON wird als
  `raw_payload` (`kind='workout'`) archiviert.
- **Kopplung:** jedes Terminieren legt zusätzlich einen Google-Kalendertermin an.

---

## 3. Google Calendar & Gmail (`kairos/connectors/google_calendar`)

### 3.1 Auth

**Login und Kalender-Zugang sind in einem einzigen OAuth-Flow kombiniert** —
der `refresh_token` aus dem ersten Login (Scope: `openid email profile calendar`)
ist gleichzeitig der Kalender-Token. Es gibt keinen separaten Connector-Onboarding-
Schritt mehr. Der vollständige Auth-Flow ist in [06 — Sicherheit, Abschnitt 3.1](06-sicherheit-und-datenschutz.md#31-nutzer-auth-google-oidc) dokumentiert.

Erforderliche Scopes:

| Scope | Zweck |
|---|---|
| `openid email profile` | Nutzer-Identität (Login) |
| `https://www.googleapis.com/auth/calendar` | Lesen + Schreiben in Kalender |
| `https://www.googleapis.com/auth/gmail.readonly` | *Zielbild:* optionaler Gmail-Zugang (Phase 6) — heute **nicht** angefragt (`auth/google.py:22`) |

**Testing-App-Status:** Die Google Cloud App bleibt im Testing-Status mit explizit
eingetragenen Nutzern. Dadurch laufen Refresh-Tokens unbegrenzt — kein
Verifikationsprozess erforderlich.

### 3.2 Kalender-Sync-Strategie

**Ist-Stand:**

- Der Abruf wird nur **manuell** ausgelöst (Sync-Seite → `POST /api/sync/google_calendar/sync` in
  `routers/sync.py`, 60 s Cooldown). Es gibt keinen Webhook, keine Watch-Channels
  und kein automatisches Polling.
- Jeder Abruf holt das **Fenster von heute −7 bis +83 Tage vollständig** (mit
  `singleEvents=true` und Paginierung). Der Client unterstützt einen `syncToken`,
  der Connector übergibt aber immer `None` (`google_calendar/connector.py:28-30`) —
  der Abruf ist also nicht inkrementell.
- Die Calendar API ist im Google-Cloud-Projekt inzwischen aktiviert: Die
  Entwicklungs-DB enthält 10 von Google importierte (`source='external'`) und 3 von
  Kairos angelegte Termine (Stand 2026-10-08).

*Zielbild (nicht umgesetzt)* — **Push (primär):** Google Calendar Push Notifications
über Watch-Channels.

```
1. API: POST /calendars/{id}/events/watch → Channel mit Expiry (max. 7 Tage)
2. Google sendet HTTP POST an https://{domain}/webhooks/google/calendar
3. Webhook-Payload enthält keine Nutzdaten, nur eine Benachrichtigung
4. Kairos löst daraufhin inkrementellen Sync per syncToken aus
5. Channel muss vor Ablauf (alle 6 Tage) erneuert werden → Scheduled Job
```

**Poll (Fallback und Sicherheitsnetz):** Alle 15 Minuten `syncToken`-basierter
inkrementeller Abruf. Fängt verpasste Webhooks (Restart, Netzwerkproblem) ab.

**Erstimport:** Full-Sync aller Events der letzten 12 Monate + alle zukünftigen
Events. Danach nur noch inkrementell.

```
syncToken-Zyklus:
  GET /calendars/{id}/events?syncToken={token}
  → Nur geänderte/gelöschte Events seit letztem Sync
  → Neuer syncToken für nächsten Aufruf
  → Bei invalidem Token: Full-Sync auslösen + neuen Token holen
```

### 3.3 Gmail (optional, Phase 6)

Gmail ist **das letzte Feature** in der Implementierungsreihenfolge — geringster
Nutzen, höchstes Risiko (Prompt Injection, OAuth-Scope-Bewertung).

Scope und Einschränkungen, wenn implementiert:
- Nur Lesen, kein Verfassen, kein Antworten
- Ausschließlich Extraktion von Terminen, Buchungsbestätigungen und Trainingsplänen
- Mail-Inhalte werden auf Nutztext reduziert (kein HTML, keine Links als
  ausführbare Anweisung) bevor sie in den Agenten-Kontext gelangen
- Alle Mail-Inhalte sind als `[EXTERNE DATEN]` markiert; im System-Prompt ist
  explizit festgehalten, dass darin enthaltene Anweisungen nicht befolgt werden
- Entscheidung über Gmail-Integration: Offener Punkt, Vorabklärung empfohlen,
  Weglassen ist eine legitime Option

---

## 4. Apple Calendar / CalDAV (`kairos/connectors/caldav`)

> **Zielbild (nicht umgesetzt).** Es gibt keinen CalDAV-Connector; der gesamte
> Abschnitt beschreibt den ursprünglichen Entwurf.

### 4.1 Auth

Apple Calendar ist über **CalDAV** erreichbar. Auth via HTTP Basic (iCloud App-Specific
Password) oder Bearer-Token je nach CalDAV-Server.

**iCloud-spezifisch:**
- Kein OAuth für CalDAV; stattdessen **App-Specific Password** über
  `appleid.apple.com` generieren.
- Server: `caldav.icloud.com`
- Principal-URL: `https://caldav.icloud.com/{apple_id}/`
- App-Specific Password wird mit DEK des Nutzers verschlüsselt gespeichert.

**Generisches CalDAV** (z. B. Nextcloud, Radicale): standard HTTP-Basic oder Digest.

### 4.2 Sync-Strategie

Apple bietet **keinen Push-Mechanismus** für CalDAV. Kairos verwendet
**`getctag` + `getetag`-basiertes Poll-Verfahren**:

```
Alle 15 Minuten:
1. PROPFIND /principal/ → ctag des Kalenders
2. ctag unverändert? → kein weiterer Aufwand
3. ctag geändert? → PROPFIND /calendar/ → ETags aller Events
4. ETags vergleichen mit lokalem Stand (sync_state.sync_token = letzter ctag + ETag-Map)
5. Nur geänderte/neue Events abrufen: GET /calendar/{event}.ics
6. Gelöschte Events erkennen: in voriger ETag-Map vorhanden, jetzt nicht mehr
```

Vorteil: Minimaler Netzwerkverkehr bei unveränderten Kalendern (nur ein PROPFIND).

### 4.3 iCalendar-Parsing

Eingehende `.ics`-Daten werden über [`icalendar`](https://pypi.org/project/icalendar/)
geparst und in das kanonische `calendar_event`-Schema übersetzt.

Sonderfälle:
- **Wiederkehrende Events:** `RRULE` wird als JSONB in `calendar_event.recurrence`
  gespeichert; Expansion für Abfragen erfolgt zur Query-Zeit, nicht beim Import.
- **Gespiegelte Events** (Event erscheint in Google UND Apple): Deduplizierung über
  `dedup_group`-UUID, gematcht über `UID` + Zeitvergleich.
- **Timezones in iCal:** `VTIMEZONE`-Komponenten werden über `pytz`/`zoneinfo`
  normalisiert; alle Timestamps in der DB sind UTC.

---

## 5. LLM-API

### 5.1 Anbieter und Modelle

**Ist:** anbieterunabhängig über [litellm](https://github.com/BerriAI/litellm)
(`src/kairos/agent/llm_client.py`). Ein deployment-weiter Schlüssel `LLM_API_KEY`
gilt für alle Nutzer der Instanz; das Modell ist pro Nutzer wählbar
(`user_setting.llm_model`, Default `anthropic/claude-sonnet-5`). Dasselbe Modell
erledigt Chat und Gedächtnis-Extraktion; ein Routing nach Aufgabe gibt es nicht.

*Zielbild (nicht umgesetzt)* — **Designprinzip Modell-Routing:**

| Aufgabe | Modell-Klasse | Begründung |
|---|---|---|
| Hauptanalyse, Trainingsplanung, komplexe Interpretation | Großes Modell (z. B. Claude Opus/Sonnet) | Qualität entscheidend |
| Situation-Brief-Klassifikation (Intent → Domain) | Kleines Modell / Embedding | Latenz + Kosten |
| Konversations-Compaction | Kleines Modell | Mechanische Aufgabe |

### 5.2 Was niemals in den Kontext gelangt

Sicherheitsrelevante Garantie: Der LLM-Anbieter sieht **keine Rohdaten**.

| Verbotene Inhalte | Stattdessen |
|---|---|
| Zeitreihen als Zahlenlisten (3.300 HR-Werte) | Aggregierte Kennzahlen (⌀HR, Zonen) |
| Vollständige Kalenderinhalte | Kompakte freie-Blöcke-Zusammenfassung |
| Rohe API-Antworten von Garmin | Normalisierte Canonical Records als Kennzahl |
| Klarnamen dritter Personen aus Kalendereinladungen | Anonymisiert oder weggelassen |

### 5.3 Prompt Caching

**Ist: nicht konfiguriert.** `llm_client.py` setzt kein `cache_control`; ob ein
Anbieter automatisch cacht, hängt vom Anbieter ab und wird nicht gemessen (keine
Token-Telemetrie). Statisch und damit cachebar sind Persona, Kennzahlen-Katalog und
Tool-Schemas (≈ 2.100 Tokens, siehe [03 §2](03-agent-design.md#2-kontextbudget));
Erinnerungen und Lagebild ändern sich pro Turn. Prompt-Caching bleibt der
wirksamste Einzelhebel für Kosten-Reduktion.

### 5.4 Fehlerverhalten

| Fehlerzustand | Verhalten |
|---|---|
| Kein `LLM_API_KEY` | SSE-Event `error` mit `no_llm_provider_configured` |
| API nicht erreichbar, Rate-Limit (429), Kontext zu groß | **Ist:** jeder Anbieterfehler wird zu einem SSE-Event `error` mit `llm_provider_error`; Chat zeigt eine Störungsmeldung; Dashboard und Daten weiter nutzbar. Kein automatisches Backoff oder Retry |
| Modell gibt Zahlen ohne Tool-Beleg | Keine Laufzeitprüfung; die Zahlen-Assertions der Eval-Suite fangen das |

*Zielbild (nicht umgesetzt):* Backoff bei 429, erzwungene Compaction mit Retry bei
zu großem Kontext.

---

## 6. Zusammenfassung Sync-Architektur

**Ist:** kein Scheduler. Garmin- und Kalender-Sync werden manuell ausgelöst und
laufen als FastAPI-`BackgroundTasks`; nach einem Garmin-Backfill folgt das Recompute.
Das folgende Diagramm ist das **Zielbild (nicht umgesetzt)**:

```
              ┌─────────────────────────────────────┐
              │          Scheduler (arq)             │
              │  03:15  Garmin-Sync je Nutzer        │
              │  */15m  Google-Poll (Fallback)       │
              │  */15m  Apple/CalDAV-Poll            │
              │  06:00  Metrics-Recompute            │
              └──────────────────┬──────────────────┘
                                 │  (in-process call)
              ┌──────────────────▼──────────────────┐
              │     kairos/connectors/               │
              │  ┌──────────┬─────────┬──────────┐   │
              │  │  garmin  │ google  │  caldav  │   │
              │  └──────────┴─────────┴──────────┘   │
              │  Connector Protocol (gemeinsam)       │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │           API-Core                   │
              │  raw_payload → normalize → upsert    │
              │  sync_state (watermark / ctag)       │
              │  sync_failure (mit retry_after)      │
              └──────────────────────────────────────┘
```

**Invariante:** Was einmal in `raw_payload` liegt, wird nie überschrieben.
Normalisierung ist immer ein Vorwärtsschritt, nie eine Mutation der Rohdaten.
