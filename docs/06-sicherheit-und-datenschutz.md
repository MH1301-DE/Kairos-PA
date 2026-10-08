# 06 — Sicherheit

> **Stand 2026-10-08.** Beschreibt den Ist-Stand im Code. Nicht gebaute Maßnahmen
> sind als **Zielbild (nicht umgesetzt)** markiert; die Checkliste in §9 zeigt den
> Stand je Punkt.

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
        └─▶ connection.credentials_enc  (Tokens, keine Passwörter)
            │  verschlüsselt mit DEK des Nutzers
            └─▶ Garmin-Token-JSON, Google-Refresh-Token
                (Apple-App-Password: Zielbild, kein CalDAV-Connector)
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
LLM_API_KEY=<API-Key des LLM-Anbieters, deployment-weit>
DOMAIN=kairos.example.com
```

`.gitignore` enthält `.env`. *Zielbild (nicht umgesetzt):* ein CI-Check, der Commits
mit `KAIROS_KEK` o. ä. im Diff verhindert — `ci.yml` führt nur ruff, mypy und pytest
aus. `MINIO_*` entfällt, solange es keinen Object Store gibt.

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

**Garmin:** E-Mail und Passwort werden im Onboarding-UI eingegeben (HTTPS) und nur
für den einmaligen Login verwendet. Gespeichert wird ausschließlich das Token-JSON,
verschlüsselt mit dem DEK; das Passwort wird nie persistiert und bei einem MFA-Retry
nicht an den Client zurückgegeben.

**Apple/iCloud** — *Zielbild (nicht umgesetzt):* App-Specific Password im
Onboarding-UI (HTTPS, serverseitig sofort mit DEK verschlüsselt, nie im Log oder
Response).

---

## 4. Netzwerksicherheit

### 4.1 Docker-Netzwerktopologie

```
Internet ──▶ Caddy (edge-Netzwerk, Port 80/443)
                │
                └──▶ alle anderen Services (internal-Netzwerk, kein Port-Mapping)
                     Web, API, Postgres, Redis   (Worker, MinIO: Zielbild)
