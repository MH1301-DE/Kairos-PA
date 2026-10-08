# ADR-0004 — Garmin-Datenzugang: Inoffizielle Connect-API via `python-garminconnect`

**Status:** Akzeptiert (mit dokumentiertem Risiko)  
**Datum:** 2026-08-01  
**Revision:** 2026-08-05 — garth durch python-garminconnect ersetzt
**Revision:** 2026-10-08 — Widget-Flow, Token-only, geplante Schreibzugriffe (Workouts)  
**Entscheider:** Betreiber

---

## Kontext

Garmin bietet zwei Wege für den Datenzugang:

1. **Offizielle Garmin Health API** — dokumentiert, stabil, ToS-konform.
2. **Inoffizielle Connect-API** — dieselbe API, die die Garmin Connect App nutzt,
   zugänglich über Bibliotheken wie [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect).

### Bibliotheks-Geschichte

Die ursprüngliche Entscheidung nannte `garth` als Implementierung. Im März 2026
blockierte Garmin/Cloudflare den garth-Auth-Endpoint (`/mobile/api/login`) global.
Der garth-Maintainer hat daraufhin das Projekt offiziell **deprecated** (garth#222).

`python-garminconnect` (cyberjunky) hat die garth-Abhängigkeit in Version 0.3.x
entfernt und nutzt seither natives DI-OAuth-Bearer + `curl_cffi` für
TLS-Fingerprint-Impersonation mit mehreren Auth-Strategien als Fallback.
Das ist die einzige aktiv gewartete Python-Bibliothek für Garmin Connect (Stand 2026-08).

Im Oktober 2026 begann Garmin, den **mobilen clientId** von jedem Netzwerk aus mit HTTP
429 abzulehnen. `python-garminconnect` probiert beim Login bis zu fünf Strategien
nacheinander (mobile/widget/portal × cffi/requests); Kairos nutzt seither **nur noch
`widget+cffi`** (`src/kairos/connectors/garmin/client.py`).

---

## Entscheidung

**Inoffizielle Connect-API via `python-garminconnect >= 0.3.17` + `curl_cffi`.**  
FIT-Binärdateien werden mit dem offiziellen `garmin-fit-sdk` dekodiert.

**Ist-Stand der Authentifizierung:**

- **Erst-Login** nur im Onboarding, mit E-Mail und Passwort über den **Widget-Flow**
  (`widget+cffi`), MFA über `return_on_mfa=True` + `resume_login()`.
- Gespeichert wird **nur das Token-JSON**, verschlüsselt mit dem DEK des Nutzers in
  `connection.credentials_enc`. Das Passwort wird nie persistiert.
- **Jeder weitere Zugriff ist ein Token-Login** (`Garmin().login(token_json)`). Ein Login
  mit Zugangsdaten kann außerhalb des Onboardings nicht ausgelöst werden.
- Lehnt Garmin den Token ab, wird die Verbindung `reauth_required`; der Nutzer verbindet
  neu.

---

## Begründung

### Warum nicht die offizielle Health API?

Die offizielle Garmin Health API setzt eine **B2B-Partnerschaft mit Garmin** voraus:
formaler Antragsprozess, Geschäftsnachweis, mehrstufige Genehmigung, laufende
Compliance-Anforderungen. Das ist für ein privates Self-Hosted-Projekt nicht
erreichbar und nicht verhältnismäßig.

### Warum nicht garth (mit User-Agent-Workaround)?

Ein einfacher UA-Override (`Mozilla/5.0 ...`) hebelt die aktuelle Cloudflare-Sperre
temporär aus. Das ist jedoch ein fragiles Pflaster auf einer deprecated Library:
Garmin kann jederzeit auf TLS-Fingerprinting umstellen. `python-garminconnect`
löst das Problem strukturell mit `curl_cffi`-Impersonation.

---

## ToS-Bewertung

| Faktor | Bewertung |
|---|---|
| Zugriff auf **eigene** Daten | ✅ jeder Nutzer greift nur auf seinen eigenen Account zu |
| Kein kommerzieller Zweck | ✅ privates Self-Hosted-Tool |
| Kein Weiterverkauf oder Aggregation über Nutzer hinweg | ✅ |
| Kein öffentliches Angebot | ✅ geschlossene Gruppe von 5 bekannten Personen |
| Rate-Limits werden respektiert | ✅ Drosselung beim Lesen (1,5 s zwischen Tagesfenstern, 300 s Cooldown je Auslösung; Abschnitt 2.2 in [04](../04-integrationen.md)) |
| Schreibzugriffe (geplant) | ⚠️ nur eigene Workouts/Aktivitäten, nur nach Bestätigung, gedrosselt — siehe unten |

**Einschätzung:** Das Risiko einer Konsequenz durch Garmin ist bei diesem Use Case
(privat, eigene Daten, kein Wiederverkauf, respektierte Limits) gering. Es bleibt
ein Restrisiko, das bewusst akzeptiert wird.

---

## Konsequenzen

### Positiv
- Vollständiger Datenzugang: alle Typen, die Garmin Connect zeigt.
- Kein Partnerschaftsprozess.
- `python-garminconnect` ist aktiv gepflegt (v0.3.8, letzte Woche, 2.8k Stars).
- `garmin-fit-sdk` ist die offizielle Garmin Python SDK für FIT-Dateien.
- Connector-Abstraktion isoliert alle Änderungen auf `kairos/connectors/garmin/`.

### Risiken

| Risiko | Wahrscheinlichkeit | Gegenmaßnahme |
|---|---|---|
| Garmin ändert API-Endpunkte oder Login | mittel (bereits zweimal eingetreten: garth 03/2026, mobile clientId 10/2026) | Connector-Abstraktion; Raw-Archiv bleibt erhalten; Login-Strategie konfigurierbar |
| Garmin sperrt den Account | gering (bei konservativer Nutzung) | Drosselung, nur Token-Login, kein paralleles Abrufen desselben Kinds. Ein nächtliches Zeitfenster gibt es nicht (kein Scheduler) |
| `python-garminconnect` wird nicht mehr gepflegt | gering | 500+ Forks; aktive Community |

### Geplante Schreibzugriffe (Workouts, Aktivitäten)

Die [Spec Aktivitäten & Workouts](../superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md)
erweitert den Zugang um **Schreiben** über dieselbe inoffizielle API: strukturierte
Workouts anlegen, ändern, terminieren, löschen sowie Aktivitäten umbenennen und löschen.
Das erhöht das Risiko gegenüber reinem Lesen:

| Risiko | Gegenmaßnahme (Spec D.7, §14) |
|---|---|
| Format der Workout-API ändert sich (inoffiziell, undokumentiert) | Mapper isoliert, Fixtures aus echtem Konto (AP 0), jede gesendete/empfangene JSON im `raw_payload` |
| Rate-Limit oder Cloudflare-Sperre bei Massenoperationen („lösche alle“) | ≥ 1,0 s zwischen Schreib-Requests, ≤ 300 je Nutzer und Stunde, nach 429 sofortiger Stopp und 15 min Sperre |
| Fehlerhafte oder ungewollte Änderungen im Konto | jede Schreibaktion nur nach Bestätigung einer Vorschau (Proposal-Snapshot); Löschen immer destruktiv-bestätigt |
| Teilerfolg zwischen Garmin und Google Calendar | Kompensation, Status `inconsistent`, idempotente Wiederaufnahme |
| Methoden fehlen in `garminconnect` 0.3.17 | vor der Umsetzung per Test verifizieren (AP 0); sonst Version anheben oder dünner Adapter |

### Upgrade-Pfad
Falls Garmin eine nutzerzentrierte offizielle API einführt, kann `python-garminconnect`
durch den offiziellen Client ersetzt werden. Nur `kairos/connectors/garmin/` ändert sich.
