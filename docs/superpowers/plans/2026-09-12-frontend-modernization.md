# Frontend-Modernisierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Neither skill was available when this plan was
> written (see docs/HANDOVER.md) -- work the tasks in order directly if that's still the case.

**Goal:** Dashboard tiles are reorderable/hideable per user, every page is usable on an iPhone
(375-430px width, notch/Dynamic Island safe areas respected), and the small consistency gaps
found in the design audit are closed. Design spec:
`docs/superpowers/specs/2026-09-12-frontend-modernization-design.md` — read it first.

**Tech Stack:** SvelteKit 5 runes, `svelte-dnd-action` (new dependency), existing `app.css`
token system (no framework swap), Vitest, pytest for the new backend endpoint.

## Global Constraints

- `install_rls_listener(session, user_id)` on every session touching `user_dashboard_tile`.
- `ruff` (line-length 100) + `mypy --strict`, conventional commits.
- Svelte 5 runes syntax, existing `app.css` tokens only -- no new colors/fonts.
- Two consistent breakpoints project-wide: `640px` (phone/tablet boundary) and `768px` (wider
  sidebar layouts) -- no page-specific magic numbers.
- Backend interpreter: `.venv/Scripts/python`. Frontend: run `npm` from inside `web/`; prefix
  with `export PATH="/c/Program Files/nodejs:$PATH" && ` if node isn't on PATH.
- No real browser click-through possible in this environment (Google OAuth needed, browser
  tool blocks cookie injection) -- verify via `npm run check`/`eslint`/Vitest/curl against a
  real (non-mocked) dev server where auth allows, same as prior sessions in this project.

---

## File Structure

```
alembic/versions/<rev>_user_dashboard_tile.py    new: user_dashboard_tile table
src/kairos/db/models.py                            + UserDashboardTile

src/kairos/routers/dashboard.py                    new: GET/PUT /api/dashboard/layout
src/kairos/api.py                                  + dashboard_router

web/package.json                                    + svelte-dnd-action
web/src/app.html                                    viewport-fit, apple-* meta tags
web/src/app.css                                     input font-size, .btn[disabled], responsive
                                                      main padding, skeleton loading class
web/src/lib/types.ts                                + DashboardTileLayout
web/src/lib/dashboardLayout.ts                       new: pure sort/filter function
web/src/routes/+layout.svelte                       hamburger/drawer nav below 640px
web/src/routes/+page.server.ts                       + layout fetch
web/src/routes/+page.svelte                          Anpassen-mode, dndzone, show/hide
web/src/routes/chat/+page.svelte                     collapsible sidebar drawer below 768px
web/src/routes/calendar/+page.svelte                 compact grid below 640px

tests/test_dashboard_router.py                       new
web/tests/unit/dashboardLayout.test.ts                new
```

---

### Task 1: Global mobile + PWA fixes

**Files:**
- Modify: `web/src/app.html`, `web/src/app.css`, `web/src/routes/+layout.svelte`

**Interfaces:**
- No new backend surface. Purely CSS/markup.

- [ ] **Step 1: `app.html` meta tags**

  Add inside `<head>`, after the existing `theme-color` line:
  ```html
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <link rel="apple-touch-icon" href="/icons/icon-192.png" />
  ```
  (Replace the existing plain `viewport` meta line with the `viewport-fit=cover` version above
  rather than duplicating it. `icons/icon-192.png` already exists under `web/static/icons/`,
  reused from the existing PWA manifest -- confirm the path resolves before committing.)

- [ ] **Step 2: `app.css` global fixes**

  - `.field input` font-size: change `font-size: var(--text-base)` to a fixed `16px` (not a
    token -- this is an iOS Safari zoom-threshold workaround, not a design choice, so it
    should not track a token that might later change under 16px again).
  - Add a `.btn:disabled` rule (covers every `.btn-*` variant): `opacity: 0.5; cursor:
    not-allowed;` placed after the existing `.btn:active` rule.
  - Add a responsive `main` padding rule:
    ```css
    @media (max-width: 640px) {
        main {
            padding: var(--space-4);
        }
    }
    ```
  - Add a skeleton-loading utility class:
    ```css
    .skeleton {
        background: linear-gradient(
            90deg, var(--color-surface-raised) 25%, var(--color-border) 50%,
            var(--color-surface-raised) 75%
        );
        background-size: 200% 100%;
        animation: skeleton-shimmer 1.5s ease-in-out infinite;
        border-radius: var(--radius-sm);
    }
    @keyframes skeleton-shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }
    ```
    (Respect the existing `prefers-reduced-motion` block at the bottom of the file -- it
    already disables all transitions globally with `* { transition: none !important; }`; add
    `animation: none !important;` to that same rule so `.skeleton` degrades to a static block
    instead of shimmering for users who asked for reduced motion.)