```

**Kein Service außer Caddy ist von außen erreichbar.** Postgres und Redis haben
bewusst kein `ports:`-Mapping. Ein Angreifer, der in einen App-Container gelangt,
kommt nicht direkt an die Datenbank.

### 4.2 TLS (Caddy)

- Automatisches TLS via Let's Encrypt (ACME), Caddy-Default (`deploy/Caddyfile`).
- **HSTS** mit `max-age=31536000; includeSubDomains` im Response-Header —
  *Zielbild (nicht umgesetzt):* Das Caddyfile setzt heute keine `header`-Direktive.
- TLS 1.2 minimum, TLS 1.3 bevorzugt.
- Keine veralteten Cipher-Suites (Caddy-Default ist ausreichend sicher).

### 4.3 Rate Limiting

**Ist:** Das `deploy/Caddyfile` (Commit `82326df`) enthält **kein** Rate-Limit.
Standard-Caddy hat dafür keine eingebaute Direktive; nötig wäre ein Plugin (z. B.
`caddy-ratelimit`) und damit ein eigenes Caddy-Image.

Vorhandene Limits in der Anwendung:

| Stelle | Limit |
|---|---|
| `POST /api/sync/garmin/backfill` | 300 s Cooldown je Nutzer → 429 mit `Retry-After` |
| `POST /api/sync/google_calendar/sync` | 60 s Cooldown je Nutzer → 429 mit `Retry-After` |
| Sync gleichen Kinds parallel | 409 |
| Garmin-Schreibzugriffe (geplant, [Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) D.7) | ≥ 1,0 s Abstand, ≤ 300 je Nutzer und Stunde, nach 429 von Garmin 15 min Sperre |

*Zielbild (nicht umgesetzt)* — Rate Limiting auf Layer 7 in Caddy:

| Route | Limit |
|---|---|
| `/auth/*` | 10 Req/min je IP |
| `/api/*` | 120 Req/min je Nutzer (session-gebunden, über das `session_id`-Cookie) |
| `/webhooks/*` | 60 Req/min je IP (erst relevant mit Kalender-Push) |

### 4.4 Content Security Policy

*Zielbild (nicht umgesetzt):* Die PWA soll CSP-Header liefern, die Inline-Scripts und
externe Ressourcen unterbinden. Heute setzen weder SvelteKit noch Caddy einen
CSP-Header:

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
Datenleck. Gesetzt wird die Variable über `install_rls_listener(session, user_id)`
(`src/kairos/db/rls.py`). Alle Tabellen mit `user_id`-Spalte haben `FORCE ROW LEVEL
SECURITY` (geprüft 2026-10-08).

**Einschränkung:** Die App-Datenbankrolle ist derzeit Superuser und umgeht RLS damit
faktisch; die Policies wirken erst unter einer Least-Privilege-Rolle (offener Punkt,
siehe HANDOVER). *Zielbild (nicht umgesetzt):* ein CI-Test, der ohne Policy auf jeder
Tabelle mit `user_id`-Spalte keinen Merge zulässt.

### 5.2 Verschlüsselte Credentials

`connection.credentials_enc` enthält Tokens (Garmin-Token-JSON, Google-Refresh-
Token), keine Passwörter, verschlüsselt mit dem DEK des Nutzers (AES-256-GCM). Der Klartext existiert nur im Arbeits-
speicher der Anwendung während eines aktiven Sync-Jobs — nie auf Disk, nie im Log.

---

## 6. Prompt Injection

Externe Inhalte (Kalendereinladungen, Garmin-Aktivitätsnotizen, Gmail) sind
**fremdkontrolliert** und müssen als Angriffsfläche behandelt werden.

Maßnahmen:

1. **Umhüllung im Kontext** — *Zielbild (nicht umgesetzt):* Externe Inhalte sollen
   als `[EXTERNE DATEN: ...]` markiert übergeben werden, mit einer Regel im
   System-Prompt, darin enthaltene Anweisungen nicht zu befolgen. Heute gibt
   `query_calendar` Termintitel und -beschreibungen unmarkiert zurück.
2. **Tools können keine Schreibvorgänge direkt auslösen.** Alle bestätigungspflichtigen
   Tools (`write`/`destructive`) erzeugen ein Proposal — die menschliche Bestätigung
   ist die eigentliche Absicherung. Ausnahme: `remember` speichert sofort (nur im
   eigenen Gedächtnis des Nutzers, mit Undo).
3. **Mail-Inhalte werden vor Übergabe sanitisiert** — Zielbild, Gmail ist nicht
   angebunden.
4. **Read-Tools liefern nur Daten.** Ein kompromittierter Kalendertermin kann den
   Agenten täuschen, aber nicht zur Ausführung bringen.

---

## 7. Audit & Logging

**Ist:** Es gibt **keine** Tabelle `audit_log` (geprüft 2026-10-08) und kein
Audit-Logging. Nachvollziehbar sind agent-initiierte Schreibvorgänge heute nur über
die Konversation: Der bestätigte Tool-Call und sein Ergebnis stehen in
`conversation_message`.

*Zielbild (nicht umgesetzt; laut [Spec](superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md) D.7 wird die Tabelle mit den
Garmin-Schreibzugriffen angelegt):*

```
audit_log(user_id, actor, action, target, result, occurred_at)
```

Alle agent-initiierten Schreibvorgänge werden geloggt. Retention: 24 Monate.
Der Nutzer kann seinen eigenen Audit-Log einsehen.

**Was nicht geloggt wird:** Konversationsinhalte (nur Metadaten: "Agent hat Termin
vorgeschlagen"). Konversations-Inhalte sind in der Tabelle `conversation_message`.

---

## 8. Backup-Sicherheit

*Zielbild (nicht umgesetzt):* Der `backup`-Dienst ist in `deploy/docker-compose.yml`
auskommentiert; das Backup-Ziel ist noch nicht entschieden.

```yaml
# täglich 02:00
backup:
  tool: restic
  destination: zweiter Standort (separater Anbieter, separates Konto)
  encryption: AES-256 (restic-eigener Key, getrennt vom KAIROS_KEK)
  what: pg_dump (MinIO entfällt ohne Object Store)
  what_not: KAIROS_KEK  ← gehört nie ins Backup
  retention: 7 täglich, 4 wöchentlich, 3 monatlich
```

Der **KAIROS_KEK gehört nicht ins Backup** — er ist das letzte Geheimnis.
Geht er verloren, sind verschlüsselte Credentials unlesbar (Garmin, Google, Apple —
alle müssen neu verbunden werden). Das ist bewusst so: Ein gestohlenes Backup ist
ohne KEK nutzlos.

---

## 9. Sicherheits-Checkliste für Phase 0

Keine Produktiv-Abnahme ohne (Stand 2026-10-08):

- [x] `.env` nicht im Git (`.gitignore`); `chmod 600` auf der VM — offen bis zum Deployment
- [ ] CI-Check: kein Commit mit `KAIROS_KEK`, `POSTGRES_PASSWORD` o. ä. im Diff — offen
- [ ] RLS auf allen fachlichen Tabellen — **erfüllt** (FORCE RLS überall); CI-Test fehlt,
      App-Rolle ist noch Superuser — offen
- [x] Postgres und Redis: kein `ports:`-Mapping in `deploy/docker-compose.yml`
- [ ] TLS aktiv (Caddy, ja), HSTS-Header gesetzt — offen
- [ ] Rate-Limit an `/auth/*` und `/api/*` (Caddy-Plugin) — offen, siehe §4.3
- [ ] Alle Test-Nutzer in der Google Cloud Console eingetragen — offen
- [ ] Backup läuft, Restore einmal durchgeführt und dokumentiert — offen
- [x] `no-new-privileges: true` auf allen App-Containern (in Compose)
