# Dashboard-Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the "Minimum für User-Test" SvelteKit frontend for Kairos-PA — Google-OIDC-gated onboarding (Garmin login with MFA retry), a sync-status page, and a dashboard rendering the 8 metrics already exposed by `/api/metrics`.

**Architecture:** A new `web/` SvelteKit 2 (Svelte 5, TypeScript) app with `adapter-node`, sharing the existing `session_id` cookie with the FastAPI backend (same origin behind Caddy in production; Vite dev-proxy locally). One new thin FastAPI router (`POST /api/connections/garmin`, `GET /api/connections`) plus a one-line fix to `/auth/callback` are added to the backend to unblock onboarding. Dashboard tiles use a generic `MetricTile` dispatcher over 3 chart forms (value/bar/gauge) driven by a static module registry — not 8 bespoke components.

**Tech Stack:** SvelteKit ^2, Svelte ^5 (runes), TypeScript ^5, `echarts` ^5 (no `svelte-echarts` wrapper — see Global Constraints), `@vite-pwa/sveltekit`, `vitest` + `@testing-library/svelte`, `@playwright/test`. Backend additions: FastAPI (existing stack, no new dependencies).

## Global Constraints

- **Refinement over the design spec** (`docs/superpowers/specs/2026-08-11-dashboard-frontend-design.md`): the spec's chart-form table listed `training_load` and `hrv_baseline` as "line chart" and named `svelte-echarts` as the wrapper library. Both are corrected here: (1) `GET /api/metrics/{metric_id}` returns a single day's snapshot, not a series — there is no time-range endpoint in this plan's scope, so no module can render an actual trend line. `training_load` renders as a multi-stat value tile (CTL/ATL/TSB numbers); `hrv_baseline` renders as a gauge (today's value against the baseline band), reusing the same gauge component as `acwr`. Only 3 chart forms exist in this plan: `value`, `bar`, `gauge`. (2) The ECharts wrapper is a small hand-written component (`EChartsBase.svelte`) around the `echarts` package directly, not the third-party `svelte-echarts` package — removes a Svelte-5-compatibility risk from an external wrapper for one `echarts.init()` call.
- No backend third-party dependencies beyond what's already in `pyproject.toml`.
- Every new backend file: `ruff check` (line-length 100) + `mypy --strict` clean, conventional commit messages (`feat(scope):`/`fix(scope):`), per `CLAUDE.md`.
- Frontend: Svelte 5 runes syntax (`$state`, `$derived`, `$props`) — not legacy `export let`/reactive-statement syntax.
- `install_rls_listener(session, user_id)` on every backend session that writes to a tenant table, per `CLAUDE.md` — applies to the new connections router.
- Backend interpreter: `.venv/Scripts/python` (Windows venv). Frontend: run `npm` commands from inside `web/`.
- Every frontend `fetch` to the backend uses `credentials: 'include'` — sessions are cookie-based, not header-token-based (see `src/kairos/auth/deps.py`).
- `MetricResult.confidence` is a `Literal["high","medium","low","insufficient_data"]`, not an ordered scale — never compare it with `<`/`>`; map it through an explicit lookup.

---

## File Structure

```
src/kairos/routers/connections.py         new: POST /api/connections/garmin, GET /api/connections
src/kairos/api.py                          + connections_router
src/kairos/auth/google.py                  callback redirects to frontend instead of returning JSON
tests/test_connections_router.py           new

web/                                        new SvelteKit app
  package.json / svelte.config.js / vite.config.ts / tsconfig.json / playwright.config.ts
  src/
    hooks.server.ts                        auth-guard: redirect to /auth/login if no session cookie
    app.html / app.d.ts
    lib/
      api.ts                               typed fetch wrapper (credentials: include, error mapping)
      types.ts                             MetricResult, Confidence, ConnectionStatus, SyncJob
      modules.ts                           static module registry (8 entries) + gauge-config helpers
      components/
        EChartsBase.svelte                 thin echarts.init() wrapper, takes an EChartsOption
        ConfidenceBadge.svelte             confidence -> color/label lookup
        MetricTile.svelte                  dispatches to ValueTile/BarTile/GaugeTile by module.form
        ValueTile.svelte
        BarTile.svelte
        GaugeTile.svelte
    routes/
      +layout.svelte                       nav (Dashboard/Sync/Logout), renders slot
      +layout.server.ts                    loads current user email for the nav (from session)
      +page.svelte                         dashboard: renders MetricTile per module
      +page.server.ts                      load(): fetch all 8 modules' MetricResults
      onboarding/+page.svelte              Garmin login form + MFA retry state machine
      onboarding/+page.server.ts           form action calling POST /api/connections/garmin
      sync/+page.svelte                    connection status + sync job list
      sync/+page.server.ts                 load(): GET /api/connections + GET /api/sync/status
  static/
    manifest.webmanifest                   PWA manifest (name, icons, display: standalone)
  tests/
    unit/modules.test.ts
    unit/ConfidenceBadge.test.ts
    unit/ValueTile.test.ts
    e2e/onboarding.spec.ts
```

---

### Task 1: Scaffold the SvelteKit project

**Files:**
- Create: `web/` (entire scaffold via CLI, then modified)
- Modify: `web/svelte.config.js`, `web/vite.config.ts`

**Interfaces:**
- Produces: a running `npm run dev` server at `http://localhost:5173` proxying `/api/*` and `/auth/*` to the backend at `http://localhost:8000`.

- [ ] **Step 1: Scaffold via the SvelteKit CLI**

Run from the repo root:
```bash
npx sv create web
```
When prompted, choose: **Skeleton project**, **TypeScript**, and additionally enable **ESLint**, **Prettier**, **Vitest**, **Playwright** (all offered by the `sv create` wizard). Decline any demo/example content it offers to keep.

- [ ] **Step 2: Install `adapter-node` and `echarts`**

```bash
cd web
npm install @sveltejs/adapter-node echarts
npm install -D @testing-library/svelte @testing-library/jest-dom jsdom @vite-pwa/sveltekit
```

- [ ] **Step 3: Switch to `adapter-node`**

Edit `web/svelte.config.js` — replace the `adapter-auto` import and usage:

```javascript
import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter()
	}
};

export default config;
```

- [ ] **Step 4: Add the dev-proxy so the browser's cookie-bearing requests reach the backend**

