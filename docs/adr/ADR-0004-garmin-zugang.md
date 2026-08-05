# ADR-0004 — Garmin-Datenzugang: Inoffizielle Connect-API via `python-garminconnect`

**Status:** Akzeptiert (mit dokumentiertem Risiko)  
**Datum:** 2026-08-01  
**Revision:** 2026-08-05 — garth durch python-garminconnect ersetzt  
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

---

## Entscheidung

**Inoffizielle Connect-API via `python-garminconnect >= 0.3.5` + `curl_cffi`.**  
FIT-Binärdateien werden mit dem offiziellen `garmin-fit-sdk` dekodiert.

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
| Rate-Limits werden respektiert | ✅ konservative Drosselung (Abschnitt 2.2 in [04](../04-integrationen.md)) |

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
| Garmin ändert API-Endpunkte | mittel (jährlich) | Connector-Abstraktion; Raw-Archiv bleibt erhalten |
| Garmin sperrt den Account | gering (bei konservativer Nutzung) | Rate-Limit + Backfill nur nachts |
| `python-garminconnect` wird nicht mehr gepflegt | gering | 500+ Forks; aktive Community |

### Upgrade-Pfad
Falls Garmin eine nutzerzentrierte offizielle API einführt, kann `python-garminconnect`
durch den offiziellen Client ersetzt werden. Nur `kairos/connectors/garmin/` ändert sich.
