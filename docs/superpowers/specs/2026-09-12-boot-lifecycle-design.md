# Boot up / Boot down / Reboot — Design Spec

**Nutzer-Auftrag:** "Insgesamt gibt es noch keine Lösung für das Thema Boot up,
Boot down und reboot." Ziel-Deployment laut Nutzerantwort: ein separater
Linux-Server/VPS (nicht dieser Windows-Rechner) — passt zu
`docs/07-deployment-und-betrieb.md` §1 ("eine einzelne Linux-VM hinter Caddy").

## 1. Bestandsaufnahme

`deploy/docker-compose.yml` existiert bereits als **Entwurf** ("Deployment-
Skizze"), ist aber nicht lauffähig:

- `deploy/Dockerfile`, `web/Dockerfile`, `deploy/Caddyfile`, `deploy/backup/`
  (Build-Kontexte) **existieren nicht** — `docker compose build` würde sofort
  fehlschlagen.
- Der `api`-Healthcheck prüft `GET /healthz` — **dieser Endpoint existiert
  nicht** im Code.
- `worker` (`arq kairos.jobs.WorkerSettings`) und `scheduler`
  (`python -m kairos.scheduler`) referenzieren Module, die **nicht
  existieren** — `arq` ist nicht einmal eine Dependency in `pyproject.toml`.
  Hintergrund-Sync läuft heute ausschließlich API-getriggert (`routers/sync.py`,
  rate-limitiert), es gibt keine Jobqueue/Scheduler-Subsystem.
- `minio` wird von keiner Zeile Code angesprochen (kein `boto3`/`minio`-Import
  irgendwo in `src/kairos`) — FIT-Rohdaten werden verarbeitet und verworfen,
  nicht als Objekt gespeichert.
- `backup` braucht ein Backup-Ziel (zweiter Standort/Anbieter) — vom Nutzer
  noch nicht festgelegt.
- `deploy/.env.example` (von `docs/07` §3.1 referenziert) existiert nicht.

Kurz: die Compose-Datei beschreibt das **Zielbild** aus `docs/07-deployment-
und-betrieb.md`, nicht den heutigen Stand. Der Nutzer hat "Boot up/Boot
down/Reboot" angesprochen — nicht "baue Job-Queue/Object-Storage/Backup" — also
ist der saubere Schnitt: **genau das bootbar machen, was heute existiert**
(api, web, postgres+timescaledb, redis, caddy als Reverse-Proxy), den Rest als
klar markiertes Zielbild stehen lassen statt stillschweigend wegzulassen.

## 2. Scope-Entscheidungen

**1. Nur die 5 heute existierenden Services werden produktionsreif gemacht:**
`caddy`, `web`, `api`, `migrate` (One-Shot), `postgres`, `redis`. `worker`,
`scheduler`, `minio`, `backup`, `uptime` werden aus der aktiven Compose-Datei
entfernt und stattdessen in einen klar überschriebenen Kommentarblock
"Zielbild laut docs/07 §1 — noch nicht gebaut" verschoben. Kein Code für eine
Jobqueue/Object-Storage/Backup wird in dieser Spec neu erfunden — das wären
eigene, deutlich größere Themen (jeweils eigene künftige Spec).

**2. `/healthz`-Endpoint, minimal.** `GET /healthz` (kein Auth, kein DB-Write)
gibt `{"status": "ok"}` mit 200 zurück, sobald der Prozess läuft. Kein
DB-Ping — ein DB-Ausfall soll den Container nicht in eine Restart-Schleife
schicken, während die App selbst noch antwortet (gleiche Überlegung wie bei
Kubernetes-Liveness- vs. Readiness-Checks, hier aber nur ein einzelner
Healthcheck für Docker/Caddy/späteres Uptime-Kuma).

**3. `deploy/Dockerfile` — Multi-Stage, Python 3.12-slim.** Build-Stage
installiert Build-Tools (für `curl_cffi`s C-Extension) + `pip install .`;
Runtime-Stage kopiert nur die installierten Packages, läuft als Non-Root-User,
`CMD uvicorn kairos.api:app --host 0.0.0.0 --port 8000`. Kein `--reload` in
Produktion.

**4. `web/Dockerfile` — Multi-Stage, Node 22-slim.** Build-Stage: `npm ci` +
`npm run build` (adapter-node, bereits in `vite.config.ts` konfiguriert,
erzeugt `build/index.js`). Runtime-Stage kopiert nur `build/`,
`node_modules` (production-only via `npm ci --omit=dev` im Build-Kontext
nach dem Build) und `package.json`. `CMD node build/index.js`. Env zur
Laufzeit: `PORT=3000`, `ORIGIN` (Pflicht für SvelteKit-Formular-CSRF-Schutz,
siehe HANDOVER.md-Notiz "ORIGIN-Env-Wiring existiert noch nicht" — wird hier
geschlossen), `BODY_SIZE_LIMIT` unverändert (Default).

**5. `deploy/Caddyfile`.** `{$DOMAIN}` terminiert TLS (Let's Encrypt
automatisch), leitet `/api/*` und `/auth/*` an `api:8000`, alles andere an
`web:3000` weiter. Kein eigener Vhost für `www.` (Scope: eine Domain, wie
Nutzergruppe von 1-5 Personen es braucht).

**6. `deploy/docker-compose.yml` wird korrigiert, nicht neu geschrieben:**
Kommentarkopf bleibt, Service-Definitionen für `caddy`/`web`/`api`/`migrate`/
`postgres`/`redis` bleiben inhaltlich fast gleich (nur `healthz` statt
Platzhalter, `ORIGIN`/`PORT`-Env für `web` ergänzt), `worker`/`scheduler`/
`minio`/`backup`/`uptime` werden in einen auskommentierten "noch nicht
gebaut"-Block verschoben (nicht gelöscht — spätere Specs bauen darauf auf).

**7. `deploy/.env.example` wird neu angelegt** — alle Variablen, die die
getrimmte Compose-Datei tatsächlich braucht: `POSTGRES_PASSWORD`,
`REDIS_PASSWORD`, `KAIROS_KEK`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`SESSION_SECRET`, `DOMAIN`, `LLM_API_KEY`, optional `GIT_SHA`. Deckt sich mit
`docs/07` §3.1 (`cp deploy/.env.example /etc/kairos/.env`).

**8. Boot up / Boot down / Reboot — bewusst keine zusätzliche
Abstraktionsschicht** (kein eigenes systemd-Unit um Compose herum). Docker
Compose selbst löst alle drei Fälle:

- **Boot up:** `docker compose -f deploy/docker-compose.yml up -d` — ein
  Befehl, `migrate` läuft automatisch vor `api` (bestehende
  `depends_on: {condition: service_completed_successfully}`).
- **Boot down:** `docker compose -f deploy/docker-compose.yml down` — stoppt
  alle Container, Volumes (Postgres-/Redis-Daten) bleiben erhalten.
- **Reboot (Server-Neustart):** `restart: unless-stopped` (bereits im
  Sketch) sorgt dafür, dass jeder Container nach einem Docker-Daemon-Neustart
  automatisch wieder hochfährt — vorausgesetzt der Docker-Daemon selbst
  startet beim Booten (`systemctl enable docker`, bei `get.docker.com`-
  Installationen auf Ubuntu bereits Standard, aber explizit dokumentiert statt
  stillschweigend vorausgesetzt).

Diese drei Fälle werden als eigener, kurzer Abschnitt in
`docs/07-deployment-und-betrieb.md` dokumentiert (direkt nach §3
Deployment-Prozess) — das beantwortet die Nutzerfrage direkt und
nachschlagbar, statt nur im Chat beantwortet zu werden.

**9. Verifikation ohne echten Server.** Es gibt in dieser Umgebung keinen
Zugriff auf einen echten Linux-Server/VPS — Docker Desktop läuft aber lokal.
Verifikation: `docker compose -f deploy/docker-compose.yml build` (alle
Images bauen durch) und ein lokaler `up -d`-Smoke-Test gegen einen isolierten
Compose-Projektnamen (eigene Netzwerke/Volumes, kollidiert nicht mit den
laufenden Dev-Containern `deploy-postgres-1`/`deploy-redis-1`) —
`GET /healthz` über den `api`-Container muss 200 liefern. Ein echter
Server-Rollout (VM anlegen, DNS, TLS-Zertifikat von Let's Encrypt) bleibt
Aufgabe des Nutzers auf der tatsächlichen VPS.

## Bewusst nicht Teil dieser Spec

- Job-Queue (`arq`) / Scheduler — kein Code dafür existiert, eigene künftige
  Spec sobald Hintergrund-Jobs (Backfill-Cron, Insight-Job aus Phase 5) nötig
  werden.
- Object-Storage (MinIO) — nichts im Code nutzt es aktuell.
- Backup/Restore (restic) — braucht eine Nutzerentscheidung zum Backup-Ziel
  (zweiter Standort/Anbieter), siehe `docs/07` §4.1. Ohne dieses Ziel kann
  kein sinnvoller Backup-Container gebaut werden.
- Uptime-Kuma/Monitoring — eigenes Thema, setzt auf `/healthz` auf (das diese
  Spec liefert), aber Alerting-Konfiguration ist nicht Teil hiervon.
- Tatsächliche VM-Provisionierung, DNS, Let's-Encrypt-Zertifikat auf einem
  echten Server — kein Werkzeugzugriff auf einen realen Host in dieser
  Umgebung, bleibt manueller Schritt des Nutzers laut `docs/07` §3.1/§7.
