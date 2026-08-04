# 04 — Integrationen

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
class Connector(Protocol):
    connector_id: str           # 'garmin' | 'google' | 'caldav'

    async def fetch(
        self,
        user_id: UUID,
        kind: str,
        window: tuple[datetime, datetime],
    ) -> RawPayload: ...

    async def normalize(
        self,
        payload: RawPayload,
    ) -> list[CanonicalRecord]: ...

    async def write_back(
        self,
        user_id: UUID,
        proposal: Proposal,
    ) -> WriteResult: ...
```

### Gemeinsame Eigenschaften

- **Watermark-basiert.** Pro `(user_id, connector, kind)` wird `synced_through`
  in `sync_state` gehalten. Kein Vollabzug im Normalbetrieb.
- **Idempotent.** Jeder Record hat einen stabilen `external_id`; Upsert per
  `ON CONFLICT DO UPDATE`. Wiederholte Ausführung ist sicher.
- **Idempotenter Raw-Store.** `raw_payload` dedupliziert über `content_hash`. Ein
  zweiter identischer API-Call belastet das Archiv nicht.
- **Verlustfreie Fehlerbehandlung.** Fehlgeschlagene Zeitfenster landen in
  `sync_failure` mit `retry_after`-Timestamp. Kein stilles Überspringen.
- **Backfill als eigener Jobtyp** mit niedrigerer Prio und konservativerem
  Rate-Limit als der inkrementelle Sync.

### Retry-Strategie

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
praktikable Option ist die inoffizielle Connect-API via [`garth`](https://github.com/matin/garth).

Auth-Flow:

```
1. Nutzer gibt Garmin-Credentials im Onboarding-UI ein (HTTPS, nie im Klartext gespeichert)
2. garth.login(email, password) → OAuth2-Token-Paar (access + refresh)
3. Tokens werden mit dem DEK des Nutzers verschlüsselt in connection.credentials_enc gespeichert
4. garth refresht den Access-Token bei Bedarf automatisch
5. Bei MFA: Kairos zeigt im UI ein Eingabefeld für den OTP-Code; garth verarbeitet ihn
6. Bei Reauth-Bedarf: connection.status = 'reauth_required'; Dashboard-Hinweis
```

Risiken und Gegenmaßnahmen: Siehe [ADR-0004](adr/ADR-0004-garmin-zugang.md).

### 2.2 Rate-Limits

Garmin dokumentiert keine offiziellen Limits. Beobachtete Praxis:

| Szenario | Empfohlene Drosselung |
|---|---|
| Inkrementeller Sync (täglich) | 1 Request / 2 s, max 200 Requests / Stunde |
| Backfill (Erstimport) | 1 Request / 3 s, nächtlich, Pausenmöglichkeit |
| FIT-Downloads | 1 Datei / 5 s (größere Payloads) |

Bei HTTP 429 oder auffälligen 5xx-Antworten: sofortiger Stop des aktuellen
Sync-Jobs, Retry-After von 30 Minuten.

### 2.3 Abzurufende Datentypen

Alle Endpunkte werden für den Zeitraum `[window_start, window_end]` (täglich)
abgerufen. Endpunkte, die Garmin-intern pro Tag aggregieren, werden als einzelner
Call pro Tag und Nutzer ausgeführt.

| Kind | Garmin-Endpunkt (garth) | Zieltabelle | Hypertable |
|---|---|---|---|
| `daily_summary` | `wellness-service/wellness/dailySummaryChart` | `daily_summary` | — |
| `hr_intraday` | `wellness-service/wellness/dailyHeartRate` | `wellness_sample` (metric: hr) | ✅ |
| `stress_intraday` | `wellness-service/wellness/dailyStress` | `wellness_sample` (metric: stress) | ✅ |
| `body_battery` | `wellness-service/wellness/dailyBodyBattery` | `wellness_sample` (metric: body_battery) | ✅ |
| `respiration` | `wellness-service/wellness/dailyRespiration` | `wellness_sample` (metric: respiration) | ✅ |
| `spo2` | `wellness-service/wellness/dailyPulseOx` | `wellness_sample` (metric: spo2) | ✅ |
| `sleep` | `wellness-service/wellness/dailySleepData` | `sleep_session` | — |
| `hrv` | `hrv-service/hrv` | `wellness_sample` (metric: hrv_5min) | ✅ |
| `activity_list` | `activitylist-service/activities/search/activities` | `activity` | — |
| `activity_details` | `activity-service/activity/{id}` | `activity` | — |
| `fit_file` | `download-service/files/activity/{id}` | `activity_record` + Object Store | ✅ |
| `body_composition` | `weight-service/weight/dateRange` | `body_composition` | — |

**Geräte der Nutzergruppe** (bestätigt):

| Gerät | Nutzer | body_battery | hrv | spo2 | training_readiness |
|---|---|---|---|---|---|
| Forerunner 265S | 2× | ✅ | ✅ | ✅ | ✅ |
| VivoActive 5 | 2× | ✅ | ✅ | ✅ | ✅ |
| **Apple Watch** | **1×** | **❌** | **❌** | **❌** | **❌** |

**Apple Watch:** Nutzt nicht Garmin Connect, sondern Apple HealthKit. Der Garmin-Connector ist für diese Person nicht anwendbar. Gesundheitsdaten erfordern einen separaten `connectors.apple_health`-Connector — geplant für Phase 6+. Bis dahin hat dieser Nutzer nur Kalender-Funktionalität.

Fehlt ein Typ auf einem Gerät, wird der Endpunkt nicht abgerufen und
`metric_def.available = false` für diesen Nutzer gesetzt.

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

**Plausibilitätsgrenzen** (Werte außerhalb → `quality = 2 (suspect)`):

| Metrik | Min | Max |
|---|---|---|
| Herzfrequenz | 25 bpm | 230 bpm |
| SpO₂ | 70 % | 100 % |
| Schlaf gesamt | 30 min | 16 h |
| Stress | 0 | 100 |
| HRV (5-min-Fenster) | 5 ms | 200 ms |

Suspect-Werte werden **nicht gelöscht**, aber in Aggregaten ausgeschlossen und dem
Agenten als solche markiert übergeben.

### 2.5 Backfill-Strategie

Der Erstimport (gesamte verfügbare Historie, max. 15 Monate) läuft als eigener Jobtyp:

```
BackfillJob(user_id, connector='garmin', from_date, to_date)
    ├─ Cursor: backfill_cursor rückwärts laufend (neueste Daten zuerst)
    ├─ Rate: 1 Request / 3 s (konservativer als inkrementeller Sync)
    ├─ Unterbrechbar: Job-Status in sync_state; kann gestoppt und fortgesetzt werden
    ├─ Scheduling: nur nachts (02:00–06:00 UTC), um Tagesbetrieb nicht zu belasten
    └─ Fortschrittsanzeige im Dashboard (% erledigt, geschätzte Restzeit)
