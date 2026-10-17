# 07 — Deployment & Betrieb

---

## 1. Infrastrukturübersicht

Kairos läuft auf **einer einzelnen Linux-VM** hinter Caddy. Kein Kubernetes, kein
Load Balancer, kein Managed Database-Service. Eine VM ist noch **nicht gebucht**;
die Größe ist offen (siehe §2.2).

```
Internet
    │ HTTPS (443)
    ▼
┌─────────────────────────────────────────────────────┐
│ VM  (Hetzner Cloud, Ubuntu 24.04 LTS — geplant)     │
│                                                     │
│  Caddy ──▶ API  ──▶ Postgres 16                     │
│         ──▶ Web        ──▶ Redis                    │
│  migrate (alembic upgrade, einmalig je Start)       │
└─────────────────────────────────────────────────────┘
```

Alle Services laufen als Docker Compose Stack unter `deploy/docker-compose.yml`.

| Dienst | Status |
|---|---|
| Caddy, Web (SvelteKit), API (FastAPI), migrate, Postgres 16 (`postgres:16`), Redis | **gebaut** (in Compose, lokal verifiziert) |
| MinIO (Object Store) | Zielbild — kein Object-Storage-Code, in Compose auskommentiert |
| arq Worker + Scheduler | Zielbild — kein Scheduler; Syncs laufen als BackgroundTasks in der API |
| Backup-Container (restic, täglich 02:00) | Zielbild — in Compose auskommentiert, Backup-Ziel nicht entschieden |
| Uptime Kuma (Monitoring) | Zielbild — nicht in Compose |
| `pgvector` | Zielbild — Extension nicht installiert |

---

## 2. VM-Sizing

### 2.1 RAM-Bedarf

| Service | Typischer RSS |
|---|---|
| Postgres 16 (`shared_buffers=256 MB`) | ~700 MB |
| API (FastAPI, uvicorn, 1 Prozess) | ~200 MB |
| Web (SvelteKit, Node) | ~100 MB |
| Redis | ~50 MB |
| Caddy | ~30 MB |
| OS + Docker-Overhead | ~400 MB |
| **Summe (Ist-Stack)** | **~1,5 GB** |
| *zusätzlich bei Zielbild:* arq Worker + Scheduler, MinIO, Uptime Kuma | *~+410 MB* |

Die Werte sind Schätzungen, nicht gemessen.

Peak (Backfill + Metrics-Recompute gleichzeitig): +400 MB → ~2,2 GB.

### 2.2 Empfehlung

