# Boot up / Boot down / Reboot Implementation Plan

**Goal:** `docker compose -f deploy/docker-compose.yml up -d` actually builds
and boots the current app (api, web, postgres+timescaledb, redis, caddy) end
to end, survives a host reboot unattended, and stops cleanly with `down`.
Design spec: `docs/superpowers/specs/2026-09-12-boot-lifecycle-design.md` --
read it first.

**Tech Stack:** Docker, Docker Compose v2, Caddy 2, existing FastAPI/SvelteKit
apps -- no new Python/JS dependencies (adapter-node is already installed).

## Global Constraints

- No worker/scheduler/minio/backup/uptime services get built -- they move to
  a clearly labeled "not built yet" comment block, per the design spec.
- `ruff`/`mypy --strict`/`pytest -q` must stay green after the `/healthz`
  addition.
- Verify locally via Docker Desktop with an isolated compose project name
  (`-p kairos-lifecycle-check`) so it never collides with the running dev
  containers (`deploy-postgres-1`/`deploy-redis-1` on the default project).

---

## Task 1: `/healthz` endpoint

**Files:**
- Modify: `src/kairos/api.py` (or a new tiny router if `api.py` doesn't hold
  routes directly -- check first)
- Test: new/existing router test file

- [ ] **Step 1: Failing test** -- `GET /healthz` returns 200 with
  `{"status": "ok"}`, no auth required.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(ops): add unauthenticated /healthz endpoint"
  ```

---

## Task 2: `deploy/Dockerfile` (API image)

**Files:**
- Create: `deploy/Dockerfile`, `.dockerignore` (repo root)

**Interfaces:**
- Multi-stage: builder installs build deps + `pip install .` into a venv;
  runtime stage (python:3.12-slim) copies the venv, runs as a non-root user,
  `CMD ["uvicorn", "kairos.api:app", "--host", "0.0.0.0", "--port", "8000"]`.
- `.dockerignore` excludes `.venv/`, `web/`, `.git/`, `__pycache__/`,
  `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`.

- [ ] **Step 1: Write the Dockerfile + .dockerignore.**
- [ ] **Step 2: Verify** -- `docker build -f deploy/Dockerfile -t kairos-api:check .`
  succeeds locally.
- [ ] **Step 3: Commit**
  ```bash
  git commit -m "feat(ops): add API Dockerfile"
  ```

---

## Task 3: `web/Dockerfile` (frontend image)

**Files:**
- Create: `web/Dockerfile`, `web/.dockerignore`

**Interfaces:**
- Multi-stage: builder (node:22-slim) runs `npm ci` + `npm run build`;
  runtime stage copies `build/`, `package.json`, and a production-only
  `node_modules` (`npm ci --omit=dev` after copying `package*.json` into the
  runtime stage). `CMD ["node", "build/index.js"]`. Documents required env
  vars in a comment: `PORT`, `ORIGIN`, `HOST`.
- `web/.dockerignore` excludes `node_modules/`, `build/`, `.svelte-kit/`,
  `tests/`.

- [ ] **Step 1: Write the Dockerfile + .dockerignore.**
- [ ] **Step 2: Verify** -- `docker build -f web/Dockerfile -t kairos-web:check ./web`
  succeeds locally.
- [ ] **Step 3: Commit**
  ```bash
  git commit -m "feat(ops): add web Dockerfile"
  ```

---

## Task 4: `deploy/Caddyfile`

**Files:**
- Create: `deploy/Caddyfile`

**Interfaces:**
- `{$DOMAIN}` block: `handle /api/* { reverse_proxy api:8000 }`,
  `handle /auth/* { reverse_proxy api:8000 }`, `handle { reverse_proxy web:3000 }`.
  Automatic HTTPS is Caddy's default behavior, no extra directive needed
  unless `DOMAIN=localhost` for local testing (add a `:80`/`tls internal`
  fallback note in a comment for the local verification step).

- [ ] **Step 1: Write the Caddyfile.**
- [ ] **Step 2: Commit**
  ```bash
  git commit -m "feat(ops): add Caddy reverse-proxy config"
  ```

---

## Task 5: Trim `deploy/docker-compose.yml` to what's real

**Files:**
- Modify: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`

**Interfaces:**
- Keep `caddy`, `web`, `api`, `migrate`, `postgres`, `redis` -- fix the `api`
  healthcheck to hit the new `/healthz`, add `ORIGIN`/`PORT` env to `web`.
- Move `worker`, `scheduler`, `minio`, `backup`, `uptime` into a single
  commented-out block headed `# Zielbild laut docs/07 §1 -- noch nicht
  gebaut, siehe docs/superpowers/specs/2026-09-12-boot-lifecycle-design.md`.
- `deploy/.env.example`: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `KAIROS_KEK`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `DOMAIN`,
  `LLM_API_KEY`, `GIT_SHA` (optional, comment: defaults to `dev`).

- [ ] **Step 1: Edit compose file + write `.env.example`.**
- [ ] **Step 2: Commit**
  ```bash
  git commit -m "feat(ops): trim docker-compose.yml to services that actually build"
  ```

---

## Task 6: Local end-to-end verification + docs

**Files:**
- Modify: `docs/07-deployment-und-betrieb.md` (§3 Erstinstallation matches
  the trimmed compose file; new "Boot up / Boot down / Reboot" subsection)
- Modify: `docs/HANDOVER.md` (completion note, same pattern as every other
  finished plan this session)

- [ ] **Step 1:** `docker compose -f deploy/docker-compose.yml -p kairos-lifecycle-check --env-file <local test .env> build`
  -- all images build.
- [ ] **Step 2:** `... up -d` against the isolated project name, poll
  `GET /healthz` through the `api` container until 200, then
  `... down -v` to clean up. Document the exact commands used and the
  result in the HANDOVER note.
- [ ] **Step 3:** Update `docs/07-deployment-und-betrieb.md` §3.1 (remove
  steps that reference not-yet-built services), add the "Boot up / Boot
  down / Reboot" subsection from the design spec §2.8.
- [ ] **Step 4: Commit**
  ```bash
  git commit -m "docs: verify boot-lifecycle stack locally, document boot up/down/reboot"
  ```

---

## Acceptance (whole-plan)

`docker compose -f deploy/docker-compose.yml build` succeeds from a clean
checkout. A local `up -d` brings up api+web+postgres+redis+caddy and
`/healthz` answers 200. `docs/07-deployment-und-betrieb.md` has an explicit,
copy-pasteable Boot up/Boot down/Reboot section. All existing tests still
pass; `ruff`/`mypy --strict` clean across the diff.

## Bewusst nicht Teil dieses Plans

Job-Queue/Scheduler, Object-Storage, Backup/Restore, Monitoring/Alerting,
tatsächliche VM-Provisionierung auf einem echten Server -- siehe design
spec's "Bewusst nicht Teil dieser Spec".
