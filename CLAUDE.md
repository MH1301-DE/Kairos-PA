# Kairos-PA — Claude Code Instructions

## Session Start Protocol

At the start of every session in this repository, do the following **before** responding:

### 1. Read the handover document
```
Read: docs/HANDOVER.md
```

### 2. Check for agent commits
```bash
git log --format="%h|%an|%ae|%s" -20
```

**Human developers** (skip diff review for these):
- `Maximilian Haenel` — mhaenel@deloitte.de
- `Maximilian Haenel` — max.haenel@t-online.de

For every commit by a **different author**, read its diff:
```bash
git show <hash>
```

### 3. Invoke the kairos-handover skill
If the Skill tool is available, invoke `kairos-handover` to load the full protocol.

## Project Conventions

- **Language:** Python 3.14, FastAPI, SQLAlchemy async
- **Linting:** `ruff` (line-length 100) + `mypy --strict`
- **Tests:** `.venv/bin/python -m pytest -q` (Windows: `.venv/Scripts/python -m pytest -q`) → must be 109 passed, 0 skipped (0 skipped requires Docker running for the testcontainers tests)
- **Commits:** conventional commits (`feat(scope):`, `fix:`, `chore:`)
- **No docstrings** on code you didn't change
- **Comments:** one short line only — state what the code cannot show, not what it does

## Non-Negotiable Rules

| Rule | Reason |
|---|---|
| FIT download = ZIP, always extract | `ActivityDownloadFormat.ORIGINAL` returns a zip, not raw .fit |
| `activity_list` before `activity_fit` | `activity_record.activity_id` is a FK |
| `install_rls_listener(session, user_id)` on every write session | FORCE ROW LEVEL SECURITY on all tenant tables |
| Use `garminconnect`, never `garth` | garth deprecated March 2026 (Cloudflare block) |
| metric_def seeds must exist | `wellness_sample.metric_id` is a non-null FK |
| `token_json len > 512` → inline token | garminconnect treats long strings as inline token data |