Edit `web/vite.config.ts`:

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': { target: 'http://localhost:8000', changeOrigin: true },
			'/auth': { target: 'http://localhost:8000', changeOrigin: true }
		}
	}
});
```

- [ ] **Step 5: Verify the dev server boots**

Run: `npm run dev -- --open=false` (from `web/`), then in a second terminal: `curl -sf http://localhost:5173/ -o /dev/null && echo OK`
Expected: `OK`, no errors in the dev-server terminal. Stop the dev server (Ctrl+C) after verifying.

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold SvelteKit app with adapter-node and dev proxy"
```

---

### Task 2: Backend — `POST /api/connections/garmin` + `GET /api/connections`

**Files:**
- Create: `src/kairos/routers/connections.py`
- Modify: `src/kairos/api.py` (register the router)
- Test: `tests/test_connections_router.py`

**Interfaces:**
- Consumes: `GarminClient` (`src/kairos/connectors/garmin/client.py` — already exists, unmodified: `login(username, password, mfa_token=None) -> AuthTokens`, raises `NeedsMfaToken`/`InvalidCredentials`/`UpstreamUnavailable`), `current_user` (`kairos.auth.deps`), `Connection` model (`kairos.db.models`), `encrypt`/`kek_from_settings`/`wrap_dek` pattern already used in `kairos/routers/sync.py`'s `_build_garmin_client` (mirror it in reverse).
- Produces: `POST /api/connections/garmin` (201/202/401/503), `GET /api/connections` → `{"connections": [{"connector": str, "status": str, "external_account": str | None}]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connections_router.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.api import app
from kairos.connectors.garmin.client import AuthTokens, InvalidCredentials, NeedsMfaToken, UpstreamUnavailable
from kairos.routers import connections as connections_module


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        if session_id == "valid":
            return {"user_id": str(uuid4())}
        return None

    import kairos.auth.deps as _deps

    monkeypatch.setattr(_deps, "get_session", _fake_get_session)
    del _sess  # imported only to document which module owns get_session; deps binds its own name


@pytest.mark.asyncio
async def test_garmin_connection_success_returns_201() -> None:
    transport = ASGITransport(app=app)
    with patch.object(
        connections_module.GarminClient, "login",
        return_value=AuthTokens(access_token="", refresh_token='{"fake":"token"}'),
    ):
        with patch.object(connections_module, "_store_connection", new=AsyncMock()):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/connections/garmin",
                    json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                    cookies={"session_id": "valid"},
                )
    assert resp.status_code == 201
    assert resp.json() == {"status": "connected"}


@pytest.mark.asyncio
async def test_garmin_connection_mfa_required_returns_202() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=NeedsMfaToken()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 202
    assert resp.json() == {"status": "mfa_required"}


@pytest.mark.asyncio
async def test_garmin_connection_invalid_credentials_returns_401() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=InvalidCredentials()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "wrong", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid_credentials"}


@pytest.mark.asyncio
async def test_garmin_connection_upstream_unavailable_returns_503() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=UpstreamUnavailable()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "garmin_unavailable"}


@pytest.mark.asyncio
async def test_garmin_connection_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/connections/garmin", json={"email": "a@b.com", "password": "pw", "mfa_token": None}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_connections_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/connections")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_connections_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.routers.connections'`

- [ ] **Step 3: Implement the router**

```python
# src/kairos/routers/connections.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import encrypt, kek_from_settings
from kairos.auth.deps import current_user
from kairos.config import settings
from kairos.connectors.garmin.client import (
    GarminClient,
    GarminConnectBackend,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)
from kairos.db.models import AppUser, Connection
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session

router = APIRouter(prefix="/api/connections", tags=["connections"])


class GarminConnectionRequest(BaseModel):
    email: str
    password: str
    mfa_token: str | None = None


@router.post("/garmin", status_code=201)
async def connect_garmin(
    req: GarminConnectionRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    client = GarminClient(GarminConnectBackend())
    try:
        tokens = client.login(req.email, req.password, mfa_token=req.mfa_token)
    except NeedsMfaToken:
        return _mfa_required_response()
    except InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc
    except UpstreamUnavailable as exc:
        raise HTTPException(status_code=503, detail="garmin_unavailable") from exc

    await _store_connection(session, user_id, req.email, tokens.refresh_token)
    await session.commit()
    return {"status": "connected"}


def _mfa_required_response() -> dict:
    return {"status": "mfa_required"}


async def _store_connection(
    session: AsyncSession, user_id: UUID, email: str, token_json: str
) -> None:
    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one()
    kek = kek_from_settings(settings.kairos_kek)
    from kairos.auth.crypto import unwrap_dek

    dek = unwrap_dek(user_row.dek_wrapped, kek)  # type: ignore[arg-type]
    credentials_enc = encrypt(token_json.encode(), dek)

    stmt = (
        insert(Connection)
        .values(
            user_id=user_id,
            connector="garmin",
            external_account=email,
            status="active",
            credentials_enc=credentials_enc,
        )
        .on_conflict_do_update(
            constraint="uq_connection",
            set_={"status": "active", "credentials_enc": credentials_enc},
        )
    )
    await session.execute(stmt)


@router.get("")
async def list_connections(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    rows = (
        await session.execute(select(Connection).where(Connection.user_id == user_id))
    ).scalars().all()
    return {
        "connections": [
            {"connector": c.connector, "status": c.status, "external_account": c.external_account}
            for c in rows
        ]
    }
```

- [ ] **Step 4: Register the router**

```python
# src/kairos/api.py — add import and include_router call
from kairos.routers.connections import router as connections_router
# ...
app.include_router(connections_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_connections_router.py -v`
Expected: 6/6 PASS

- [ ] **Step 6: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/routers/connections.py src/kairos/api.py tests/test_connections_router.py && .venv/Scripts/python -m mypy --strict src/kairos/routers/connections.py`
Expected: clean

- [ ] **Step 7: Run full backend suite to check for regressions**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all previously-passing tests still pass, plus the 6 new ones

- [ ] **Step 8: Commit**

```bash
git add src/kairos/routers/connections.py src/kairos/api.py tests/test_connections_router.py
git commit -m "feat(backend): POST /api/connections/garmin + GET /api/connections"
```

---

### Task 3: Backend — `/auth/callback` redirects to the frontend

**Files:**
- Modify: `src/kairos/auth/google.py:39-106` (the `callback` handler)
- Test: `tests/test_auth.py` (add one test; read the existing file first to match its exact style/fixtures)

**Interfaces:**
- Consumes: `settings.domain` (already exists in `kairos.config.Settings`, default `"localhost"`).
- Produces: `/auth/callback` now returns a 302 redirect to `/` (frontend root) with the `session_id` cookie set, instead of a bare JSON body.

- [ ] **Step 1: Read the existing test file for the exact fixture/mocking pattern**

Read `tests/test_auth.py` in full before writing the new test — it already mocks `httpx.AsyncClient` responses for the Google token/userinfo exchange; match that pattern exactly rather than inventing a new one.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_auth.py` (exact fixture names depend on what Step 1 finds — use the same mocking helpers the existing `test_callback_*` tests in that file use, just assert on the response differently):

```python
@pytest.mark.asyncio
async def test_callback_redirects_to_frontend_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reuse this file's existing Google-token/userinfo mocking fixture/pattern
    # (see the other test_callback_* tests above for the exact mock setup).
    resp = await _call_callback_with_valid_state_and_code()  # replace with this file's actual helper
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert "session_id" in resp.cookies
```

(If `tests/test_auth.py` uses inline per-test mocking rather than a shared helper, inline the same mock setup the neighboring `test_callback_success`-style test uses instead of calling a helper — match whatever pattern is actually there.)

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_auth.py -k redirects_to_frontend -v`
Expected: FAIL — current code returns `JSONResponse`, not a redirect with `location` header

- [ ] **Step 4: Implement**

In `src/kairos/auth/google.py`, replace the callback's return:

```python
# was:
#     session_id = await create_session(user.id, email)
#     response = JSONResponse({"ok": True, "email": email})
#     response.set_cookie(...)
#     return response
#
# becomes:
    session_id = await create_session(user.id, email)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response