- [ ] **Step 3: Nav hamburger/drawer below 640px**

  In `+layout.svelte`: add a `mobileMenuOpen = $state(false)` alongside the existing
  `menuOpen`. Wrap `.nav-links` in a `<div class="nav-links-wrap">` that's `display: none`
  below 640px; add a hamburger `<button>` (visible only below 640px, `display: none` above)
  that toggles `mobileMenuOpen`. When open, render a full-height drawer (`position: fixed;
  inset: 0;` panel, same `.menu-panel` visual language but full-screen) containing both the
  nav links AND the existing "Konto & Sync" section content (Verbindungen, Datenabgleich,
  Abmelden) -- one drawer covers everything on mobile instead of two separate triggers.
  Close on `Escape` (extend the existing `handleKeydown`) and on any nav-link click (mirrors
  desktop's implicit close-on-navigate).

- [ ] **Step 4: `npm run check`, `eslint`, manual reasoning check**

  Run both from `web/`. No Vitest changes needed (pure CSS/markup). Since a real browser
  click-through isn't possible here, do a careful re-read of the drawer markup for obvious
  mistakes (unclosed conditionals, `aria-expanded` on the right element) instead of trusting
  a visual check that can't happen.

- [ ] **Step 5: Commit**
  ```bash
  git commit -m "fix(web): mobile nav drawer, iOS zoom fix, safe-area meta, disabled/skeleton styles"
  ```

---

### Task 2: `user_dashboard_tile` table + layout API

**Files:**
- Create: `alembic/versions/<rev>_user_dashboard_tile.py`, `src/kairos/routers/dashboard.py`
- Modify: `src/kairos/db/models.py`, `src/kairos/api.py`
- Test: `tests/test_dashboard_router.py`

**Interfaces:**
- Produces: `UserDashboardTile` ORM model, composite PK `(user_id, module_id)`, `position:
  int`, `visible: bool` (default `True`). `_DEFAULT_MODULE_ORDER` constant in `dashboard.py`
  mirroring `web/src/lib/modules.ts`'s `MODULES` order exactly (module ids: `trimp`,
  `hr_zone_distribution`, `training_load`, `acwr`, `monotony_strain`, `hrv_baseline`,
  `sleep_debt`, `resting_hr_trend` -- copy this list from `modules.ts`, don't retype it from
  memory, confirm it matches before committing).
  - `GET /api/dashboard/layout` -- if the user has no stored rows, returns
    `_DEFAULT_MODULE_ORDER` as `[{module_id, position, visible: true}, ...]` (0-indexed
    position). Otherwise returns the stored rows ordered by `position`.
  - `PUT /api/dashboard/layout` -- body `{tiles: [{module_id, position, visible}]}`. 422 if any
    `module_id` isn't in `_DEFAULT_MODULE_ORDER`. Delete-then-insert the user's rows in one
    transaction.

- [ ] **Step 1: Migration + ORM model** -- standard RLS tenant-table pattern, mirror
  `MetricDailyValue`'s composite-PK style (no separate `id` column).

- [ ] **Step 2: Router** -- mirror `routers/memory.py`'s structure. `_DEFAULT_MODULE_ORDER`
  as a module-level tuple of strings.

- [ ] **Step 3: Tests** -- `GET` with no stored rows returns the 8-module default in the
  right order; `PUT` then `GET` round-trips a custom order/visibility; `PUT` with an unknown
  `module_id` returns 422 and writes nothing; RLS isolation test (two-user pattern from
  `test_memory_router.py`).

- [ ] **Step 4: Lint, commit**
  ```bash
  git commit -m "feat(dashboard): per-user tile order/visibility (GET/PUT /api/dashboard/layout)"
  ```

---

### Task 3: Dashboard personalization frontend

**Files:**
- Modify: `web/package.json`, `web/src/lib/types.ts`, `web/src/routes/+page.server.ts`,
  `web/src/routes/+page.svelte`
- Create: `web/src/lib/dashboardLayout.ts`
- Test: `web/tests/unit/dashboardLayout.test.ts`

