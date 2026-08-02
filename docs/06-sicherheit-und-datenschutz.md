# 06 — Sicherheit

Kairos verarbeitet Gesundheitsdaten. Alle Sicherheitsmaßnahmen folgen dem Prinzip **Defense in Depth**: kein
einzelner Mechanismus ist die letzte Verteidigungslinie.

---

## 1. Prinzipien

1. **Secrets gehören nie in die Datenbank und nie ins Repository.** Schlüssel,
   Tokens und Passwörter leben ausschließlich in der `.env`-Datei (außerhalb des
   Repos, `chmod 600`) oder in einem Secret-Store.
2. **Minimale Exposition.** Kein Service ist öffentlich erreichbar, der es nicht
   sein muss. Postgres und Redis haben kein Port-Mapping nach außen.
3. **Verschlüsselung in allen Schichten.** In Transit (TLS), at Rest (DEK/KEK),
   in der Datenbank (verschlüsselte Credentials).
4. **Kein Trust durch Lage.** Inhalte aus externen Quellen (Kalender, Mail,
   Garmin-Notizen) werden nie als vertrauenswürdig behandelt, unabhängig davon,
   über welchen Kanal sie kommen.
5. **Schreibvorgänge brauchen menschliche Bestätigung.** Der Agent kann nichts
   ausführen, was nicht bestätigt wurde — das ist gleichzeitig Bedienkomfort und
   Sicherheitsmechanismus.

---

## 2. Secrets & Schlüsselmanagement

### 2.1 Schlüsselhierarchie

```
KAIROS_KEK  (Master Key Encryption Key)
    │  AES-256-GCM, 32 Byte, außerhalb der VM in einem Passwort-Manager
    │  NIEMALS in der DB, NIEMALS im Repo, NIEMALS im Backup
    │
    └─▶ DEK_user_1  (Data Encryption Key je Nutzer)
    └─▶ DEK_user_2  …
        │  AES-256-GCM, zufällig generiert beim User-Onboarding
        │  verschlüsselt mit KEK, gespeichert als app_user.dek_wrapped (bytea)
        │
        └─▶ connection.credentials_enc  (OAuth-Tokens, Passwörter)
            │  verschlüsselt mit DEK des Nutzers
            └─▶ Garmin-Session-Token, Google-Refresh-Token, Apple-App-Password, …
```

**Envelope Encryption:** Der KEK verlässt die Anwendungsebene nie. Zum
Ver-/Entschlüsseln wird der DEK des Nutzers zur Laufzeit in den Speicher geladen,
verwendet und danach wieder verworfen. Kompromittierung eines DEK betrifft nur
einen Nutzer; Kompromittierung des KEK erfordert sofortige Schlüsselrotation.

### 2.2 Secret-Rotation

| Secret | Rotationsstrategie |
|---|---|
| KAIROS_KEK | Manuelle Rotation: neuen KEK generieren, alle DEKs re-encrypten, `.env` aktualisieren, Neustart |
| OAuth-Tokens (Google, Apple) | Automatisch über Refresh-Token-Mechanismus; bei Kompromittierung: Verbindung trennen + neu verbinden |
| Postgres-Passwort | Rotation via `ALTER USER`, `.env` updaten, Neustart |
| SESSION_SECRET | `.env` updaten, Neustart (alle aktiven Sessions werden invalidiert) |

### 2.3 `.env`-Datei

```bash
# Außerhalb des Repos, chmod 600, nie einchecken
KAIROS_KEK=<32-Byte-Base64>        # Master Key — NIEMALS ins Backup
POSTGRES_PASSWORD=<zufällig, 32+>
REDIS_PASSWORD=<zufällig, 32+>
GOOGLE_CLIENT_ID=<aus Google Cloud Console>
GOOGLE_CLIENT_SECRET=<aus Google Cloud Console>
SESSION_SECRET=<zufällig, 32+>    # HMAC-Key für Session-Cookies
MINIO_USER=kairos
MINIO_PASSWORD=<zufällig, 32+>
DOMAIN=kairos.example.com
```

`.gitignore` enthält `.env`, `*.env`, `deploy/.env` — erzwungen durch CI-Check
(kein Commit mit `KAIROS_KEK` im Diff möglich).

---

## 3. Authentifizierung

