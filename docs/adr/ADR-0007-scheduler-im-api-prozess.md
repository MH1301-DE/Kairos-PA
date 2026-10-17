# ADR-0007 — Scheduler im API-Prozess statt arq-Worker oder Linux-cron

**Status:** Akzeptiert  
**Datum:** 2026-10-17  
**Entscheider:** Betreiber  
**Ersetzt:** Zielbild „Scheduler (arq)“ in `01-architektur.md` §3/§5.1 und `04-integrationen.md` §6

---

## Kontext

Kairos soll Abläufe zu festen Zeiten ausführen: Garmin- und Kalender-Sync, Neuberechnung
der Kennzahlen und einen Agent-Lauf mit festem Prompt („Morgen-Briefing“,
„Wochenanalyse“). Bisher lief jeder Sync nur per Klick als FastAPI-`BackgroundTask`.

Das alte Zielbild sah einen eigenen Worker-Container mit `arq` (Redis-Queue) vor.
Ebenfalls bewertet wurde Linux-cron im Container oder auf dem Host. Die Details stehen in
`docs/superpowers/specs/2026-10-15-scheduler-design.md` §2 und §3.

---

## Entscheidung

Ein **generischer Scheduler läuft im FastAPI-Prozess**: ein `asyncio`-Loop, gestartet im
`lifespan`, holt alle 30 s die fälligen Jobs aus Postgres (`scheduled_job`) und führt
ihre Schritte über eine **Aktions-Registry** aus. Die Registry ruft dieselben HTTP-freien
Service-Funktionen auf wie die Sync-Buttons.

Voraussetzung ist **genau ein API-Prozess** (uvicorn ohne `--workers`,
`WEB_CONCURRENCY` ≤ 1). Der Loop warnt beim Start, wenn das verletzt ist.

---

## Begründung

| Kriterium | In-Process (gewählt) | arq-Worker | Linux-cron |
|---|---|---|---|
| Locks und Cooldowns mit dem Sync-Button | dieselben `asyncio.Lock`s und Cooldowns im Speicher | müssten nach Postgres/Redis | getrennter Prozess, Button liefe ungebremst gegen Garmin |
| Authentifizierung | keine; `user_id` aus der Job-Zeile, RLS per `install_rls_listener` | wie In-Process | HTTP bräuchte Service-Token und Impersonation |
| Ergebnis eines Laufs | Rückgabewert der Service-Funktion | über die Queue | Sync-Endpunkte antworten nur `202` |
| Zeitpläne je Nutzer, in der UI editierbar | ja (DB) | ja (DB) | crontab müsste geschrieben werden |
| Betrieb | nichts Neues | zweiter Container, getrennte Logs | cron-Daemon, getrennte Logs |
| Ausfall | stirbt mit der API; verpasste Läufe werden beim Start einmal nachgeholt | unabhängig von der API | läuft weiter, verpasst bei Host-Ausfall |

Der Garmin-Cooldown existiert wegen einer echten Cloudflare-Sperre. Dass Scheduler und
Button ihn zuverlässig teilen, wiegt schwerer als die Entkopplung von API-Deploys.

---

## Konsequenzen

- **Ein Prozess.** Mehrere Worker hätten doppelte Läufe und wirkungslose Locks zur
  Folge, ohne dass ein Test das bemerkt. Kommentare an den uvicorn-Zeilen in
  `deploy/Dockerfile` und `deploy/docker-compose.yml` halten das fest.
- **Mehrprozessfähig vorbereitet:** Der Claim ist `SELECT … FOR UPDATE SKIP LOCKED`, der
  Laufzustand liegt in der DB. Für einen eigenen Prozess wären nötig: Advisory-Locks statt
  `asyncio.Lock`, Cooldowns in Redis/DB, Heartbeat statt „beim Start ist alles
  abgebrochen“ (Spec §2.1).
- **RLS:** Fällige Jobs aller Nutzer findet die `SECURITY DEFINER`-Funktion
  `scheduler_due_jobs`, die nur IDs und Zeitpunkte liefert; alles Weitere läuft in einer
  Session mit RLS des Job-Nutzers.
- **API-Deploys** brechen laufende Läufe ab (`interrupted`); verpasste Termine werden
  einmal nachgeholt.
- `arq` wird nicht eingeführt; die auskommentierte `worker`/`scheduler`-Skizze in
  `deploy/docker-compose.yml` ist damit erledigt.
