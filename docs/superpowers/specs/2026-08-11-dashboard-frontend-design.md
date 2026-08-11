# Dashboard-Frontend — Design

**Status:** Autonom erarbeitet und selbst freigegeben (Nutzer nicht verfügbar, volle Entscheidungsautonomie erteilt am 2026-08-10/11). Jede Entscheidung unten ist explizit begründet, damit sie im Nachhinein überprüfbar ist.

## 1. Scope & Abgrenzung

Ziel ist die **"Minimum für User-Test"**-Messlatte aus `08-roadmap.md` (nicht die volle Phase-2-Vision mit Aktivitäts-/Schlafdetailansicht — die wird bewusst in einen Folgeplan ausgelagert, siehe §7):

1. Onboarding-Seite: Google-Login (bereits im Backend vorhanden) + Garmin-E-Mail/Passwort → `connection` anlegen
2. Sync-Status-Seite: Fortschritt des Backfills (`GET /api/sync/status` existiert bereits)
3. Dashboard mit Kennzahlen-Kacheln (die 8 registrierten Metriken aus `/api/metrics`, alle bereits backend-seitig fertig und getestet)

**Wichtiger Fund während der Recherche:** Für Punkt 1 fehlt noch ein Backend-Endpoint, um eine Garmin-`connection` per HTTP anzulegen — die Domain-Logik (`GarminClient.login()` mit MFA-Retry, `src/kairos/connectors/garmin/client.py`, 11 bereits bestehende Tests) ist fertig, aber nicht per HTTP erreichbar. Dieser eine schlanke Endpoint ist Teil dieses Plans (kein eigenständiges Subsystem, sondern eine notwendige, kleine Ergänzung, ohne die die Onboarding-Seite nicht funktionieren kann).

**Zweiter kleiner Fund:** `GET /auth/callback` (Google-OIDC) liefert aktuell rohes JSON (`{"ok": true, "email": ...}`) statt eines Redirects zu einer Frontend-Seite. Für einen kohärenten Login-Flow muss das auf einen Redirect zu `/onboarding` bzw. `/dashboard` umgestellt werden (kleine, im Scope liegende Anpassung an `src/kairos/auth/google.py`).

## 2. Architektur-Entscheidungen

### 2.1 Hosting-Modus: SvelteKit mit `adapter-node`

**Optionen:** (a) `adapter-static` (reine SPA, vorgerendert), (b) `adapter-node` (eigener kleiner Node-Server, SSR), (c) `adapter-auto`.

**Entscheidung: (b) `adapter-node`.** Begründung: Das Dashboard zeigt ausschließlich personalisierte, authentifizierte Daten — es gibt nichts sinnvoll vorzurenderndes. `docker-compose.yml` (Deployment-Skizze, `07-deployment-und-betrieb.md`) sieht bereits einen eigenen `web`-Container vor (`build: {context: ../web}`), der hinter Caddy läuft — das setzt ohnehin einen laufenden Node-Prozess voraus, `adapter-node` ist also die Option, die am wenigsten von der bereits dokumentierten Infrastruktur abweicht.

### 2.2 Auth/Session: Same-Origin-Cookie, kein separates Frontend-Auth

Backend setzt bereits einen `httponly, secure, samesite=lax`-Cookie (`session_id`, 30 Tage) nach Google-Login. Da Caddy Web und API unter derselben Domain vereint (`Caddy ──▶ API` und `──▶ Web`, `07-deployment-und-betrieb.md` §1), braucht das Frontend **kein eigenes Auth-System** — `fetch(..., {credentials: 'include'})` gegen `/api/*` reicht. Lokale Entwicklung: Vite-Dev-Server-Proxy leitet `/api/*` und `/auth/*` an den lokal laufenden FastAPI-Prozess weiter (Port aus `.env`), damit Cookies im Dev-Modus ebenfalls funktionieren (kein CORS-Workaround nötig).

**Geschützte Routen:** Ein SvelteKit `hooks.server.ts` prüft bei jedem Request serverseitig, ob `session_id` gesetzt ist (schneller Check, kein Redis-Zugriff nötig — die eigentliche Session-Validierung passiert ohnehin bei jedem Backend-Call über `current_user`); fehlt der Cookie, Redirect zu `/auth/login` (Backend-Route, unverändert).

### 2.3 Neuer Backend-Endpoint: `POST /api/connections/garmin`

Folgt exakt dem Muster von `src/kairos/routers/sync.py` (gleiches `current_user`-Dependency, gleicher `install_rls_listener`-Aufruf, gleicher Router-Stil):

