# 07 — Deployment & Betrieb

---

## 1. Infrastrukturübersicht

Kairos läuft auf **einer einzelnen Linux-VM** hinter Caddy. Kein Kubernetes, kein
Load Balancer, kein Managed Database-Service.

```
Internet
    │ HTTPS (443)
    ▼
┌─────────────────────────────────────────────────────┐
│ VM  (Hetzner Cloud, Ubuntu 24.04 LTS)               │
│                                                     │
│  Caddy ──▶ API  ──▶ Postgres+Timescale+pgvector     │
│         ──▶ Web        ──▶ Redis                    │
│                        ──▶ MinIO (FIT/Raw-Objekte)  │
│  Worker + Scheduler (arq)                           │
│  Backup-Job (restic, täglich 02:00)                 │
│  Uptime Kuma (Monitoring)                           │
└─────────────────────────────────────────────────────┘
```

Alle Services laufen als Docker Compose Stack unter `deploy/docker-compose.yml`.

---

## 2. VM-Sizing

### 2.1 RAM-Bedarf

| Service | Typischer RSS |
|---|---|
| Postgres + TimescaleDB (`shared_buffers=256 MB`) | ~700 MB |
| API (FastAPI, 2 Workers) | ~200 MB |
| arq Worker | ~150 MB |
| Scheduler | ~80 MB |
| Redis | ~50 MB |
| Caddy | ~30 MB |
| MinIO | ~100 MB |
| Uptime Kuma | ~80 MB |
| OS + Docker-Overhead | ~400 MB |
| **Summe** | **~1,8 GB** |

Peak (Backfill + Metrics-Recompute gleichzeitig): +400 MB → ~2,2 GB.

### 2.2 Empfehlung

**Hetzner Cloud CX22** — 2 vCPU, 4 GB RAM, 40 GB SSD, ~€ 4,50/Monat.

| Ressource | Verfügbar | Bedarf | Puffer |
|---|---|---|---|
| RAM | 4 GB | ~2,2 GB Peak | ~1,8 GB ✅ |
| SSD | 40 GB | ~10 GB (5 Jahre) | ~30 GB ✅ |
| vCPU | 2 | Burst bei Sync | ausreichend ✅ |

**Upgrade-Trigger:** RAM-Auslastung dauerhaft > 80 % → CX32 (8 GB, ~€ 8,50/Monat).
CPU ist kein Engpass; Postgres und arq sind I/O-gebunden, nicht CPU-gebunden.

### 2.3 Postgres-Tuning für 4 GB RAM

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

---

## 4. Backup & Wiederherstellung

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

**Uptime Kuma** (im Stack) überwacht:

| Check | Intervall | Alert |
|---|---|---|
| `https://{domain}/healthz` (API) | 1 min | Push-Notification |
| Postgres (TCP Port intern) | 1 min | Push-Notification |
| Garmin-Sync-Job (letzter Erfolg < 26 h) | 15 min | Push-Notification |
| Backup-Job (letzter Erfolg < 26 h) | 15 min | Push-Notification |

Alerting: Uptime Kuma unterstützt Push-Notifications (Pushover, Telegram, E-Mail).
Kein separater Alertmanager nötig.

**Logs:** `docker compose logs -f api` im Normalbetrieb; structured JSON-Logs
(Python `structlog`), filterbar nach `user_id`, `request_id`, `level`.

---

## 6. Kosten

### 6.1 Infrastruktur

| Posten | Kosten/Monat |
|---|---|
| Hetzner CX22 | ~€ 4,50 |
| Domain (.com, .de) | ~€ 1,00 |
| Backup-Ziel (Hetzner Storage Box 100 GB) | ~€ 1,00 |
| **Infrastruktur gesamt** | **~€ 6,50** |

### 6.2 LLM-API (Anthropic Claude)

Schätzung bei aktivem Betrieb (alle 5 Nutzer, Claude Sonnet):

| Parameter | Annahme |
|---|---|
| Turns/Tag gesamt | ~15 (∅ 3 je Nutzer) |
| Input-Tokens/Turn | ~15.000 (Median-Budget) |
| Output-Tokens/Turn | ~800 |
| Cache-Hit-Rate | ~25 % (System-Prompt + Core-Tools) |

```
Input  : 15 × 15.000 × 30 Tage × (1 − 0,25 Cache)  ≈  5,1 M Tokens/Monat
Output : 15 × 800    × 30 Tage                       ≈  0,36 M Tokens/Monat

Claude Sonnet ($3/MTok in, $15/MTok out):
  5,1 × $3  +  0,36 × $15  ≈  $15,30 + $5,40  ≈  $21/Monat
Cache-Savings (25 %):  −$3,80
```

**Realistisch: $15–25/Monat** bei normalem Betrieb, $40–50 bei intensiver Nutzung.

Kostenhebel in absteigender Wirkung:
1. **Prompt-Caching** (bereits eingebaut): spart ~20–30 %
2. **Modell-Routing**: einfache Abfragen (Kalender, Schnellinfo) auf Claude Haiku
   ($0.25/MTok) → spart ~40 % bei gleicher Qualität für Routineabfragen
3. **Tageslimit** je Nutzer konfigurierbar (verhindert Kostenausreißer)

### 6.3 Gesamtkosten

| Szenario | €/Monat |
|---|---|
| Minimalbetrieb (Betreiber allein, wenig Chat) | ~€ 10 |
| Normalbetrieb (5 Nutzer, ∅ 3 Turns/Tag) | ~€ 25 |
| Intensivnutzung (viele Analysen, Planungen) | ~€ 55 |

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
  □ Uptime-Kuma-Alerts konfigurieren

Phase 1 — Garmin
  □ Garmin-Verbindung im Onboarding herstellen
  □ Backfill starten, Fortschritt im Dashboard beobachten
  □ Stichprobenvergleich 10 zufällige Tage vs. Garmin Connect

Phase 2 — Kalender
  □ Google-Login (verbindet gleichzeitig Kalender)
  □ Apple/iCloud CalDAV-Verbindung
  □ Sync-Test: Termin anlegen, bestätigen, in Quelle prüfen
```