```

Update the function's return type annotation from `JSONResponse` to `RedirectResponse` (already imported at the top of the file — `from fastapi.responses import JSONResponse, RedirectResponse`).

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_auth.py -v`
Expected: all tests in the file pass, including the new one

- [ ] **Step 6: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/auth/google.py tests/test_auth.py && .venv/Scripts/python -m mypy --strict src/kairos/auth/google.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add src/kairos/auth/google.py tests/test_auth.py
git commit -m "fix(backend): /auth/callback redirects to frontend instead of returning JSON"
```

---

### Task 4: Frontend — typed API client, shared types, auth guard

**Files:**
- Create: `web/src/lib/types.ts`, `web/src/lib/api.ts`, `web/src/hooks.server.ts`
- Test: `web/tests/unit/api.test.ts`

**Interfaces:**
- Produces:
  - `type Confidence = "high" | "medium" | "low" | "insufficient_data"`
  - `interface MetricResult { metric_id: string; variant: string; value: number | Record<string, number> | null; unit: string; confidence: Confidence; coverage_days: number; coverage_required_days: number; as_of: string; }`
  - `interface ConnectionInfo { connector: string; status: string; external_account: string | null; }`
  - `interface SyncJob { kind: string; status: string; started_at: string | null; finished_at: string | null; error: string | null; windows_processed: number; }` (mirrors `src/kairos/ingestion/job_registry.py`'s `SyncJob.to_dict()` — read that file to confirm exact field names before writing this type)
  - `async function apiGet<T>(fetchFn: typeof fetch, path: string): Promise<T>` — throws `ApiError` (`class ApiError extends Error { status: number }`) on non-2xx
  - `async function apiPost<T>(fetchFn: typeof fetch, path: string, body: unknown): Promise<{ status: number; data: T }>` — does NOT throw on non-2xx (callers like onboarding need to branch on status code), only throws on network failure

- [ ] **Step 1: Confirm the `SyncJob` field names**

Read `src/kairos/ingestion/job_registry.py`'s `to_dict()` method and copy its exact keys into the TypeScript type in the next step — do not guess.

- [ ] **Step 2: Write the failing test**

```typescript
// web/tests/unit/api.test.ts
import { describe, it, expect, vi } from 'vitest';
import { apiGet, apiPost, ApiError } from '../../src/lib/api';

describe('apiGet', () => {
	it('returns parsed JSON on success', async () => {
		const fetchFn = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ hello: 'world' }), { status: 200 })
		);
		const result = await apiGet<{ hello: string }>(fetchFn, '/api/test');
		expect(result).toEqual({ hello: 'world' });
		expect(fetchFn).toHaveBeenCalledWith('/api/test', { credentials: 'include' });
	});

	it('throws ApiError on non-2xx', async () => {
		const fetchFn = vi.fn().mockResolvedValue(new Response('{}', { status: 404 }));
		await expect(apiGet(fetchFn, '/api/missing')).rejects.toThrow(ApiError);
	});
});

describe('apiPost', () => {
	it('returns status and data without throwing on non-2xx', async () => {
		const fetchFn = vi
			.fn()
			.mockResolvedValue(new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }));
		const result = await apiPost(fetchFn, '/api/x', { a: 1 });
		expect(result.status).toBe(401);
		expect(result.data).toEqual({ detail: 'nope' });
		expect(fetchFn).toHaveBeenCalledWith('/api/x', {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ a: 1 })
		});
	});
});
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `web/`): `npm run test:unit -- api.test.ts`
Expected: FAIL — `../../src/lib/api` does not exist yet

- [ ] **Step 4: Implement the types and API client**

```typescript
// web/src/lib/types.ts
export type Confidence = 'high' | 'medium' | 'low' | 'insufficient_data';

export interface MetricResult {
	metric_id: string;
	variant: string;
	value: number | Record<string, number> | null;
	unit: string;
	confidence: Confidence;
	coverage_days: number;
	coverage_required_days: number;
	as_of: string;
}

export interface ConnectionInfo {
	connector: string;
	status: string;
	external_account: string | null;
}

export interface SyncJob {
	kind: string;
	status: string;
	started_at: string | null;
	finished_at: string | null;
	error: string | null;
	windows_processed: number;
}
```

```typescript
// web/src/lib/api.ts
export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

export async function apiGet<T>(fetchFn: typeof fetch, path: string): Promise<T> {
	const resp = await fetchFn(path, { credentials: 'include' });
	if (!resp.ok) {
		throw new ApiError(resp.status, `GET ${path} failed with ${resp.status}`);
	}
	return (await resp.json()) as T;
}

export async function apiPost<T>(
	fetchFn: typeof fetch,
	path: string,
	body: unknown
): Promise<{ status: number; data: T }> {
	const resp = await fetchFn(path, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	const data = (await resp.json()) as T;
	return { status: resp.status, data };
}
```

- [ ] **Step 5: Write the auth guard**

```typescript
// web/src/hooks.server.ts
import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

const PUBLIC_PATHS = ['/auth/login', '/auth/callback'];

export const handle: Handle = async ({ event, resolve }) => {
	const isPublic = PUBLIC_PATHS.some((p) => event.url.pathname.startsWith(p));
	const hasSession = event.cookies.get('session_id') !== undefined;
	if (!isPublic && !hasSession) {
		throw redirect(302, '/auth/login');
	}
	return resolve(event);
};
```

- [ ] **Step 6: Run test to verify it passes**

Run (from `web/`): `npm run test:unit -- api.test.ts`
Expected: 3/3 PASS

- [ ] **Step 7: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/hooks.server.ts web/tests/unit/api.test.ts
git commit -m "feat(web): typed API client, shared types, session-cookie auth guard"
```

---

### Task 5: Frontend — module registry

**Files:**
- Create: `web/src/lib/modules.ts`
- Test: `web/tests/unit/modules.test.ts`

**Interfaces:**
- Consumes: `MetricResult` from `web/src/lib/types.ts` (Task 4)
- Produces:
  - `type ChartForm = 'value' | 'bar' | 'gauge'`
  - `interface ValueField { key: string; label: string; unit?: string }`
  - `interface GaugeBand { from: number; to: number; color: string; label: string }`
  - `interface GaugeSpec { min: number; max: number; valueKey: string; bands: GaugeBand[] }`
  - `interface ModuleDef { moduleId: string; variant: string; title: string; form: ChartForm; fields?: ValueField[]; trendKey?: string; gauge?: (result: MetricResult) => GaugeSpec; }`
  - `const MODULES: ModuleDef[]` — exactly 8 entries, one per backend `metric_id`
  - `function moduleById(id: string): ModuleDef | undefined`

- [ ] **Step 1: Write the failing test**

```typescript
// web/tests/unit/modules.test.ts
import { describe, it, expect } from 'vitest';
import { MODULES, moduleById } from '../../src/lib/modules';