```
POST /api/connections/garmin
Body: { "email": str, "password": str, "mfa_token": str | null }

→ 201 { "status": "connected" }
   Ruft GarminClient.login(email, password, mfa_token) auf. Bei Erfolg:
   token_json verschlüsseln (bestehendes crypto.py-Muster wie in sync.py's
   _build_garmin_client, nur umgekehrte Richtung), connection-Zeile anlegen
   (connector='garmin', status='active', credentials_enc=...).

→ 202 { "status": "mfa_required" }
   GarminClient wirft NeedsMfaToken (kein mfa_token übergeben). Frontend
   zeigt daraufhin ein OTP-Eingabefeld und sendet denselben Request erneut
   mit mfa_token gesetzt.

→ 401 { "detail": "invalid_credentials" }
   GarminClient wirft InvalidCredentials.

→ 503 { "detail": "garmin_unavailable" }
   GarminClient wirft UpstreamUnavailable.
```

`GET /api/connections` (einfacher Zusatz, keine eigene Aufgabe wert): Liste der `connection`-Zeilen des Nutzers mit `status`, für die Sync-Status-Seite (zeigt an, ob überhaupt eine Garmin-Verbindung besteht, bevor `/api/sync/status` sinnvoll etwas anzeigen kann).

### 2.4 Modul-Registry: statische TypeScript-Konfiguration, kein DB-Backend

`01-architektur.md` §4.5 skizziert ein Modul-JSON-Schema (`module_id`, `title`, `data_endpoint`, `component`, `refresh`, `size`) mit dem Hinweis "Nutzerkonfiguration ist nur eine Liste von `module_id` mit Position" — das impliziert perspektivisch eine DB-gestützte, pro-Nutzer-anpassbare Registry. **Für diesen Plan: eine statische TS-Konstante** (`src/lib/modules.ts`), die die 8 bekannten Metriken aus der Backend-Registry hart hinterlegt (keine Positionierungs-UI, keine Persistenz der Nutzerauswahl). Begründung (YAGNI): Bei einem einzigen aktiven Nutzer (Betreiber) lohnt sich eine volle Konfigurations-Infrastruktur noch nicht; eine DB-gestützte, pro-Nutzer-verschiebbare Variante ist eine saubere spätere Erweiterung ohne Bruch, sobald Nutzer 2–5 (Phase 6) onboarden.

Modul-Liste (1:1 aus der Backend-Registry, `GET /api/metrics` liefert die `metric_id`-Liste zur Laufzeit zur Validierung, falls sich das Backend ändert):

| module_id | Titel | Kachel-Typ |
|---|---|---|
| `trimp` | Trainingsbelastung (TRIMP) | Einzelwert + Varianten-Umschalter (Edwards/Banister) |
| `hr_zone_distribution` | HF-Zonenverteilung | Balkendiagramm + Varianten-Umschalter (%HRmax/Karvonen) |
| `training_load` | CTL/ATL/TSB | Liniendiagramm (3 Serien) |
| `acwr` | Belastungsverhältnis (ACWR) | Gauge mit Risikoband |
| `monotony_strain` | Trainingsmonotonie | Einzelwert + Sekundärwert (Strain) |
| `hrv_baseline` | HRV-Baseline | Liniendiagramm mit Band |
| `sleep_debt` | Schlafschuld | Einzelwert (Stunden) |
| `resting_hr_trend` | Ruhepuls-Trend | Einzelwert mit Trendpfeil |

### 2.5 Diagramm-Komponenten: ein generischer ECharts-Wrapper + Mark-Spezifikationen pro Kennzahl-Typ

Statt 8 einzelner Chart-Komponenten: **ein** generischer `<MetricChart>`-Wrapper (nutzt `svelte-echarts`), der eine ECharts-Options-Objekt-Funktion pro Kennzahl-*Form* (nicht pro Kennzahl) auswählt — die 8 Kennzahlen fallen in nur 4 Darstellungsformen (Einzelwert-Kachel, Liniendiagramm, Balkendiagramm, Gauge), siehe Tabelle oben. Das hält die Komponentenzahl klein und macht neue Kennzahlen billig (neuer Registry-Eintrag + vorhandene Form wiederverwenden).

### 2.6 PWA

`@vite-pwa/sveltekit` (Begründung für SvelteKit statt Next.js war explizit die PWA-Reife dieses Plugins, siehe `HANDOVER.md`) mit einem minimalen Manifest (Name, Icons, `display: standalone`) und einem einfachen Cache-First-Service-Worker für die App-Shell. **Kein** Offline-Datensync in diesem Plan (die Dashboard-Daten brauchen ohnehin eine Live-Verbindung zum Backend) — nur die Installierbarkeit als PWA, wie in der Roadmap als Ziel genannt.

### 2.7 Tests