### 3.1 Nutzer-Auth: Google OIDC

Alle 5 Nutzer haben Google-Accounts; Google dient als OIDC-Provider. Kein
self-hosted IdP — null zusätzliche Container, null Wartung.
MFA wird über das Google-Konto gesteuert (2FA empfohlen, nicht erzwungen durch
Kairos — liegt in der Eigenverantwortung der geschlossenen Nutzergruppe).
Begründung: [ADR-0006](adr/ADR-0006-google-oidc.md).

**Login + Kalender in einem Flow:** Da Kalender-Zugang ebenfalls Google OAuth
benötigt, werden beide Scopes in einer einzigen Authorization-Anfrage kombiniert:

```
1.  Kairos generiert state = secure_random(32) → Redis (TTL 10 min)
2.  Vollständiger Redirect zu Google:
    https://accounts.google.com/o/oauth2/v2/auth
        ?client_id={GOOGLE_CLIENT_ID}
        &redirect_uri=https://{domain}/auth/callback
        &scope=openid email profile https://www.googleapis.com/auth/calendar
        &response_type=code
        &state={state}
        &access_type=offline
        &prompt=consent
3.  Nutzer meldet sich im Google-Login-Fenster an (läuft auf Google-Infrastruktur,
    Kairos sieht das Passwort nie)
4.  Google redirectet zurück: /auth/callback?code=…&state=…
5.  Kairos prüft state (CSRF-Schutz), tauscht code gegen Tokens:
    POST https://oauth2.googleapis.com/token
    → id_token (JWT, für Login) + refresh_token (für Kalender)
6.  id_token wird validiert: RS256-Signatur, aud == client_id, iss, exp
    → Nutzer-Session erstellt (httpOnly-Cookie mit Session-ID → Redis)
7.  refresh_token wird mit DEK des Nutzers verschlüsselt
    → connection.credentials_enc  (für Kalender-Sync)
8.  access_token nur im Speicher, nie persistiert
```

**Erlaubte Nutzer:** Da Kairos nicht öffentlich ist, wird die Google Cloud
App im Status "Testing" belassen (max. 100 Test-Nutzer). Die 5 Nutzer werden
explizit als Test-User eingetragen — kein Verifikationsprozess bei Google nötig,
kein Ablauf von Refresh-Tokens nach 7 Tagen.

**Apple/iCloud:** App-Specific Password wird im Onboarding-UI eingegeben
(HTTPS, serverseitig sofort mit DEK verschlüsselt, nie im Log oder Response).

---

## 4. Netzwerksicherheit

### 4.1 Docker-Netzwerktopologie

```
Internet ──▶ Caddy (edge-Netzwerk, Port 80/443)
                │
                └──▶ alle anderen Services (internal-Netzwerk, kein Port-Mapping)
                     Postgres, Redis, API, Worker, MinIO
```

**Kein Service außer Caddy ist von außen erreichbar.** Postgres und Redis haben
bewusst kein `ports:`-Mapping. Ein Angreifer, der in einen App-Container gelangt,
kommt nicht direkt an die Datenbank.

### 4.2 TLS (Caddy)

- Automatisches TLS via Let's Encrypt (ACME), HTTP-01-Challenge.
- **HSTS** mit `max-age=31536000; includeSubDomains` im Response-Header.
- TLS 1.2 minimum, TLS 1.3 bevorzugt.
- Keine veralteten Cipher-Suites (Caddy-Default ist ausreichend sicher).

### 4.3 Rate Limiting

Caddy übernimmt Basic Rate Limiting auf Layer 7:

| Route | Limit |
|---|---|
| `/auth/*` | 10 Req/min je IP |
| `/connectors/*/callback` | 5 Req/min je IP |
| `/api/*` | 120 Req/min je Nutzer (JWT-gebunden) |
| `/webhooks/*` | 60 Req/min je IP |

### 4.4 Content Security Policy

Die PWA liefert CSP-Header, die Inline-Scripts und externe Ressourcen unterbinden:

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  connect-src 'self';
  img-src 'self' data:;
  frame-ancestors 'none'