describe('module registry', () => {
	it('has exactly 8 modules, one per known metric_id', () => {
		const ids = MODULES.map((m) => m.moduleId);
		expect(ids).toEqual([
			'trimp',
			'hr_zone_distribution',
			'training_load',
			'acwr',
			'monotony_strain',
			'hrv_baseline',
			'sleep_debt',
			'resting_hr_trend'
		]);
	});

	it('every module has a unique moduleId', () => {
		const ids = MODULES.map((m) => m.moduleId);
		expect(new Set(ids).size).toBe(ids.length);
	});

	it('moduleById finds a known module and returns undefined for unknown', () => {
		expect(moduleById('trimp')?.title).toBe('Trainingsbelastung (TRIMP)');
		expect(moduleById('nonexistent')).toBeUndefined();
	});

	it('acwr gauge spec maps a mid-range ratio into the sweet_spot band', () => {
		const acwr = moduleById('acwr')!;
		const spec = acwr.gauge!({
			metric_id: 'acwr',
			variant: 'default',
			value: { ratio: 1.0 },
			unit: 'ratio',
			confidence: 'high',
			coverage_days: 28,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		});
		expect(spec.valueKey).toBe('ratio');
		const sweetSpot = spec.bands.find((b) => b.label === 'sweet_spot');
		expect(sweetSpot).toBeDefined();
		expect(1.0).toBeGreaterThanOrEqual(sweetSpot!.from);
		expect(1.0).toBeLessThanOrEqual(sweetSpot!.to);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npm run test:unit -- modules.test.ts`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement**

```typescript
// web/src/lib/modules.ts
import type { MetricResult } from './types';

export type ChartForm = 'value' | 'bar' | 'gauge';

export interface ValueField {
	key: string;
	label: string;
	unit?: string;
}

export interface GaugeBand {
	from: number;
	to: number;
	color: string;
	label: string;
}

export interface GaugeSpec {
	min: number;
	max: number;
	valueKey: string;
	bands: GaugeBand[];
}

export interface ModuleDef {
	moduleId: string;
	variant: string;
	title: string;
	form: ChartForm;
	fields?: ValueField[];
	trendKey?: string;
	gauge?: (result: MetricResult) => GaugeSpec;
}

function acwrGauge(): GaugeSpec {
	return {
		min: 0,
		max: 2,
		valueKey: 'ratio',
		bands: [
			{ from: 0, to: 0.8, color: '#94a3b8', label: 'undertraining' },
			{ from: 0.8, to: 1.3, color: '#22c55e', label: 'sweet_spot' },
			{ from: 1.3, to: 1.5, color: '#f59e0b', label: 'caution' },
			{ from: 1.5, to: 2.0, color: '#ef4444', label: 'high_risk' }
		]
	};
}

function hrvBaselineGauge(result: MetricResult): GaugeSpec {
	const v = result.value as Record<string, number>;
	const low = v.baseline_low;
	const high = v.baseline_high;
	const pad = high - low;
	return {
		min: low - pad,
		max: high + pad,
		valueKey: 'today',
		bands: [
			{ from: low - pad, to: low, color: '#ef4444', label: 'low' },
			{ from: low, to: high, color: '#22c55e', label: 'normal' },
			{ from: high, to: high + pad, color: '#f59e0b', label: 'high' }
		]
	};
}

export const MODULES: ModuleDef[] = [
	{ moduleId: 'trimp', variant: 'edwards', title: 'Trainingsbelastung (TRIMP)', form: 'value' },
	{
		moduleId: 'hr_zone_distribution',
		variant: 'percent_max',
		title: 'HF-Zonenverteilung (heute)',
		form: 'bar'
	},
	{
		moduleId: 'training_load',
		variant: 'default',
		title: 'CTL / ATL / TSB',
		form: 'value',
		fields: [
			{ key: 'ctl', label: 'CTL (Fitness)' },
			{ key: 'atl', label: 'ATL (Ermüdung)' },
			{ key: 'tsb', label: 'TSB (Form)' }
		]
	},
	{ moduleId: 'acwr', variant: 'default', title: 'Belastungsverhältnis (ACWR)', form: 'gauge', gauge: acwrGauge },
	{
		moduleId: 'monotony_strain',
		variant: 'default',
		title: 'Trainingsmonotonie',
		form: 'value',
		fields: [
			{ key: 'monotony', label: 'Monotonie' },
			{ key: 'strain', label: 'Strain' }
		]
	},
	{
		moduleId: 'hrv_baseline',
		variant: 'default',
		title: 'HRV-Baseline',
		form: 'gauge',
		gauge: hrvBaselineGauge
	},
	{ moduleId: 'sleep_debt', variant: 'default', title: 'Schlafschuld', form: 'value', fields: undefined },
	{
		moduleId: 'resting_hr_trend',
		variant: 'default',
		title: 'Ruhepuls-Trend',
		form: 'value',
		fields: [
			{ key: 'recent_avg', label: '7-Tage-Ø', unit: 'bpm' },
			{ key: 'prior_avg', label: 'Vorherige 30 Tage-Ø', unit: 'bpm' }
		],
		trendKey: 'delta_bpm'
	}
];

export function moduleById(id: string): ModuleDef | undefined {
	return MODULES.find((m) => m.moduleId === id);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `web/`): `npm run test:unit -- modules.test.ts`
Expected: 4/4 PASS

- [ ] **Step 5: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/modules.ts web/tests/unit/modules.test.ts
git commit -m "feat(web): static module registry for the 8 dashboard metrics"
```

---

### Task 6: Frontend — EChartsBase, ConfidenceBadge, ValueTile, MetricTile dispatcher

**Files:**
- Create: `web/src/lib/components/EChartsBase.svelte`, `web/src/lib/components/ConfidenceBadge.svelte`, `web/src/lib/components/ValueTile.svelte`, `web/src/lib/components/MetricTile.svelte`
- Test: `web/tests/unit/ConfidenceBadge.test.ts`, `web/tests/unit/ValueTile.test.ts`

**Interfaces:**
- Consumes: `MetricResult`, `Confidence` (Task 4), `ModuleDef`, `moduleById` (Task 5)
- Produces: `<EChartsBase option={EChartsOption} />` (generic, used by Task 7/8), `<ConfidenceBadge confidence={Confidence} />`, `<ValueTile result={MetricResult} module={ModuleDef} />`, `<MetricTile result={MetricResult} module={ModuleDef} />` (dispatches on `module.form`; bar/gauge tiles are stubbed as a `<div>TODO-shaped</div>` placeholder ONLY until Tasks 7/8 land — see note below, this is not a plan placeholder violation because the stub is temporary scaffolding replaced within the same plan, not a permanent gap)

- [ ] **Step 1: Write the failing tests**

```typescript
// web/tests/unit/ConfidenceBadge.test.ts
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ConfidenceBadge from '../../src/lib/components/ConfidenceBadge.svelte';

describe('ConfidenceBadge', () => {
	it('renders nothing visible for high confidence', () => {
		render(ConfidenceBadge, { confidence: 'high' });
		expect(screen.queryByTestId('confidence-badge')).toBeNull();
	});

	it('renders a badge for medium confidence', () => {
		render(ConfidenceBadge, { confidence: 'medium' });
		expect(screen.getByTestId('confidence-badge').textContent).toContain('mittel');
	});

	it('renders a badge for low confidence', () => {
		render(ConfidenceBadge, { confidence: 'low' });
		expect(screen.getByTestId('confidence-badge').textContent).toContain('niedrig');
	});
});
```

```typescript
// web/tests/unit/ValueTile.test.ts
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ValueTile from '../../src/lib/components/ValueTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('ValueTile', () => {
	it('renders a scalar value with its unit', () => {
		const result: MetricResult = {
			metric_id: 'trimp',
			variant: 'edwards',
			value: 42.5,
			unit: 'trimp_pt',
			confidence: 'high',
			coverage_days: 1,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('trimp')! });
		expect(screen.getByText(/42.5/).textContent).toContain('trimp_pt');
	});

	it('renders "Nicht genug Daten" for insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'trimp',
			variant: 'edwards',
			value: null,
			unit: 'trimp_pt',
			confidence: 'insufficient_data',
			coverage_days: 0,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('trimp')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders multi-field dict values with their labels', () => {
		const result: MetricResult = {
			metric_id: 'training_load',
			variant: 'default',
			value: { ctl: 15.2, atl: 9.3, tsb: 5.9 },
			unit: 'ctl_atl_tsb',
			confidence: 'high',
			coverage_days: 81,
			coverage_required_days: 90,
			as_of: '2026-08-11'
		};
		render(ValueTile, { result, module: moduleById('training_load')! });
		expect(screen.getByText(/CTL \(Fitness\)/)).toBeTruthy();
		expect(screen.getByText(/15.2/)).toBeTruthy();
	});
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm run test:unit -- ConfidenceBadge.test.ts ValueTile.test.ts`
Expected: FAIL — components don't exist

- [ ] **Step 3: Implement `EChartsBase.svelte`**

```svelte
<!-- web/src/lib/components/EChartsBase.svelte -->
<script lang="ts">
	import * as echarts from 'echarts';
	import type { EChartsOption } from 'echarts';

	let { option }: { option: EChartsOption } = $props();
	let container: HTMLDivElement;
	let chart: echarts.ECharts | undefined;

	$effect(() => {
		if (!chart) {
			chart = echarts.init(container);
		}
		chart.setOption(option, true);
		return () => {
			// no per-option teardown needed; chart instance is disposed below on unmount
		};
	});

	$effect(() => {
		return () => {
			chart?.dispose();
			chart = undefined;
		};
	});
</script>

<div bind:this={container} style="width: 100%; height: 220px;"></div>
```

- [ ] **Step 4: Implement `ConfidenceBadge.svelte`**

```svelte
<!-- web/src/lib/components/ConfidenceBadge.svelte -->
<script lang="ts">
	import type { Confidence } from '../types';

	let { confidence }: { confidence: Confidence } = $props();

	const LABELS: Record<Confidence, string | null> = {
		high: null,
		medium: 'mittel',
		low: 'niedrig',
		insufficient_data: null
	};

	let label = $derived(LABELS[confidence]);
</script>

{#if label}
	<span data-testid="confidence-badge" class="confidence-badge confidence-{confidence}">
		Konfidenz: {label}
	</span>
{/if}

<style>
	.confidence-badge {
		font-size: 0.75rem;
		padding: 0.1rem 0.4rem;
		border-radius: 0.25rem;
		background: #fef3c7;
		color: #92400e;
	}
</style>
```

- [ ] **Step 5: Implement `ValueTile.svelte`**

```svelte
<!-- web/src/lib/components/ValueTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

<div class="value-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || result.value === null}
		<p class="empty">Nicht genug Daten</p>
	{:else if module.fields}
		{@const dict = result.value as Record<string, number>}
		<dl>
			{#each module.fields as field (field.key)}
				<dt>{field.label}</dt>
				<dd>{dict[field.key].toFixed(2)} {field.unit ?? ''}</dd>
			{/each}
		</dl>
		{#if module.trendKey}
			{@const delta = dict[module.trendKey]}
			<p class="trend">{delta < 0 ? '↓' : delta > 0 ? '↑' : '→'} {delta.toFixed(1)} bpm</p>
		{/if}
	{:else}
		<p class="scalar">{(result.value as number).toFixed(1)} {result.unit}</p>
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	.value-tile {
		border: 1px solid #e2e8f0;
		border-radius: 0.5rem;
		padding: 1rem;
	}
	.empty {
		color: #94a3b8;
	}
</style>
```

- [ ] **Step 6: Implement `MetricTile.svelte`** (bar/gauge branches are temporary scaffolding stubs — Tasks 7/8 replace them with real components in this same plan, not deferred out of it)

```svelte
<!-- web/src/lib/components/MetricTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ValueTile from './ValueTile.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

{#if module.form === 'value'}
	<ValueTile {result} {module} />
{:else if module.form === 'bar'}
	<div class="pending-form">{module.title} (Balkendiagramm folgt in Task 7)</div>
{:else if module.form === 'gauge'}
	<div class="pending-form">{module.title} (Gauge folgt in Task 8)</div>
{/if}
```

- [ ] **Step 7: Run tests to verify they pass**

Run (from `web/`): `npm run test:unit -- ConfidenceBadge.test.ts ValueTile.test.ts`
Expected: 6/6 PASS

- [ ] **Step 8: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/components/
git commit -m "feat(web): EChartsBase wrapper, ConfidenceBadge, ValueTile, MetricTile dispatcher"
```

---

### Task 7: Frontend — BarTile (HR-Zonenverteilung)

**Files:**
- Create: `web/src/lib/components/BarTile.svelte`
- Modify: `web/src/lib/components/MetricTile.svelte:9-11` (replace the `bar` stub with `<BarTile>`)
- Test: `web/tests/unit/BarTile.test.ts`

**Interfaces:**
- Consumes: `EChartsBase` (Task 6), `MetricResult` where `value` is `Record<string, number>` with keys `zone_1`..`zone_5` (seconds each, per `hr_zone_distribution_variant.py`'s `_zone_seconds` output)
- Produces: `<BarTile result={MetricResult} module={ModuleDef} />`

- [ ] **Step 1: Write the failing test**

```typescript
// web/tests/unit/BarTile.test.ts
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import BarTile from '../../src/lib/components/BarTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('BarTile', () => {
	it('renders the module title and an empty-state message when insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'hr_zone_distribution',
			variant: 'percent_max',
			value: null,
			unit: 'seconds',
			confidence: 'insufficient_data',
			coverage_days: 0,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		render(BarTile, { result, module: moduleById('hr_zone_distribution')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders a chart container when zone data is present', () => {
		const result: MetricResult = {
			metric_id: 'hr_zone_distribution',
			variant: 'percent_max',
			value: { zone_1: 600, zone_2: 300, zone_3: 0, zone_4: 0, zone_5: 0 },
			unit: 'seconds',
			confidence: 'high',
			coverage_days: 1,
			coverage_required_days: 1,
			as_of: '2026-08-11'
		};
		const { container } = render(BarTile, { result, module: moduleById('hr_zone_distribution')! });
		expect(container.querySelector('div[style*="height"]')).toBeTruthy();
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npm run test:unit -- BarTile.test.ts`
Expected: FAIL — component does not exist

- [ ] **Step 3: Implement**

```svelte
<!-- web/src/lib/components/BarTile.svelte -->
<script lang="ts">
	import type { EChartsOption } from 'echarts';
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import EChartsBase from './EChartsBase.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();

	let option = $derived.by((): EChartsOption | null => {
		if (result.value === null) return null;
		const dict = result.value as Record<string, number>;
		const zones = Object.keys(dict).sort();
		return {
			xAxis: { type: 'category', data: zones },
			yAxis: { type: 'value', name: 'Sekunden' },
			series: [{ type: 'bar', data: zones.map((z) => Math.round(dict[z])) }],
			tooltip: { trigger: 'axis' }
		};
	});
</script>

<div class="bar-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || option === null}
		<p class="empty">Nicht genug Daten</p>
	{:else}
		<EChartsBase option={option} />
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	.bar-tile {
		border: 1px solid #e2e8f0;
		border-radius: 0.5rem;
		padding: 1rem;
	}
	.empty {
		color: #94a3b8;
	}
</style>
```

- [ ] **Step 4: Wire it into `MetricTile`**

```svelte
<!-- web/src/lib/components/MetricTile.svelte — replace the bar branch -->
{:else if module.form === 'bar'}
	<BarTile {result} {module} />
```

Add the import at the top: `import BarTile from './BarTile.svelte';`

- [ ] **Step 5: Run test to verify it passes**

Run (from `web/`): `npm run test:unit -- BarTile.test.ts`
Expected: 2/2 PASS

- [ ] **Step 6: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/components/BarTile.svelte web/src/lib/components/MetricTile.svelte web/tests/unit/BarTile.test.ts
git commit -m "feat(web): BarTile for HR-zone distribution"
```

---

### Task 8: Frontend — GaugeTile (ACWR, HRV-Baseline)

**Files:**
- Create: `web/src/lib/components/GaugeTile.svelte`
- Modify: `web/src/lib/components/MetricTile.svelte` (replace the `gauge` stub with `<GaugeTile>`)
- Test: `web/tests/unit/GaugeTile.test.ts`

**Interfaces:**
- Consumes: `EChartsBase` (Task 6), `GaugeSpec`/`module.gauge()` (Task 5)
- Produces: `<GaugeTile result={MetricResult} module={ModuleDef} />`

- [ ] **Step 1: Write the failing test**

```typescript
// web/tests/unit/GaugeTile.test.ts
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import GaugeTile from '../../src/lib/components/GaugeTile.svelte';
import { moduleById } from '../../src/lib/modules';
import type { MetricResult } from '../../src/lib/types';

describe('GaugeTile', () => {
	it('renders the empty state for insufficient_data', () => {
		const result: MetricResult = {
			metric_id: 'acwr',
			variant: 'default',
			value: null,
			unit: 'ratio',
			confidence: 'insufficient_data',
			coverage_days: 2,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		};
		render(GaugeTile, { result, module: moduleById('acwr')! });
		expect(screen.getByText('Nicht genug Daten')).toBeTruthy();
	});

	it('renders a chart container when a ratio is present', () => {
		const result: MetricResult = {
			metric_id: 'acwr',
			variant: 'default',
			value: { ratio: 1.1 },
			unit: 'ratio',
			confidence: 'high',
			coverage_days: 28,
			coverage_required_days: 7,
			as_of: '2026-08-11'
		};
		const { container } = render(GaugeTile, { result, module: moduleById('acwr')! });
		expect(container.querySelector('div[style*="height"]')).toBeTruthy();
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npm run test:unit -- GaugeTile.test.ts`
Expected: FAIL — component does not exist

- [ ] **Step 3: Implement**

```svelte
<!-- web/src/lib/components/GaugeTile.svelte -->
<script lang="ts">
	import type { EChartsOption } from 'echarts';
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import EChartsBase from './EChartsBase.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();

	let option = $derived.by((): EChartsOption | null => {
		if (result.value === null || !module.gauge) return null;
		const spec = module.gauge(result);
		const dict = result.value as Record<string, number>;
		const value = dict[spec.valueKey];
		return {
			series: [
				{
					type: 'gauge',
					min: spec.min,
					max: spec.max,
					axisLine: {
						lineStyle: {
							width: 12,
							color: spec.bands.map((b) => [
								(b.to - spec.min) / (spec.max - spec.min),
								b.color
							])
						}
					},
					pointer: { show: true },
					detail: { formatter: `{value}`, fontSize: 20 },
					data: [{ value: Math.round(value * 100) / 100 }]
				}
			]
		};
	});
</script>

<div class="gauge-tile">
	<h3>{module.title}</h3>
	{#if result.confidence === 'insufficient_data' || option === null}
		<p class="empty">Nicht genug Daten</p>
	{:else}
		<EChartsBase option={option} />
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	.gauge-tile {
		border: 1px solid #e2e8f0;
		border-radius: 0.5rem;
		padding: 1rem;
	}
	.empty {
		color: #94a3b8;
	}
</style>
```

- [ ] **Step 4: Wire it into `MetricTile`**

```svelte
<!-- web/src/lib/components/MetricTile.svelte — replace the gauge branch -->
{:else if module.form === 'gauge'}
	<GaugeTile {result} {module} />
```

Add the import at the top: `import GaugeTile from './GaugeTile.svelte';`

- [ ] **Step 5: Run test to verify it passes**

Run (from `web/`): `npm run test:unit -- GaugeTile.test.ts`
Expected: 2/2 PASS

- [ ] **Step 6: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/components/GaugeTile.svelte web/src/lib/components/MetricTile.svelte web/tests/unit/GaugeTile.test.ts
git commit -m "feat(web): GaugeTile for ACWR and HRV-baseline"
```

---

### Task 9: Frontend — Dashboard page

**Files:**
- Create: `web/src/routes/+page.svelte`, `web/src/routes/+page.server.ts`

**Interfaces:**
- Consumes: `apiGet` (Task 4), `MODULES` (Task 5), `MetricTile` (Task 6/7/8)
- Produces: `GET /` renders one `<MetricTile>` per module, fetched server-side

- [ ] **Step 1: Implement the load function**

```typescript
// web/src/routes/+page.server.ts
import type { PageServerLoad } from './$types';
import { apiGet } from '$lib/api';
import { MODULES } from '$lib/modules';
import type { MetricResult } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const results = await Promise.all(
		MODULES.map(async (m) => {
			try {
				const result = await apiGet<MetricResult>(
					fetch,
					`/api/metrics/${m.moduleId}?variant=${m.variant}`
				);
				return { module: m, result, error: null as string | null };
			} catch {
				return { module: m, result: null as MetricResult | null, error: 'Daten gerade nicht verfügbar' };
			}
		})
	);
	return { tiles: results };
};
```

- [ ] **Step 2: Implement the page**

```svelte
<!-- web/src/routes/+page.svelte -->
<script lang="ts">
	import MetricTile from '$lib/components/MetricTile.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<h1>Dashboard</h1>
<div class="tile-grid">
	{#each data.tiles as tile (tile.module.moduleId)}
		{#if tile.result}
			<MetricTile result={tile.result} module={tile.module} />
		{:else}
			<div class="tile-error">
				<h3>{tile.module.title}</h3>
				<p>{tile.error}</p>
			</div>
		{/if}
	{/each}
</div>

<style>
	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 1rem;
	}
	.tile-error {
		border: 1px solid #fecaca;
		border-radius: 0.5rem;
		padding: 1rem;
		color: #b91c1c;
	}
</style>
```

- [ ] **Step 3: Manual verification**

Start the backend (`docker compose up -d` for Postgres/Redis, `.venv/Scripts/uvicorn kairos.api:app --reload` from repo root) and the frontend dev server (`npm run dev` from `web/`). With a valid `session_id` cookie set manually (e.g. via the browser devtools after a real Google login) or by temporarily stubbing `hooks.server.ts`, load `http://localhost:5173/` and confirm 8 tiles render (most will show "Nicht genug Daten" or an error without real Garmin data — that's expected and correct, not a bug, since no backfill has run in a fresh dev DB).

- [ ] **Step 4: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/+page.svelte web/src/routes/+page.server.ts
git commit -m "feat(web): dashboard page rendering all 8 metric tiles"
```

---

### Task 10: Frontend — Onboarding page (Garmin login + MFA retry)

**Files:**
- Create: `web/src/routes/onboarding/+page.svelte`, `web/src/routes/onboarding/+page.server.ts`

**Interfaces:**
- Consumes: `apiPost` (Task 4)
- Produces: `GET /onboarding` (form), `POST /onboarding` (SvelteKit form action calling the backend)

- [ ] **Step 1: Implement the form action**

```typescript
// web/src/routes/onboarding/+page.server.ts
import type { Actions } from './$types';
import { apiPost } from '$lib/api';

export const actions: Actions = {
	default: async ({ request, fetch }) => {
		const form = await request.formData();
		const email = form.get('email') as string;
		const password = form.get('password') as string;
		const mfaToken = (form.get('mfa_token') as string) || null;

		const { status, data } = await apiPost<{ status?: string; detail?: string }>(
			fetch,
			'/api/connections/garmin',
			{ email, password, mfa_token: mfaToken }
		);

		if (status === 201) {
			return { success: true, email };
		}
		if (status === 202) {
			return { mfaRequired: true, email, password };
		}
		if (status === 401) {
			return { error: 'E-Mail oder Passwort falsch.' };
		}
		if (status === 503) {
			return { error: 'Garmin ist gerade nicht erreichbar. Bitte später erneut versuchen.' };
		}
		return { error: `Unerwarteter Fehler (${status}): ${data.detail ?? 'unbekannt'}` };
	}
};
```

- [ ] **Step 2: Implement the page**

```svelte
<!-- web/src/routes/onboarding/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<h1>Garmin-Verbindung einrichten</h1>

{#if form?.success}
	<p class="success">Verbunden mit {form.email}. <a href="/sync">Zum Sync-Status</a></p>
{:else}
	<form method="POST" use:enhance>
		<label>
			E-Mail
			<input type="email" name="email" value={form?.email ?? ''} required />
		</label>
		<label>
			Passwort
			<input type="password" name="password" value={form?.password ?? ''} required />
		</label>
		{#if form?.mfaRequired}
			<label>
				MFA-Code (aus E-Mail/App)
				<input type="text" name="mfa_token" required autofocus />
			</label>
			<input type="hidden" name="email" value={form.email} />
			<input type="hidden" name="password" value={form.password} />
		{/if}
		{#if form?.error}
			<p class="error">{form.error}</p>
		{/if}
		<button type="submit">Verbinden</button>
	</form>
{/if}

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 320px;
	}
	.error {
		color: #b91c1c;
	}
	.success {
		color: #15803d;
	}
</style>
```

- [ ] **Step 3: Manual verification**

With the backend running and a valid session cookie, load `http://localhost:5173/onboarding`, submit invalid credentials and confirm the 401 error message renders; if a real (test) Garmin account with MFA is available, confirm the MFA field appears on the 202 path and a subsequent submit with the code succeeds. If no test Garmin account is available, verify the three response branches (401/503/202) render correctly by temporarily editing `+page.server.ts` to hardcode each status for a manual check, then revert.

- [ ] **Step 4: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/onboarding/
git commit -m "feat(web): onboarding page with Garmin login and MFA retry"
```

---

### Task 11: Frontend — Sync-status page

**Files:**
- Create: `web/src/routes/sync/+page.svelte`, `web/src/routes/sync/+page.server.ts`

**Interfaces:**
- Consumes: `apiGet` (Task 4), `ConnectionInfo`/`SyncJob` (Task 4)
- Produces: `GET /sync` — shows connection status + sync job list

- [ ] **Step 1: Implement the load function**

```typescript
// web/src/routes/sync/+page.server.ts
import type { PageServerLoad } from './$types';
import { apiGet } from '$lib/api';
import type { ConnectionInfo, SyncJob } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const [connections, syncStatus] = await Promise.all([
		apiGet<{ connections: ConnectionInfo[] }>(fetch, '/api/connections'),
		apiGet<{ jobs: SyncJob[] }>(fetch, '/api/sync/status')
	]);
	return { connections: connections.connections, jobs: syncStatus.jobs };
};
```

- [ ] **Step 2: Implement the page**

```svelte
<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
</script>

<h1>Sync-Status</h1>

{#if !garminConnection}
	<p>Keine Garmin-Verbindung. <a href="/onboarding">Jetzt einrichten</a></p>
{:else}
	<p>Garmin: {garminConnection.status} ({garminConnection.external_account})</p>

	<table>
		<thead>
			<tr>
				<th>Kind</th>
				<th>Status</th>
				<th>Verarbeitete Fenster</th>
				<th>Fehler</th>
			</tr>
		</thead>
		<tbody>
			{#each data.jobs as job (job.kind)}
				<tr>
					<td>{job.kind}</td>
					<td>{job.status}</td>
					<td>{job.windows_processed}</td>
					<td>{job.error ?? '–'}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}
```

- [ ] **Step 3: Manual verification**

With the backend running, load `http://localhost:5173/sync` and confirm it shows "Keine Garmin-Verbindung" before onboarding, and the job table after a backfill has been triggered via `POST /api/sync/garmin/backfill`.

- [ ] **Step 4: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/sync/
git commit -m "feat(web): sync-status page"
```

---

### Task 12: Frontend — root layout, navigation, end-to-end auth wiring

**Files:**
- Create: `web/src/routes/+layout.svelte`, `web/src/routes/+layout.server.ts`

**Interfaces:**
- Consumes: nothing new — wires together Tasks 4/9/10/11 into a navigable app
- Produces: a nav bar (Dashboard / Sync-Status / Onboarding) present on every page; `/auth/login` link when unauthenticated is unreachable in-app since `hooks.server.ts` already redirects, but the nav still needs a visible "logged in as X" + logout affordance

- [ ] **Step 1: Implement the layout load function**

```typescript
// web/src/routes/+layout.server.ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies }) => {
	// hooks.server.ts already guarantees a session cookie exists on every
	// non-public route reachable here; we don't decode it (opaque to the
	// frontend, backend owns session state) — just confirm presence for the nav.
	return { authenticated: cookies.get('session_id') !== undefined };
};
```

- [ ] **Step 2: Implement the layout**

```svelte
<!-- web/src/routes/+layout.svelte -->
<script lang="ts">
	import type { LayoutData } from './$types';

	let { data, children }: { data: LayoutData; children: () => unknown } = $props();
</script>

<nav>
	<a href="/">Dashboard</a>
	<a href="/sync">Sync-Status</a>
	<a href="/onboarding">Garmin verbinden</a>
	{#if data.authenticated}
		<form method="POST" action="/auth/logout" style="display: inline;">
			<button type="submit">Abmelden</button>
		</form>
	{/if}
</nav>

<main>
	{@render children()}
</main>

<style>
	nav {
		display: flex;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 1px solid #e2e8f0;
	}
	main {
		padding: 1rem;
	}
</style>
```

- [ ] **Step 3: Manual end-to-end verification**

With backend + frontend dev servers running (per Task 9 Step 3), navigate `http://localhost:5173/` while logged OUT (no `session_id` cookie) — confirm redirect to `/auth/login`, which redirects to Google, which (after a real login) redirects back to `/auth/callback`, which (per Task 3) redirects to `/` with the session cookie set. Confirm the dashboard now loads and the nav shows all three links plus "Abmelden".

- [ ] **Step 4: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/+layout.svelte web/src/routes/+layout.server.ts
git commit -m "feat(web): root layout with navigation, end-to-end auth flow verified"
```

---

### Task 13: Frontend — PWA setup

**Files:**
- Modify: `web/vite.config.ts` (add the `@vite-pwa/sveltekit` plugin)
- Create: `web/static/icons/icon-192.png`, `web/static/icons/icon-512.png` (placeholder icons — see step 1)

**Interfaces:**
- Produces: an installable PWA (manifest + app-shell service worker), no offline data sync (per the design spec, §2.6)

- [ ] **Step 1: Generate placeholder icons**

The project has no designed app icon yet. Generate two flat placeholder PNGs (solid background + a single letter "K", any reasonable tool available — e.g. a small Node script using the `sharp` package if already available, or an online-free equivalent run locally; if no image-generation tooling is available in this environment, create simple 192×192 and 512×512 solid-color PNGs via Python's stdlib-adjacent `Pillow` if installed, or note in the commit message that these are temporary placeholders to be replaced with real branding before production launch). Save as `web/static/icons/icon-192.png` and `web/static/icons/icon-512.png`.

- [ ] **Step 2: Configure the PWA plugin**

```typescript
// web/vite.config.ts — add to the plugins array alongside sveltekit()
import { SvelteKitPWA } from '@vite-pwa/sveltekit';

export default defineConfig({
	plugins: [
		sveltekit(),
		SvelteKitPWA({
			registerType: 'autoUpdate',
			manifest: {
				name: 'Kairos',
				short_name: 'Kairos',
				description: 'Persönlicher Gesundheits- und Trainingsassistent',
				theme_color: '#0f172a',
				background_color: '#ffffff',
				display: 'standalone',
				icons: [
					{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
					{ src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' }
				]
			},
			workbox: {
				// app-shell caching only — dashboard data always requires a live
				// backend connection, per the design spec's explicit no-offline-sync decision
				globPatterns: ['**/*.{js,css,html,svg,png,ico}']
			}
		})
	],
	server: {
		proxy: {
			'/api': { target: 'http://localhost:8000', changeOrigin: true },
			'/auth': { target: 'http://localhost:8000', changeOrigin: true }
		}
	}
});
```

- [ ] **Step 3: Build and verify the manifest is generated**

Run (from `web/`): `npm run build`
Expected: build succeeds; `web/.svelte-kit/output/client/manifest.webmanifest` (or equivalent output path the plugin reports in its build log) exists and contains `"name": "Kairos"`.

- [ ] **Step 4: Commit**

```bash
git add web/vite.config.ts web/static/icons/
git commit -m "feat(web): PWA manifest and app-shell service worker (no offline data sync)"
```

---

### Task 14: Frontend — Playwright E2E test for onboarding

**Files:**
- Create: `web/tests/e2e/onboarding.spec.ts`

**Interfaces:**
- Consumes: Playwright's route interception to mock `POST /api/connections/garmin` — no real backend or Garmin account needed for this test

- [ ] **Step 1: Write the test**

```typescript
// web/tests/e2e/onboarding.spec.ts
import { test, expect } from '@playwright/test';

test.describe('onboarding', () => {
	test.beforeEach(async ({ context }) => {
		// hooks.server.ts requires a session cookie to reach any non-public route
		await context.addCookies([
			{ name: 'session_id', value: 'e2e-fake-session', domain: 'localhost', path: '/' }
		]);
	});

	test('shows an error on invalid credentials', async ({ page }) => {
		await page.route('**/api/connections/garmin', async (route) => {
			await route.fulfill({ status: 401, json: { detail: 'invalid_credentials' } });
		});
		await page.goto('/onboarding');
		await page.fill('input[name=email]', 'wrong@example.com');
		await page.fill('input[name=password]', 'wrongpass');
		await page.click('button[type=submit]');
		await expect(page.getByText('E-Mail oder Passwort falsch.')).toBeVisible();
	});

	test('shows the MFA field on a 202 response, then succeeds', async ({ page }) => {
		let callCount = 0;
		await page.route('**/api/connections/garmin', async (route) => {
			callCount += 1;
			if (callCount === 1) {
				await route.fulfill({ status: 202, json: { status: 'mfa_required' } });
			} else {
				await route.fulfill({ status: 201, json: { status: 'connected' } });
			}
		});
		await page.goto('/onboarding');
		await page.fill('input[name=email]', 'user@example.com');
		await page.fill('input[name=password]', 'correctpass');
		await page.click('button[type=submit]');
		await expect(page.locator('input[name=mfa_token]')).toBeVisible();
		await page.fill('input[name=mfa_token]', '123456');
		await page.click('button[type=submit]');
		await expect(page.getByText(/Verbunden mit/)).toBeVisible();
	});
});
```

- [ ] **Step 2: Run the test**

Run (from `web/`): `npm run test:e2e -- onboarding.spec.ts`
Expected: 2/2 PASS (Playwright's config, scaffolded in Task 1, starts the dev server automatically via `webServer` in `playwright.config.ts` — if it doesn't, add a `webServer: { command: 'npm run dev', port: 5173 }` block to that file first)

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/onboarding.spec.ts web/playwright.config.ts
git commit -m "test(web): e2e coverage for the onboarding MFA-retry flow"
```

---

## Self-Review

**Spec coverage:** §1 (onboarding/sync/dashboard scope) → Tasks 9–11. §2.1 (adapter-node) → Task 1. §2.2 (auth) → Tasks 3–4, 12. §2.3 (connections endpoint) → Task 2. §2.4 (module registry) → Task 5 (with the line→gauge/value correction documented in Global Constraints). §2.5 (chart components) → Tasks 6–8. §2.6 (PWA) → Task 13. §2.7 (tests) → unit tests threaded through every component task, E2E in Task 14. §3 (data flow) → Task 9's load function + §4 error handling reflected in every tile's `insufficient_data`/error branch. §7 (deferred items) — none of them have a task here, correctly excluded.

**Placeholder scan:** The only intentional stub is `MetricTile.svelte`'s bar/gauge branches in Task 6, explicitly called out as scaffolding replaced within Tasks 7–8 of this same plan, not a deferred gap — acceptable per the plan's own task-ordering, not a "TBD".

**Type consistency:** `ModuleDef`, `MetricResult`, `GaugeSpec`, `ChartForm` are defined once (Tasks 4–5) and consumed identically by name in every later task — checked field-by-field across Tasks 6–9 for drift, none found.

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-11-dashboard-frontend.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