`vitest` (Unit-/Komponententests, SvelteKit-Standard) für den `<MetricChart>`-Wrapper und die Modul-Registry-Validierung. `@playwright/test` (E2E) für genau einen Ende-zu-Ende-Pfad: Onboarding (Garmin-Login inkl. simuliertem MFA-Fall über einen gemockten Backend-Endpoint) — das ist der einzige Pfad mit echter Fehlerbehandlungs-Komplexität (drei Fehlerzustände + ein Erfolgszustand), der Rest (Dashboard-Kacheln) wird über Komponententests mit gemockten API-Antworten abgedeckt, kein volles E2E nötig für jede Kachel.

## 3. Datenfluss

```
Dashboard-Seite lädt
  → SvelteKit load()-Funktion (server-seitig, +page.server.ts)
    → parallel: GET /api/metrics (Liste bekannter metric_ids, zur Registry-Validierung)
    → für jedes Modul: GET /api/metrics/{metric_id}?variant=...&as_of=heute
  → Kachel rendert MetricResult (value, unit, confidence, coverage_days)
  → confidence ∈ {"medium", "low"} → visuelle Kennzeichnung (gedämpfte Farbe + Tooltip
    "basiert auf X von Y Tagen"); confidence = "insufficient_data" → siehe §4 (kein Wert
    wird dargestellt). "high" wird ohne Zusatzkennzeichnung dargestellt. (`Confidence` ist
    im Backend ein `Literal["high","medium","low","insufficient_data"]`, keine sortierbare
    Skala — die Zuordnung Farbe/Text erfolgt über eine feste Lookup-Tabelle im Frontend,
    kein Vergleichsoperator.) Direkte Umsetzung der in `01-architektur.md` geforderten
    Coverage-Transparenz.
  → periodischer Refresh laut `refresh`-Feld der Modul-Registry (15 min Standard)
    über einen client-seitigen Intervall-Timer, kein Websocket/SSE nötig für diese
    Aktualisierungsfrequenz
```

## 4. Fehlerbehandlung

- Backend nicht erreichbar / 5xx → Kachel zeigt "Daten gerade nicht verfügbar", kein Absturz der ganzen Seite (jede Kachel lädt unabhängig, ein Fehler in einer Metrik blockiert nicht die anderen 7).
- `confidence="insufficient_data"` → Kachel zeigt explizit "Nicht genug Daten" statt eines irreführenden Platzhalterwerts wie 0.
- Onboarding-Fehler (401/503 vom neuen Connections-Endpoint) → konkrete, unterscheidbare Fehlermeldungen (falsche Zugangsdaten vs. Garmin nicht erreichbar), kein generisches "Fehler aufgetreten".

## 5. Testbarkeit & Einheiten

- `src/lib/modules.ts` — reine Konfiguration, kein I/O, trivial testbar.
- `src/lib/components/MetricChart.svelte` — nimmt `MetricResult` + Form-Typ als Props, reine Darstellungslogik, komponententestbar mit festen Beispieldaten (keine Backend-Abhängigkeit im Test).
- `src/routes/onboarding/+page.svelte` + zugehöriger Server-Endpoint-Aufruf — einziger Ort mit echtem Kontrollfluss (MFA-Retry-UI-Zustand), daher der einzige E2E-Testfall.

## 6. Was diese Spec NICHT ist

Keine Angebot einer visuellen Vorschau (Wireframes/Mockups) — die Aufgabe wurde ohne Nutzerinteraktion bearbeitet, ein visueller Begleiter (Browser-Vorschau) wäre hier nutzlos gewesen, da niemand da war, um ihn zu betrachten. Layout-Details (genaue Kachel-Anordnung, Breakpoints) werden erst in der Implementierung anhand des tatsächlichen ECharts-Renderings entschieden, nicht vorab in dieser Spec festgelegt.

## 7. Bewusst zurückgestellt (kein Teil dieses Plans)

- **Aktivitäts- und Schlafdetailansicht** (Hypnogramm, Sekunden-Aktivitätsdaten): braucht neue Backend-Endpoints für Rohzeitreihen (`activity_record`, `sleep_session`-Phasen), die noch nicht existieren. Eigener Folgeplan.
- **Nutzerkonfigurierbare Modul-Positionierung**: erst relevant, sobald Nutzer 2–5 onboarden (Phase 6).
- **`user_setting`-Schreib-UI** (Ruhepuls/Geschlecht/Geburtsdatum für Banister-TRIMP/Karvonen): Backend hat aktuell nur einen Lese-Fallback (beobachteter Tages-Minimum-Puls, siehe `docs/HANDOVER.md`), keine Schreib-API. Eigener kleiner Folgeplan, sobald gebraucht.
- **Offline-Datensync** in der PWA — nur App-Shell-Caching, wie oben begründet.
