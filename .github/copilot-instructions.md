# Kairos-PA — GitHub Copilot Instructions

## Session Start Protocol

At the start of every session in this repository:

1. **Read `docs/HANDOVER.md`** for full project context.

2. **Check for agent commits** — run:
   ```
   git log --format="%h|%an|%ae|%s" -20
   ```
   Human developers: `Maximilian Haenel` (mhaenel@deloitte.de, max.haenel@t-online.de).
   For any other author, run `git show <hash>` to understand their changes.

3. **Invoke the `kairos-handover` skill** if the superpowers framework is active.

## Project Conventions

- Language: **Python 3.14**, FastAPI, SQLAlchemy async
- Linting: `ruff` (line-length 100), `mypy` (strict)
- Tests: `pytest -q` — must stay at 45 passed, 6 skipped
- Commits: conventional commits format (`feat(scope): ...`, `fix:`, `chore:`)
- No markdown docs unless explicitly requested
- Comments: one short line only, no docstrings on unchanged code

## Critical Rules

- FIT download = ZIP archive — always extract before decoding
- `activity_list` must run before `activity_fit` (FK dependency)
- Always call `install_rls_listener(session, user_id)` on sessions that write to RLS tables
- garth is deprecated — use garminconnect 0.3.x only
- metric_def seeds must exist before writing wellness_sample rows