```

Der Google-OAuth-Flow läuft als Server-seitiger Redirect — kein Google-JS-SDK,
kein clientseitiger `fetch` zu Google. Daher ist keine externe `connect-src`
erforderlich.

---

## 5. Datenverschlüsselung in der Datenbank

### 5.1 Row Level Security

Jede fachliche Tabelle trägt `user_id`. RLS erzwingt Mandantentrennung auf DB-Ebene:

```sql
-- Anwendung setzt pro Transaktion:
SET LOCAL app.current_user_id = '<uuid>';

-- RLS-Policy auf jeder Tabelle (Beispiel):
CREATE POLICY tenant_isolation ON wellness_sample
  USING (user_id = current_setting('app.current_user_id')::uuid);
```

Ein vergessener `WHERE`-Filter im ORM-Code führt zu **0 Zeilen**, nicht zu einem
Datenleck. **CI-Test:** Kein Merge ohne Policy auf jeder Tabelle mit `user_id`-Spalte.

### 5.2 Verschlüsselte Credentials

`connection.credentials_enc` enthält OAuth-Tokens und Passwörter, verschlüsselt
mit dem DEK des Nutzers (AES-256-GCM). Der Klartext existiert nur im Arbeits-
speicher der Anwendung während eines aktiven Sync-Jobs — nie auf Disk, nie im Log.

---

## 6. Prompt Injection

Externe Inhalte (Kalendereinladungen, Garmin-Aktivitätsnotizen, Gmail) sind
**fremdkontrolliert** und müssen als Angriffsfläche behandelt werden.

Maßnahmen:

1. **Umhüllung im Kontext:** Externe Inhalte werden immer als `[EXTERNE DATEN: ...]`
   markiert übergeben. Der System-Prompt erklärt explizit, dass darin enthaltene
   Anweisungen nicht befolgt werden.
2. **Tools können keine Schreibvorgänge direkt auslösen.** Alle Write-Tools geben
   ein Proposal zurück — die menschliche Bestätigung ist die eigentliche Absicherung.
3. **Mail-Inhalte werden vor Übergabe sanitisiert:** kein HTML, keine klickbaren
   Links, nur extrahierter Nutztext.
4. **Read-Tools liefern nur Daten.** Ein kompromittierter Kalendertermin kann den
   Agenten täuschen, aber nicht zur Ausführung bringen.

---

## 7. Audit & Logging

```
audit_log(user_id, actor, action, target, result, occurred_at)
```

Alle agent-initiierten Schreibvorgänge werden geloggt. Retention: 24 Monate.
Der Nutzer kann seinen eigenen Audit-Log einsehen.

**Was nicht geloggt wird:** Konversationsinhalte (nur Metadaten: "Agent hat Termin
vorgeschlagen"). Konversations-Inhalte sind in der `message`-Tabelle.

---

## 8. Backup-Sicherheit

```yaml
# täglich 02:00
backup:
  tool: restic
  destination: zweiter Standort (separater Anbieter, separates Konto)
  encryption: AES-256 (restic-eigener Key, getrennt vom KAIROS_KEK)
  what: pg_dump + MinIO-Daten
  what_not: KAIROS_KEK  ← gehört nie ins Backup
  retention: 7 täglich, 4 wöchentlich, 3 monatlich
```

Der **KAIROS_KEK gehört nicht ins Backup** — er ist das letzte Geheimnis.
Geht er verloren, sind verschlüsselte Credentials unlesbar (Garmin, Google, Apple —
alle müssen neu verbunden werden). Das ist bewusst so: Ein gestohlenes Backup ist
ohne KEK nutzlos.

---

## 9. Sicherheits-Checkliste für Phase 0

Keine Phase-0-Abnahme ohne:

- [ ] `.env` außerhalb des Repos, `chmod 600`, kein Git-Tracking
- [ ] CI-Check: kein Commit mit `KAIROS_KEK`, `POSTGRES_PASSWORD` o. ä. im Diff
- [ ] RLS auf allen fachlichen Tabellen, CI-Test bestätigt das
- [ ] Postgres: kein `ports:`-Mapping in `docker-compose.yml`
- [ ] TLS aktiv, HSTS-Header gesetzt
- [ ] MFA Google-seitig: alle 5 Test-Nutzer in Google Cloud Console eingetragen
- [ ] Backup läuft, Restore einmal durchgeführt und dokumentiert
- [ ] `no-new-privileges: true` auf allen App-Containern (bereits in Compose)