**SSD-Bedarf** (Messung vom 2026-10-17 nach Stufe 1, siehe
[02 §1.3](02-datenmodell-und-volumen.md#13-speicherbedarf)): Daten für 5 Nutzer über
5 Jahre ≈ **4 GB bei der realen Aktivitätsrate** (≈ 98/Jahr), ≈ **5,5 GB im
Doku-Szenario** (250/Jahr). Seit Stufe 1 liegen Sekundendaten als Arrays in
`activity_stream` (≈ 0,13 MB je Aktivität statt ≈ 4 MB in `activity_record`), dazu das
Original-FIT-ZIP (≈ 0,09 MB). Hauptposten ist jetzt `wellness_sample`. Dazu kommen OS,
Docker-Images (≈ 8–10 GB, ohne TimescaleDB-Image) und Platz für lokale Dumps vor dem
Upload ins Backup. **40 GB SSD reichen** (Hetzner CX22).

| VM (Hetzner, Angaben vor Buchung prüfen) | RAM | SSD | Bewertung |
|---|---|---|---|
| CX22 | 4 GB | 40 GB | RAM ✅; SSD reicht für die reale Rate knapp, im Doku-Szenario **zu knapp** |
| CX32 | 8 GB | 80 GB | ausreichend für beide Szenarien mit Puffer |

**Empfehlung (aktualisiert):** eine VM mit **≥ 80 GB SSD** (z. B. CX32) — oder CX22
plus ein separates Volume für Postgres. CPU ist kein Engpass; Postgres und der Sync
sind I/O-gebunden. **Offen:** welche VM real gebucht wird (Prüfbericht vom
2026-10-07, Frage 26).

### 2.3 Postgres-Tuning für 4 GB RAM

*Zielbild (nicht umgesetzt):* `deploy/docker-compose.yml` setzt heute keine dieser
Parameter; Postgres läuft mit den Image-Defaults.

```ini
# /etc/postgresql/16/main/postgresql.conf (via Docker-Env oder Config-Mount)
shared_buffers       = 1GB      # 25 % des RAM
effective_cache_size = 3GB      # 75 % des RAM
work_mem             = 16MB
maintenance_work_mem = 256MB
max_connections      = 50       # API hat max 10 Connections per Worker
```

---

## 3. Deployment-Prozess

### 3.1 Erstinstallation

```bash
# 1. VM bei Hetzner anlegen (Ubuntu 24.04, SSH-Key hinterlegen)
# 2. Docker + Docker Compose installieren
curl -fsSL https://get.docker.com | sh
# 3. Repo klonen
git clone https://github.com/{user}/kairos /opt/kairos
# 4. .env-Datei anlegen (außerhalb des Repos)
cp /opt/kairos/deploy/.env.example /etc/kairos/.env
chmod 600 /etc/kairos/.env
# → KEK, Passwörter, Google-Client-ID/Secret eintragen
# 5. Symlink damit Compose die .env findet
ln -s /etc/kairos/.env /opt/kairos/deploy/.env
# 6. Stack starten (Migrationen laufen automatisch vor dem App-Start)
cd /opt/kairos/deploy
docker compose up -d
```

### 3.2 Updates

```bash
cd /opt/kairos
git pull
GIT_SHA=$(git rev-parse --short HEAD) docker compose up -d --build
```

Images werden auf den neuen `GIT_SHA`-Tag gebaut; Alembic-Migrationen laufen als
One-Shot-Container (`migrate`) vor dem App-Start. Downtime: ~30–60 Sekunden.

### 3.3 Rollback

```bash
git checkout <previous-sha>
GIT_SHA=<previous-sha> docker compose up -d --build
# Bei DB-Migration: alembic downgrade -1
```

### 3.4 Boot up / Boot down / Reboot

Keine zusätzliche Abstraktionsschicht (kein eigenes systemd-Unit um Compose
herum) -- Docker Compose selbst deckt alle drei Fälle ab.

**Boot up** (Stack hochfahren, z. B. nach Erstinstallation oder manuellem
Stop):
```bash
cd /opt/kairos/deploy
docker compose up -d
```
Ein Befehl -- `migrate` läuft automatisch als One-Shot-Container vor `api`
(`depends_on: {condition: service_completed_successfully}`).

**Boot down** (Stack sauber stoppen, Daten bleiben erhalten):
```bash
cd /opt/kairos/deploy
docker compose down
```
Postgres-/Redis-Volumes (`pgdata`, `redisdata`) überleben das -- nur
`docker compose down -v` löscht auch Volumes, absichtlich ein separater,
selten gebrauchter Befehl.

**Reboot** (Server-Neustart, geplant oder ungeplant): läuft **automatisch**,
kein manueller Schritt nötig, sofern beim Ersteinrichten zwei Dinge
sichergestellt sind:

1. Jeder Service hat `restart: unless-stopped` (bereits Standard in
   `deploy/docker-compose.yml`) -- jeder Container fährt nach einem
   Docker-Daemon-Neustart automatisch wieder hoch.
2. Der Docker-Daemon selbst startet beim Booten. Bei einer
   `get.docker.com`-Installation auf Ubuntu ist das bereits Standard
   (`systemctl is-enabled docker` sollte `enabled` zeigen); falls nicht:
   ```bash
   sudo systemctl enable docker
   ```

Ein `docker compose down` (bewusstes Stoppen) übersteht einen Reboot
**nicht** wieder hoch -- das ist Absicht: ein bewusst gestoppter Stack soll
nicht durch einen Server-Neustart überraschend wieder anlaufen.

---

## 4. Backup & Wiederherstellung

> **Zielbild (nicht umgesetzt).** Der `backup`-Dienst ist in
> `deploy/docker-compose.yml` auskommentiert; das Backup-Ziel ist noch nicht
> entschieden. Ohne Object Store entfällt `/srv/minio` im Backup.

### 4.1 Backup-Job

```bash
# täglich 02:00 via cron im backup-Container
pg_dump -Fc kairos > /tmp/kairos_$(date +%Y%m%d).dump
restic backup /tmp/kairos_*.dump /srv/minio
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune
```

Ziel: zweiter Standort, separater Anbieter (z. B. Hetzner Storage Box oder
Backblaze B2). Restic verschlüsselt mit eigenem Key (getrennt vom KAIROS_KEK).

**Was nicht im Backup:** KAIROS_KEK — er lebt nur in `/etc/kairos/.env` auf der VM
und im Passwort-Manager des Betreibers.

### 4.2 Wiederherstellungstest (Pflicht in Phase 0)

```bash
# Auf einer frischen VM oder lokal:
restic restore latest --target /tmp/restore
pg_restore -d kairos_test /tmp/restore/kairos_*.dump
# Smoke-Test: mindestens ein Nutzer, mindestens ein wellness_sample
```

**Ohne nachgewiesenen Restore gibt es keine Phase-0-Abnahme.**

### 4.3 Recovery Time Objective

| Szenario | RTO |
|---|---|
| VM-Neustart (kein Datenverlust) | ~2 min |
| Neue VM, Restore aus Backup | ~30 min |
| Datenbankkorruption, Restore aus Backup | ~30 min |

---

## 5. Monitoring

> **Zielbild (nicht umgesetzt).** Uptime Kuma ist nicht im Stack. Vorhanden sind
> nur der Docker-Healthcheck der API (`/healthz`) und der Postgres-Healthcheck
> (`pg_isready`) in `deploy/docker-compose.yml`.

**Uptime Kuma** (geplant) überwacht:

| Check | Intervall | Alert |
|---|---|---|
| `https://{domain}/healthz` (API) | 1 min | Push-Notification |
| Postgres (TCP Port intern) | 1 min | Push-Notification |
| Garmin-Sync-Job (letzter Erfolg < 26 h) | 15 min | Push-Notification |
| Backup-Job (letzter Erfolg < 26 h) | 15 min | Push-Notification |

Alerting: Uptime Kuma unterstützt Push-Notifications (Pushover, Telegram, E-Mail).
Kein separater Alertmanager nötig.

**Logs:** `docker compose logs -f api` im Normalbetrieb. **Ist:** Standard-`logging`
von Python, Textformat. *Zielbild (nicht umgesetzt):* structured JSON-Logs
(`structlog`), filterbar nach `user_id`, `request_id`, `level`.

---

## 6. Kosten

### 6.1 Infrastruktur

| Posten | Kosten/Monat |
|---|---|
| VM (CX22 bzw. CX32, siehe §2.2) | ~€ 4,50 bzw. ~€ 8,50 (Stand der ursprünglichen Planung, vor Buchung prüfen) |
| Domain (.com, .de) | ~€ 1,00 |
| Backup-Ziel (Hetzner Storage Box 100 GB) | ~€ 1,00 |
| **Infrastruktur gesamt** | **~€ 6,50 – 10,50** |

### 6.2 LLM-API

Default-Modell ist `anthropic/claude-sonnet-5` (über litellm, pro Nutzer änderbar;
Preise laut Anthropic-Preisliste, Stand 2026-10-06: **$2 / MTok Input, $10 / MTok
Output, Cache-Reads $0,20 / MTok**; der Nachfolger Claude Sonnet 5.5 kostet dasselbe).

Schätzung bei aktivem Betrieb (alle 5 Nutzer):

| Parameter | Annahme |
|---|---|
| Nutzer-Turns/Tag gesamt | ~15 (∅ 3 je Nutzer) |
| LLM-Aufrufe je Nutzer-Turn | ≥ 1; mit Tool-Runden laut Eval oft 2–4 (jede Runde sendet den Kontext erneut) |
| Input-Tokens je LLM-Aufruf | ~15.000 (Median-Budget, nicht gemessen) |
| Output-Tokens je Nutzer-Turn | ~800 |
| Cache-Hit-Rate | 0 % — Prompt-Caching ist nicht konfiguriert |

```
Input  : 15 × 15.000 × 30 Tage            ≈  6,75 M Tokens/Monat je LLM-Aufruf pro Turn
Output : 15 × 800    × 30 Tage            ≈  0,36 M Tokens/Monat

Claude Sonnet 5 ($2/MTok in, $10/MTok out):
  1 Aufruf/Turn :  6,75 × $2  + 0,36 × $10  ≈  $13,50 + $3,60  ≈  $17/Monat
  3 Aufrufe/Turn: 20,25 × $2  + 0,36 × $10  ≈  $40,50 + $3,60  ≈  $44/Monat
```

**Realistisch: $20–45/Monat** bei normalem Betrieb, je nach Anzahl der Tool-Runden.
Gemessen ist das nicht: Token-Telemetrie fehlt bisher (geplant, siehe
[03 §8](03-agent-design.md#8-evaluierung)).

Kostenhebel in absteigender Wirkung:
1. **Prompt-Caching** (nicht konfiguriert): Persona, Kennzahlen-Katalog und
   Tool-Schemas (≈ 2.100 Tokens) sind statisch; innerhalb der Tool-Runden eines
   Turns wiederholt sich zusätzlich die gesamte Historie. Cache-Reads kosten ein
   Zehntel des Input-Preises.
2. **Modell-Routing** (nicht gebaut): einfache Abfragen auf ein kleineres Modell
   (Claude Haiku 5.5: $0,10 / $0,50 pro MTok bis 100K Prompt-Tokens).
3. **Tageslimit** je Nutzer konfigurierbar (nicht gebaut; verhindert Kostenausreißer).

### 6.3 Gesamtkosten

| Szenario | €/Monat |
|---|---|
| Minimalbetrieb (Betreiber allein, wenig Chat) | ~€ 12 |
| Normalbetrieb (5 Nutzer, ∅ 3 Turns/Tag) | ~€ 30 – 55 |
| Intensivnutzung (viele Analysen, Planungen) | ~€ 70+ |

Schätzwerte (Infrastruktur + LLM, Wechselkurs ≈ 1:1 angenommen), nicht gemessen.

---

## 7. Erste Inbetriebnahme — Schritt-für-Schritt

```
Phase 0 — Fundament
  □ VM anlegen, SSH-Zugang, UFW (nur 22, 80, 443 offen)
  □ Docker installieren
  □ /etc/kairos/.env anlegen und befüllen (KEK generieren!)
  □ docker compose up -d
  □ Datenbank-Migrations-Log prüfen (migrate-Container)
  □ https://{domain}/healthz → HTTP 200
  □ Erster Nutzer (Betreiber) anlegt: Google-Login testen
  □ Backup-Job manuell auslösen, Restore auf frischer VM durchführen
    (noch nicht gebaut, siehe §4 -- braucht erst ein Backup-Ziel)
  □ Uptime-Kuma-Alerts konfigurieren
    (noch nicht gebaut, siehe deploy/docker-compose.yml "Zielbild"-Block)

Phase 1 — Garmin
  □ Garmin-Verbindung im Onboarding herstellen
  □ Backfill starten, Fortschritt im Dashboard beobachten
  □ Stichprobenvergleich 10 zufällige Tage vs. Garmin Connect

Phase 2 — Kalender
  □ Google-Login (verbindet gleichzeitig Kalender)
  □ Apple/iCloud CalDAV-Verbindung
  □ Sync-Test: Termin anlegen, bestätigen, in Quelle prüfen
```
