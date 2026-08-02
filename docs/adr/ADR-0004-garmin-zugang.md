# ADR-0004 — Garmin-Datenzugang: Inoffizielle Connect-API via `garth`

**Status:** Akzeptiert (mit dokumentiertem Risiko)  
**Datum:** 2026-08-01  
**Entscheider:** Betreiber

---

## Kontext

Garmin bietet zwei Wege für den Datenzugang:

1. **Offizielle Garmin Health API** — dokumentiert, stabil, ToS-konform.
2. **Inoffizielle Connect-API** — dieselbe API, die die Garmin Connect App nutzt,
   zugänglich über Bibliotheken wie [`garth`](https://github.com/matin/garth).

---

## Entscheidung

**Inoffizielle Connect-API via `garth`.**

---

## Begründung

### Warum nicht die offizielle Health API?

Die offizielle Garmin Health API setzt eine **B2B-Partnerschaft mit Garmin** voraus:
formaler Antragsprozess, Geschäftsnachweis, mehrstufige Genehmigung, laufende
Compliance-Anforderungen. Das ist für ein privates Self-Hosted-Projekt nicht
erreichbar und nicht verhältnismäßig.

### Was `garth` tut

`garth` authentifiziert sich gegen `connect.garmin.com` wie die offizielle
Garmin-Connect-App: OAuth2-Flow mit denselben Client-Credentials. Die zurückgegebenen
Daten sind identisch mit dem, was ein Nutzer in der App sieht.

---

## ToS-Bewertung

Garmins Nutzungsbedingungen verbieten automatisierten Datenzugriff ohne ausdrückliche
Genehmigung. Für Kairos gilt:

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
- `garth` ist aktiv gepflegt und weit verbreitet.

### Risiken

| Risiko | Wahrscheinlichkeit | Gegenmaßnahme |
|---|---|---|
| Garmin ändert API-Endpunkte | mittel (jährlich) | Connector-Abstraktion macht Anpassung lokal; Raw-Archiv bleibt erhalten |
| Garmin sperrt den Account | gering (bei konservativer Nutzung) | Rate-Limit + Backfill nur nachts |
| `garth` wird nicht mehr gepflegt | gering | Fork oder Alternative (`garminconnect`) als Fallback |

### Upgrade-Pfad
Falls Garmin eine nutzerzentrierte offizielle API einführt (angekündigt, kein
Datum), kann `garth` durch den offiziellen Client ersetzt werden. Die
Connector-Abstraktion stellt sicher, dass nur `kairos/connectors/garmin/` sich
ändert.
