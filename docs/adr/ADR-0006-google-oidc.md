# ADR-0006 — Auth-Provider: Google OIDC statt self-hosted IdP

**Status:** Akzeptiert  
**Datum:** 2026-08-02  
**Entscheider:** Betreiber

---

## Kontext

Kairos braucht Nutzer-Authentifizierung für 5 bekannte Personen. Bewertet wurden
**Authentik** (self-hosted OIDC), **Authelia** (leichter self-hosted IdP) und
**Google OIDC** (externer Provider).

Zusätzliche Rahmenbedingung: VM-Ressourcen sollen minimal gehalten werden, da
diese direkt die monatlichen Kosten bestimmen.

---

## Entscheidung

**Google OIDC** als einziger Auth-Provider.

---

## Begründung

| Kriterium | Authentik | Authelia | Google OIDC |
|---|---|---|---|
| RAM-Overhead | ~400 MB | ~80 MB | **0 MB** |
| Wartungsaufwand | mittel | gering | **keine** |
| MFA | ✅ eingebaut | ✅ TOTP | ✅ Google-seitig |
| Externe Abhängigkeit | keine | keine | **Google** |
| Setup-Aufwand | hoch | mittel | **minimal** |

**Ausschlaggebend:** Alle 5 Nutzer haben Google-Accounts. Google übernimmt
Passwort-Management, MFA und Account-Recovery — das sind Probleme, die selbst
gut zu lösen aufwändig ist.

**Kombinierter Flow:** Da Kalender-Zugang ebenfalls Google OAuth benötigt, deckt
ein einziger Authorization-Request beide Anforderungen ab (`openid email profile`
+ `calendar`-Scope). Das entfällt bei jedem anderen Ansatz.

**Testing-App-Status:** Mit 5 explizit eingetragenen Test-Nutzern in der Google
Cloud Console laufen Refresh-Tokens unbegrenzt — kein Verifikationsprozess nötig.

---

## Konsequenzen

### Positiv
- Kein Authentik-Container: spart ~400 MB RAM und ~1–2 h Konfigurationsaufwand.
- Passwort-Reset, Account-Lockout, MFA: vollständig delegiert an Google.
- Login- und Kalender-OAuth in einem Flow.

### Einschränkungen
- **Externe Abhängigkeit:** Ist Google nicht erreichbar, können sich Nutzer nicht
  einloggen. Bei 99,9+ % Google-Uptime akzeptabel für ein privates Tool.
- **Google-Account Pflicht:** Alle 5 Nutzer müssen einen Google-Account haben
  (bestätigt).
- **Google kann Auth-Policy ändern.** Unwahrscheinlich für OIDC-Basics; Risiko
  durch `Testing`-App-Status mitigiert.

### Upgrade-Pfad
Falls ein Nutzer ohne Google-Account hinzukommt oder Google OIDC Probleme bereitet:
Authelia als leichtgewichtiger Ersatz (~80 MB, TOTP, CalDAV-unabhängig) — der
OAuth-Flow in der App bleibt identisch, nur der `issuer` ändert sich.