**Interfaces:**
- `npm install svelte-dnd-action` in `web/`.
- `DashboardTileLayout` type in `types.ts`: `{ module_id: string; position: number; visible:
  boolean }`.
- `applyLayout(modules: ModuleDef[], layout: DashboardTileLayout[]): ModuleDef[]` in
  `dashboardLayout.ts` -- pure function, sorts `modules` by the matching layout entry's
  `position`, filters out `visible: false` entries. A `modules` entry with no matching layout
  row (e.g. a module added after the user's last save) sorts to the end, stays visible --
  never silently drops a real module because the layout is stale.

- [ ] **Step 1: `npm install svelte-dnd-action`** in `web/`.

- [ ] **Step 2: `dashboardLayout.ts`** + its Vitest test -- cover: normal sort, a hidden
  module filtered out, a module missing from the layout still appears (at the end).

- [ ] **Step 3: `+page.server.ts`** -- `load()` also fetches `GET /api/dashboard/layout`,
  passes it through. New form action `saveLayout` -- body is the serialized tile array (hidden
  form field, JSON-stringified from the client before submit), `PUT`s it to the backend.

- [ ] **Step 4: `+page.svelte`** -- apply `applyLayout(MODULES, data.layout)` before rendering
  the grid (both in normal mode and, un-filtered, in edit mode -- edit mode needs to show
  hidden tiles too, dimmed, so they can be re-enabled). "Anpassen" button toggles
  `editMode = $state(false)`. In edit mode: wrap the grid in `use:dndzone={{items: tiles}}`
  (svelte-dnd-action's action, `items` bound to a local `$state` array reordered by its
  `consider`/`finalize` events -- follow the library's documented Svelte-5-runes pattern, not
  the older Svelte-4 store-based examples some of its docs still show elsewhere), each tile
  gets a visible drag handle (only rendered in edit mode) and a visibility checkbox. "Speichern"
  submits the `saveLayout` action with the current order + checkbox states, then exits edit
  mode. Give the drag handle `touch-action: none` in CSS so touch dragging doesn't also scroll
  the page.

- [ ] **Step 5: `npm run check`, `eslint`, `npm run test:unit`, commit**
  ```bash
  git commit -m "feat(web): drag-and-drop dashboard tile reordering and show/hide"
  ```

---

### Task 4: `/chat` mobile-responsive sidebar

**Files:**
- Modify: `web/src/routes/chat/+page.svelte`

**Interfaces:** No new backend/type surface -- pure layout change.

- [ ] **Step 1:** Below `768px`, `.chat-layout`'s `grid-template-columns: 16rem 1fr` collapses
  to a single column; `.conversation-list` becomes a slide-in drawer (`position: fixed`, same
  full-screen-panel pattern as Task 1's nav drawer) toggled by a small icon-button placed at
  the top of `.chat-main` (only rendered below 768px). Reuse the same open/close state pattern
  (a local `$state(false)`, closed by `Escape` and by selecting a conversation).

- [ ] **Step 2: `npm run check`, `eslint`, careful re-read (same no-browser caveat as Task 1)**

- [ ] **Step 3: Commit**
  ```bash
  git commit -m "fix(web): /chat conversation list becomes a drawer below 768px"
  ```

---

### Task 5: `/calendar` compact mobile grid

**Files:**
- Modify: `web/src/routes/calendar/+page.svelte`

**Interfaces:** No new backend/type surface -- pure layout change.

- [ ] **Step 1:** Below `640px`: reduce `.day-cell` `min-height` and padding, reduce
  `.day-number`/`.day-event-chip` font sizes, reduce `.calendar-toolbar`'s gap so the month
  nav + "Kalender synchronisieren" button don't wrap awkwardly. Keep the 7-column structure
  (design spec's Scope-Entscheidung: matches Apple/Google Calendar's own mobile month view,
  not a list-view rewrite).

- [ ] **Step 2: `npm run check`, `eslint`, careful re-read**

- [ ] **Step 3: Commit**
  ```bash
  git commit -m "fix(web): denser /calendar month grid below 640px"
  ```

---

## Acceptance (whole-plan)

`user_dashboard_tile` round-trips order/visibility correctly (Task 2's tests). Every existing
backend/frontend test still passes. `npm run check`/`eslint` clean across the whole diff. No
real click-through verification was possible (documented limitation, same as every prior
frontend task in this project this session) -- flag to the user that a manual pass on a real
iPhone (or Chrome's device toolbar) is the actual verification step once they can log in.