```

**Volumenabschätzung Backfill 15 Monate, 4 Garmin-Nutzer** (Apple Watch gesondert):
15 Monate × 30 Tage × 10 Endpunkte × 4 Nutzer ≈ **18.000 API-Requests**.
Bei 1 Request / 3 s = 54.000 s ≈ **15 Stunden Laufzeit** (verteilt über ~4 Nächte).

---

## 3. Google Calendar & Gmail (`kairos/connectors/google`)

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
| `https://www.googleapis.com/auth/gmail.readonly` | Optionaler Gmail-Zugang (Phase 6) |

**Testing-App-Status:** Die Google Cloud App bleibt im Testing-Status mit explizit
eingetragenen Nutzern. Dadurch laufen Refresh-Tokens unbegrenzt — kein
Verifikationsprozess erforderlich.

### 3.2 Kalender-Sync-Strategie

**Push (primär):** Google Calendar Push Notifications über Watch-Channels.

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

Geplant: Anthropic Claude. Konkretes Modell und Routing-Strategie sind offene
Punkte ([08 — Offene Punkte](08-roadmap.md#vor-phase-0)).

**Designprinzip Modell-Routing:**

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

Die ersten ~3.500 Tokens jedes Turns (System-Prompt, Core-Tools, Nutzerprofil) sind
über Sessions hinweg identisch und für **Anthropic Prompt Caching** geeignet. Das
ist der wirksamste Einzelhebel für Kosten-Reduktion.

### 5.4 Fehlerverhalten

| Fehlerzustand | Verhalten |
|---|---|
| API nicht erreichbar | Chat zeigt Störungsmeldung; Dashboard und Daten weiter nutzbar |
| Rate-Limit (429) | Exponential Backoff; Nutzer sieht "Assistent ist kurz überlastet" |
| Kontext zu groß (400) | Compaction erzwingen, Retry mit reduziertem Kontext |
| Modell gibt Zahlen ohne Tool-Beleg | Tool-Dispatcher prüft → wird als Bug geloggt; Zahlen-Assertion in Eval-Suite fängt das |

---

## 6. Zusammenfassung Sync-Architektur

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
