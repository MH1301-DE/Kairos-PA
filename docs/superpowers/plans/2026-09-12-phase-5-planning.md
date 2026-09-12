# Phase 5 — Planung (Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Neither skill was available when this plan was
> written (see docs/HANDOVER.md) -- work the tasks in order directly if that's still the case.

**Goal:** Reference questions 13 ("Trainingsplan für die nächsten 3 Wochen") and 15 ("was habe
ich schon trainiert, was fehlt laut Plan") answerable end-to-end through `/chat`, with real
calendar events written on confirmation. Design spec:
`docs/superpowers/specs/2026-09-12-phase-5-planning-design.md` -- read it first.

**Architecture:** A pure, deterministic planning function (`generate_plan_blocks`, mirrors the
existing `metrics/formulas/` pattern) turns free-calendar-blocks + current CTL into a sequence
of `plan_block` rows. Four new tools (`plan_propose`, `plan_commit`, `plan_adjust`,
`plan_progress`) extend the existing static `CORE_TOOLS` tuple from the Phase-4 MVP plan --
the dispatcher and orchestrator are already generic over any `ToolSpec`, so no changes to
either are needed, only new entries. `plan_commit` writes real calendar events through the
existing `_create_calendar_event`, no new write path.

**Tech Stack:** FastAPI, SQLAlchemy async, same stack as every prior phase -- no new
dependencies.

## Global Constraints

- `install_rls_listener(session, user_id)` on every session touching `plan`/`plan_block`.
- `ruff` (line-length 100) + `mypy --strict`, conventional commits.
- `plan_commit`/`plan_adjust` are `write`-class with `requires_confirmation=True` -- verified
  by a dispatcher-level test (handler never called without confirmation), same pattern as the
  Phase-4 MVP's `test_agent_dispatcher.py`.
- No new calendar-write path -- every event `plan_commit` creates goes through
  `_create_calendar_event` in `routers/calendar.py`, unchanged from Phase 4.
- Backend interpreter: `.venv/Scripts/python`.

---

## File Structure

```
alembic/versions/<rev>_plan_tables.py              new: plan + plan_block tables
src/kairos/db/models.py                              + Plan, PlanBlock

src/kairos/planning/__init__.py                       new (empty)
src/kairos/planning/algorithm.py                       new: generate_plan_blocks() (pure)
src/kairos/repositories/plan.py                        new: PlanRepository

src/kairos/agent/tools.py                              + 4 tool handlers, + 4 CORE_TOOLS entries

tests/test_planning_algorithm.py                       new
tests/test_plan_repository_integration.py               new
tests/test_agent_tools_planning.py                      new
tests/test_plan_commit_integration.py                   new
```

---

### Task 1: `plan` / `plan_block` tables

**Files:**
- Create: `alembic/versions/<rev>_plan_tables.py`
- Modify: `src/kairos/db/models.py`

**Interfaces:**
- Produces: `Plan` (id, user_id, title, start_date, end_date, goal_date nullable, status
  default `'draft'`, created_at, updated_at) and `PlanBlock` (id, plan_id FK, user_id FK
  redundant-for-RLS same reasoning as `conversation_message.user_id`, day, workout_type,
  target_trimp nullable float, calendar_event_id FK `calendar_event.id` nullable, status
  default `'planned'`) per the design spec's exact schema.

- [ ] **Step 1: Migration + ORM models** -- standard RLS tenant-table pattern for both tables,
  `CheckConstraint`s for `status`/`workout_type` per the spec.

- [ ] **Step 2: `alembic upgrade head`, `alembic check`, lint, commit**
  ```bash
  git commit -m "feat(planning): plan and plan_block tables"
  ```

---

### Task 2: Planning algorithm (pure function)

**Files:**
- Create: `src/kairos/planning/__init__.py` (empty), `src/kairos/planning/algorithm.py`
- Test: `tests/test_planning_algorithm.py`

**Interfaces:**
- `@dataclass(frozen=True) class PlannedBlock: day: date; workout_type: Literal["long_run",
  "hard", "easy", "rest"]; target_trimp: float | None`
- `def generate_plan_blocks(*, start: date, end: date, goal_date: date | None,
  free_blocks_by_day: dict[date, list[FreeBlock]], current_ctl: float) -> list[PlannedBlock]`
  -- one entry per day in `[start, end]`. Rules (see design spec Scope-Entscheidung 2 for the
  full reasoning): exactly one `long_run` per calendar week, placed on the day with the single
  longest free block that week; `hard` sessions only on days with a free block >= 60 min, with
  >= 48h between any two `hard` days; every remaining day with a usable free block becomes
  `easy`; every day with no usable free block (or left over after the above) becomes `rest`,
  and at least one `rest` day per week is enforced even if every day technically has a free
  block (force the day with the smallest free block to `rest` if the week would otherwise have
  none). Weekly total `target_trimp` (sum across `long_run`/`hard`/`easy` blocks that week)
  targets `current_ctl * 7 * 1.1^(week_index)`, distributed: `long_run` gets 35% of the
  week's total, each `hard` day gets 25%, remaining split evenly across `easy` days. If
  `goal_date` falls within `[start, end]`, the final 7 days before it get a flat 50% load
  multiplier (taper) applied after the above.

- [ ] **Step 1: Write failing tests** -- cover: a 3-week window with generous free blocks
  produces exactly 3 `long_run` blocks (one per week) and respects the 48h hard-session
  spacing; a window with zero free blocks on any day produces an all-`rest` plan (no crash, no
  division by zero); a `goal_date` inside the window produces a lower weekly total in its
  taper week than the week before it; every week has at least one `rest` block even when every
  day has a free block.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(planning): deterministic rule-based training plan generator"
  ```

---

### Task 3: `PlanRepository`

**Files:**
- Create: `src/kairos/repositories/plan.py`
- Test: `tests/test_plan_repository_integration.py`

**Interfaces:**
- `create_draft(*, user_id, title, start_date, end_date, goal_date, blocks: list[PlannedBlock])
  -> Plan` -- inserts the `Plan` row (`status='draft'`) and one `PlanBlock` row per
  `PlannedBlock`.
- `get(*, user_id, plan_id) -> Plan | None`
- `get_active_for_user(*, user_id) -> Plan | None` -- most recent `status='committed'` plan.
- `list_blocks(*, user_id, plan_id) -> list[PlanBlock]`, ordered by `day`.
- `commit(*, user_id, plan_id, event_ids_by_block_id: dict[UUID, str]) -> None` -- sets
  `plan.status='committed'`, sets `plan_block.calendar_event_id` for each block.
- `replace_remaining_blocks(*, user_id, plan_id, from_day: date, blocks: list[PlannedBlock]) ->
  None` -- deletes `plan_block` rows for this plan with `day >= from_day AND status='planned'`,
  inserts the replacements. Blocks already `status='done'`/`'skipped'` are never touched.

- [ ] **Step 1: Failing integration tests** (real testcontainer DB, mirror
  `test_conversation_repository_integration.py`'s style) -- `create_draft` then `list_blocks`
  round-trips; `commit` sets both the plan and every block's `calendar_event_id`;
  `replace_remaining_blocks` leaves past/done blocks untouched and replaces only future planned
  ones; RLS isolation (two-user pattern).

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(planning): PlanRepository"
  ```

---

### Task 4: Four planning tool handlers

**Files:**
- Modify: `src/kairos/agent/tools.py`
- Test: `tests/test_agent_tools_planning.py`, additions to `tests/test_agent_dispatcher.py`
- Integration test: `tests/test_plan_commit_integration.py`

**Interfaces:**
- `plan_propose_handler(session, *, user_id, weeks: int, goal_date: str | None = None) ->
  dict[str, Any]` -- computes `free_blocks_by_day` via the existing `CalendarEventRepository`
  + `compute_free_blocks` (same helpers `query_calendar_handler` already uses, factor the
  "build free_blocks_by_day for a date range" logic into a small shared helper in `tools.py`
  rather than duplicating the loop) and current CTL via `registry.get("training_load",
  "default").compute(...)` (multi-stat dict, read `.value["ctl"]`, default to `0.0` if
  `insufficient_data` -- a brand-new user still gets a plan, just a conservative one), calls
  `generate_plan_blocks`, persists via `PlanRepository.create_draft`. `read`-class, no
  confirmation (mirrors `remember`'s reasoning: a draft has no side effect outside the
  database).
- `plan_commit_handler(session, *, user_id, plan_id: str) -> dict[str, Any]` -- `write`,
  `requires_confirmation=True`. For every non-`rest` block without a `calendar_event_id`,
  builds a `CreateEventRequest` (summary from `workout_type` + `target_trimp`, e.g. "Long Run
  (TRIMP ~140)"), calls `_create_calendar_event`, collects the resulting event ids, calls
  `PlanRepository.commit`.
- `plan_adjust_handler(session, *, user_id, plan_id: str, reason: str) -> dict[str, Any]` --
  `write`, `requires_confirmation=True`. Multiplier: `0.7` if `reason` (lowercased) contains
  any of `"stress"`, `"krank"`, `"müde"`, `"erkält"`; else `0.85`. Applies the multiplier to
  every future `'planned'` block's `target_trimp`, re-generates their `calendar_event`
  summaries via `_create_calendar_event`'s update path if already committed (skip silently for
  blocks with no `calendar_event_id` yet -- an adjust before a commit just changes the draft).
- `plan_progress_handler(session, *, user_id, plan_id: str | None = None) -> dict[str, Any]`
  -- `read`. Resolves the active plan if `plan_id` is omitted. For the current ISO week,
  compares planned vs. actual: sums `target_trimp` for this week's `plan_block` rows, sums
  real TRIMP for the same days via `edwards_daily_load_series`, reports both totals plus a
  per-day planned-vs-done breakdown.

- [ ] **Step 1: Failing handler tests** (isolated, real DB via the `session` fixture, mirror
  `test_agent_tools.py`'s style) -- one per handler, plus dispatcher-level tests confirming
  `plan_commit`/`plan_adjust` never call their handler without `pending_confirmation=True`
  (same assertion style as the existing `test_agent_dispatcher.py`).

- [ ] **Step 2: Integration test** -- `plan_propose` then `plan_commit` (mocked
  `_build_google_calendar_client`, same pattern as `test_agent_tools.py`'s calendar tests)
  against a real DB: every non-`rest` `plan_block` ends up with a `calendar_event_id`, the
  matching `calendar_event` row has `source='kairos'`.

- [ ] **Step 3: Implement the 4 handlers + append 4 `ToolSpec` entries to `CORE_TOOLS`** (and
  `TOOLS_BY_NAME` picks them up automatically, it's derived from `CORE_TOOLS`).

- [ ] **Step 4: Tests, lint, commit**
  ```bash
  git commit -m "feat(planning): plan_propose/commit/adjust/progress tools"
  ```

---

## Acceptance (whole-plan)

`scripts/agent_eval_suite.py`'s cases 13 and 15 (currently excluded from `CASES`, see that
script) can be added back once this plan lands, run once `LLM_API_KEY` is configured, to
verify end-to-end. All new tests pass; existing test count doesn't regress. `ruff`/
`mypy --strict` clean across the diff.

## Bewusst nicht Teil dieses Plans

Insight-Job + Web Push (see design spec's "Bewusst nicht Teil dieser Spec") -- a genuinely
separate subsystem, own future plan. No `/plans` frontend page -- chat is the only interface
for now, per the design spec.
