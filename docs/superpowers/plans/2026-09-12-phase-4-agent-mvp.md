# Phase 4 — Agent (MVP-Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. If neither skill is available in the executing
> session, work the tasks in order directly instead — the dependency ordering and Files/
> Interfaces contracts below still apply, just without the automated task-brief/review-package
> pipeline.

**Goal:** A user can chat with Kairos at `/chat` and get correct, tool-grounded answers to 13 of
the 15 reference questions (`docs/00-vision-und-scope.md` §5; 13 and 15 are Phase 5 — see the
design spec). Write/destructive tool calls (except `remember`) require an explicit confirmation
before they execute; `remember` writes immediately but always shows a visible, dismissible
"Kairos hat sich gemerkt: … · Rückgängig" chip. Median input < 15,000 tokens/turn.

**Design spec:** `docs/superpowers/specs/2026-09-12-phase-4-agent-mvp-design.md` — read it first,
this plan does not repeat its reasoning, only the concrete build steps.

**Architecture:** A single async tool-calling loop (`src/kairos/agent/orchestrator.py`) drives
`litellm.completion()` against a static, 8-entry tool list (`src/kairos/agent/tools.py`) — no
`tool_registry` table, no embeddings, nothing to search (Scope-Entscheidung 1 in the spec).
Two tool handlers (`propose_calendar_event`, `delete_calendar_event`) call the *existing* Phase-3
calendar endpoints under the hood, so their confirmation gating is already server-enforced and
not reimplemented here. A deterministic Situation Brief is built from existing repositories, no
LLM call. Conversations persist as flat message rows (`conversation`/`conversation_message`),
no rolling-compaction summary in this phase. Two small, agent-independent groundwork pieces
(daily series for derived metrics, a safe custom-metric formula evaluator) are built first
because `query_health`/`analyze_records` depend on them.

**Tech Stack:** FastAPI, SQLAlchemy async, `litellm` (new dependency), `simpleeval` (new
dependency, safe expression evaluation), SvelteKit 5 runes, Vitest, pytest + testcontainers.

## Global Constraints

- `install_rls_listener(session, user_id)` on every session that reads or writes
  `conversation`, `conversation_message`, `metric_daily_value`, `custom_metric_definition`, or
  any existing tenant table — non-negotiable per `CLAUDE.md`.
- Backend: `ruff` (line-length 100) + `mypy --strict` clean, conventional commit messages.
- Frontend: Svelte 5 runes syntax, `credentials: 'include'` via the existing `apiGet`/`apiPost`/
  `apiPatch`/`apiDelete` helpers (`web/src/lib/api.ts`), existing `app.css` design tokens only.
- No LLM API call outside `src/kairos/agent/orchestrator.py` — risk-class enforcement lives in
  one place (the dispatcher the orchestrator calls into), never bypassable from a router.
- Every `write`/`destructive` tool handler (except `remember`, see design spec Scope-Entscheidung
  4) returns a `Proposal`, never executes directly. The two calendar tools delegate to the
  existing `POST`/`DELETE /api/calendar/events` endpoints — do not duplicate their logic.
- Tool results follow the output contract from `docs/03-agent-design.md` §4.5: `{summary, data,
  meta}`, hard-capped at 2,000 tokens, `meta.truncated` set when cut.
- No streaming in this phase (design spec Scope-Entscheidung 1) — `POST .../messages` returns
  the complete assistant turn.
- Backend interpreter: `.venv/Scripts/python`. Frontend: run `npm` from inside `web/`; prefix
  with `export PATH="/c/Program Files/nodejs:$PATH" && ` if node isn't on PATH.
- `custom_metric_definition.expression` is evaluated only through `simpleeval` with a whitelist
  of existing metric codes as the only available names — never `eval()`/`exec()` on it, anywhere.

---

## File Structure

```
alembic/versions/<rev>_metric_daily_value.py                    new: metric_daily_value table
alembic/versions/<rev>_custom_metric_definition.py               new: custom_metric_definition table
alembic/versions/<rev>_conversation_tables.py                    new: conversation + conversation_message
alembic/versions/<rev>_llm_model_setting.py                      new: user_setting.llm_model column
src/kairos/db/models.py                                           + MetricDailyValue, CustomMetricDefinition,
                                                                     Conversation, ConversationMessage,
                                                                     + UserSetting.llm_model

src/kairos/repositories/metrics_recompute.py                     + recompute_metric_daily_values()
src/kairos/routers/metrics.py                                    POST /recompute also calls the above

src/kairos/metrics/custom_eval.py                                new: safe expression evaluator
src/kairos/repositories/custom_metrics.py                        new: CustomMetricRepository
src/kairos/routers/custom_metrics.py                              new: GET/POST/DELETE /api/metrics/custom

src/kairos/agent/__init__.py                                     new (empty)
src/kairos/agent/llm_client.py                                   new: litellm wrapper, per-user model+key
src/kairos/agent/situation_brief.py                               new: build_situation_brief()
src/kairos/agent/tools.py                                         new: ToolSpec + CORE_TOOLS + 8 handlers
src/kairos/agent/dispatcher.py                                    new: risk-class enforcement, Proposal
src/kairos/agent/orchestrator.py                                  new: the tool-calling loop
src/kairos/repositories/conversation.py                           new: ConversationRepository
src/kairos/routers/agent.py                                       new: /api/agent/conversations/*
src/kairos/api.py                                                  + custom_metrics_router, + agent_router

web/src/lib/types.ts                                               + ChatMessage, Conversation, Proposal
web/src/routes/chat/
  +page.server.ts                new: load() fetches conversations; actions for send/confirm/new
  +page.svelte                    new: message list, input, proposal card, memory chip
web/src/routes/+layout.svelte                                     + "Chat" nav link (after "Gedächtnis")

tests/test_metrics_recompute_daily_values.py                      new
tests/test_custom_metric_eval.py                                  new
tests/test_custom_metrics_router.py                                new
tests/test_conversation_repository_integration.py                  new
tests/test_agent_tools.py                                          new (each handler, isolated)
tests/test_agent_dispatcher.py                                     new (risk-class enforcement)
tests/test_agent_orchestrator.py                                   new (mocked litellm.completion)
tests/test_agent_router.py                                         new
scripts/agent_eval_suite.py                                        new: manual-trigger, real LLM calls
web/tests/unit/chat-types.test.ts                                  new (or folded into the page test)
```

---

### Task 1: `metric_daily_value` — daily series for derived formula metrics

**Files:**
- Create: `alembic/versions/<rev>_metric_daily_value.py`
- Modify: `src/kairos/db/models.py`, `src/kairos/repositories/metrics_recompute.py`,
  `src/kairos/routers/metrics.py`
- Test: `tests/test_metrics_recompute_daily_values.py`

**Interfaces:**
- Produces: `MetricDailyValue` ORM model — PK `(user_id, metric_id, variant_id, day)`, columns
  `value: float | None`, `confidence: str`. `async def recompute_metric_daily_values(session,
  *, user_id: UUID, start: date, end: date) -> None` in `metrics_recompute.py` — for every
  `(metric_id, variant_id)` in `build_default_registry()` (`src/kairos/metrics/bootstrap.py`,
  already exists) and every day in `[start, end]`, calls `registry.get(metric_id,
  variant_id).compute(session, user_id=user_id, as_of=day)` and upserts the result. Delete-then-
  insert per call, same pattern as `recompute_wellness_daily_stats` in the same file.

- [ ] **Step 1: Migration + ORM model**

  Find the current head (`.venv/Scripts/python -m alembic heads` — should be `9f3d6a1b2c48`
  after the memory-table migration merged this session). Table:
  ```
  user_id       UUID FK app_user, part of PK
  metric_id     TEXT NOT NULL, part of PK
  variant_id    TEXT NOT NULL, part of PK
  day           DATE NOT NULL, part of PK
  value         DOUBLE PRECISION
  confidence    TEXT NOT NULL
  FORCE ROW LEVEL SECURITY (same tenant_isolation policy as every other table)
  ```
  Mirror `HrBucketSecondsDaily`'s composite-PK ORM style in `models.py` exactly (all-PK columns,
  no separate `id`). Add the ORM class near `WellnessDailyStats`.

- [ ] **Step 2: `recompute_metric_daily_values`**

  ```python
  async def recompute_metric_daily_values(
      session: AsyncSession, *, user_id: UUID, start: date, end: date
  ) -> None:
      await session.execute(
          text(
              "DELETE FROM metric_daily_value "
              "WHERE user_id = :uid AND day >= :start AND day <= :end"
          ),
          {"uid": str(user_id), "start": start, "end": end},
      )
      registry = build_default_registry()
      day = start
      while day <= end:
          for metric_id in registry.metric_ids():
              for variant_id in registry.variants_for(metric_id):
                  result = await registry.get(metric_id, variant_id).compute(
                      session, user_id=user_id, as_of=day
                  )
                  await session.execute(
                      text(
                          "INSERT INTO metric_daily_value "
                          "(user_id, metric_id, variant_id, day, value, confidence) "
                          "VALUES (:uid, :mid, :vid, :day, :value, :confidence)"
                      ),
                      {
                          "uid": str(user_id), "mid": metric_id, "vid": variant_id, "day": day,
                          "value": result.value if isinstance(result.value, int | float) else None,
                          "confidence": result.confidence,
                      },
                  )
          day += timedelta(days=1)
  ```
  Add the `build_default_registry` import from `kairos.metrics.bootstrap` — check first that
  this doesn't create a circular import with `routers/metrics.py` (it shouldn't; bootstrap has
  no router dependency). `MetricResult.value` can be a `dict` for multi-stat metrics (e.g.
  training_load's CTL/ATL/TSB) — those are skipped (stored as `NULL`) in this table; only
  scalar formula outputs get a daily series. Note this limitation in a one-line comment, don't
  silently work around it — multi-stat daily series is a real follow-up, not in this task's scope.

- [ ] **Step 3: Wire into the existing recompute trigger**

  In `routers/metrics.py`'s `recompute_metrics`, add the new call alongside the two existing
  ones, same `start`/`end` window.

- [ ] **Step 4: Tests**

  Integration test (real testcontainer DB, mirror `tests/test_metrics_recompute_integration.py`'s
  fixture style): seed enough wellness/activity data for at least one variant to return a
  non-`insufficient_data` result on a known day, call `recompute_metric_daily_values`, assert a
  row exists with the expected `metric_id`/`variant_id`/`day` and a `value` that matches a direct
  `.compute()` call for the same day (regression-proofs against drift between the two paths).

- [ ] **Step 5: Verify, lint, commit**

  `.venv/Scripts/python -m pytest tests/test_metrics_recompute_daily_values.py -v`, then
  `ruff check` + `mypy --strict` on the touched files.
  ```bash
  git commit -m "feat(metrics): daily series for derived formula metrics (metric_daily_value)"
  ```

---

### Task 2: Custom metrics — safe formula evaluator + CRUD

**Files:**
- Create: `alembic/versions/<rev>_custom_metric_definition.py`
- Create: `src/kairos/metrics/custom_eval.py`, `src/kairos/repositories/custom_metrics.py`,
  `src/kairos/routers/custom_metrics.py`
- Modify: `src/kairos/db/models.py`, `src/kairos/api.py`, `pyproject.toml` (add `simpleeval`)
- Test: `tests/test_custom_metric_eval.py`, `tests/test_custom_metrics_router.py`

**Interfaces:**
- Produces: `CustomMetricDefinition` ORM model (see design spec's schema — `id`, `user_id`,
  `code`, `display_name`, `expression`, `created_by`, `created_at`; `UNIQUE(user_id, code)`, RLS).
  `def evaluate_expression(expression: str, values: dict[str, float]) -> float` in
  `custom_eval.py` — raises `InvalidExpression` for anything outside arithmetic + name lookups
  (simpleeval's default `EvalWithCompoundTypes` is too permissive; use plain `simpleeval.SimpleEval`
  with `functions={}` and `names=values` — no function calls at all, arithmetic and comparisons
  only). `def extract_metric_refs(expression: str) -> set[str]` — parses the expression once
  (via `ast.parse` + walking `ast.Name` nodes, simpleeval exposes no ref-extraction itself) to
  validate every referenced name is a real metric code *before* storing the definition, so a typo
  fails at creation time, not at every later evaluation.
  `CustomMetricRepository`: `create`/`list_for_user`/`delete`, same shape as `SqlMemoryRepository`.
  Router: `GET/POST/DELETE /api/metrics/custom` — `POST` validates via `extract_metric_refs`
  against `metric_def.code` ∪ formula `metric_id`s from `build_default_registry()` before insert,
  422 on an unknown reference.

- [ ] **Step 1: Add `simpleeval` dependency**

  `pyproject.toml` dependencies list, then `.venv/Scripts/python -m pip install simpleeval` and
  re-run `pip install -e ".[dev]"` if the editable install needs a refresh.

- [ ] **Step 2: Migration + ORM model** — schema exactly as in the design spec.

- [ ] **Step 3: `custom_eval.py`**

  ```python
  from __future__ import annotations
  import ast
  from simpleeval import SimpleEval, InvalidExpression as _SimpleEvalInvalid

  class InvalidExpression(Exception):
      pass

  def extract_metric_refs(expression: str) -> set[str]:
      try:
          tree = ast.parse(expression, mode="eval")
      except SyntaxError as exc:
          raise InvalidExpression(str(exc)) from exc
      return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

  def evaluate_expression(expression: str, values: dict[str, float]) -> float:
      evaluator = SimpleEval(names=values)
      evaluator.functions = {}  # no function calls whatsoever, arithmetic only
      try:
          result = evaluator.eval(expression)
      except _SimpleEvalInvalid as exc:
          raise InvalidExpression(str(exc)) from exc
      if not isinstance(result, int | float):
          raise InvalidExpression("expression did not evaluate to a number")
      return float(result)
  ```
  Test both the happy path (`"hrv_5min * 0.5 + stress * 0.2"`) and rejection of anything with a
  function call (`"__import__('os')"`), attribute access, or a name not in `values` — simpleeval
  raises `NameNotDefined` (subclass of its `InvalidExpression`) for the last case, which the
  `except` above already catches.

- [ ] **Step 4: Repository + router**

  Mirror `src/kairos/repositories/memory.py`/`src/kairos/routers/memory.py` structurally.
  `POST` handler: call `extract_metric_refs(req.expression)`, check every ref is in
  `{m.code for m in <metric_def rows>} | set(build_default_registry().metric_ids())`, 422 with
  the offending name(s) if not, else insert with `created_by="user"` (same spoof-proofing
  pattern as `agent_memory.source` — a future agent tool creates with `created_by="agent"` via
  the repository directly, never through this endpoint).

- [ ] **Step 5: Tests, lint, commit**

  `.venv/Scripts/python -m pytest tests/test_custom_metric_eval.py tests/test_custom_metrics_router.py -v`
  ```bash
  git commit -m "feat(metrics): custom metric definitions via a safe expression evaluator"
  ```

---

### Task 3: `conversation` / `conversation_message` tables

**Files:**
- Create: `alembic/versions/<rev>_conversation_tables.py`, `src/kairos/repositories/conversation.py`
- Modify: `src/kairos/db/models.py`
- Test: `tests/test_conversation_repository_integration.py`

**Interfaces:**
- Produces: `Conversation`, `ConversationMessage` ORM models per the design spec's schema.
  `ConversationRepository`: `create(user_id, title) -> Conversation`,
  `list_for_user(user_id) -> list[Conversation]`,
  `append_message(conversation_id, user_id, role, content, tool_calls=None) -> ConversationMessage`,
  `list_messages(conversation_id, user_id, limit=50) -> list[ConversationMessage]` (most recent
  `limit`, ascending order for feeding back into the LLM — this is the "simple context-window
  cutoff" from the design spec, no compaction).

- [ ] **Step 1: Migration + ORM models** — both tables, both RLS, `conversation_message` has its
  own `user_id` column (not just via join) specifically so its own RLS policy doesn't need a
  subquery — same reasoning the design spec gives.

- [ ] **Step 2: Repository** — straightforward CRUD, mirror `SqlGoalRepository`'s style. One
  gotcha: `append_message` must also bump `conversation.updated_at` (for the conversation-list
  sort order in the frontend) — a plain `UPDATE conversation SET updated_at = now() WHERE id =
  :id` alongside the insert, same transaction.

- [ ] **Step 3: Tests** — integration test: create conversation, append 3 messages, list back in
  order, RLS isolation test (same two-user pattern as `test_memory_router.py`'s RLS test).

- [ ] **Step 4: Lint, commit**
  ```bash
  git commit -m "feat(agent): conversation and conversation_message tables"
  ```

---

### Task 4: LLM provider wiring (litellm + per-user credential)

**Files:**
- Create: `alembic/versions/<rev>_llm_model_setting.py`, `src/kairos/agent/__init__.py`,
  `src/kairos/agent/llm_client.py`
- Modify: `src/kairos/db/models.py` (`UserSetting.llm_model`), `pyproject.toml`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces: `UserSetting.llm_model: str` (default `"anthropic/claude-sonnet-5"`, per the spec's
  resolved default-model question). `async def get_completion(session, *, user_id, messages,
  tools) -> litellm.ModelResponse` in `llm_client.py` — loads the user's `llm_model` from
  `user_setting` and their API key from a `connection` row with `connector='llm_provider'`
  (decrypted via the existing `kek_from_settings`/`unwrap_dek`/`decrypt` chain, exact pattern as
  `_build_garmin_client` in `routers/sync.py`), then calls
  `litellm.completion(model=llm_model, messages=messages, tools=tools, api_key=decrypted_key,
  stream=False)` via `asyncio.to_thread` (litellm's sync API, same blocking-call-off-the-event-
  loop pattern as the Garmin client).
- **No connections-router UI in this task** — storing an LLM API key still needs a way for the
  user to enter one. Reuse the existing `/account` page pattern: a follow-up, separate small task
  (not blocking this one) adds a form there. For this task and the ones after it, tests supply a
  fake `connection` row directly; document this gap explicitly in the task's PR/commit rather
  than silently deferring it.

- [ ] **Step 1: Add `litellm` dependency** to `pyproject.toml`, install.

- [ ] **Step 2: Migration** — single nullable-with-default column on `user_setting`.

- [ ] **Step 3: `llm_client.py`** — mirror `_build_garmin_client`'s connection-lookup/decrypt
  structure exactly (same `first()` not `scalar_one_or_none()` reasoning, same `try/except
  Exception: return None`-style graceful degradation, but here raise a clear
  `NoLlmCredentialConfigured` exception instead of returning `None` silently — the orchestrator
  needs to tell the user "no API key configured yet" rather than fail mysteriously).

- [ ] **Step 4: Tests** — mock `litellm.completion` (module-level patch, never a real API call in
  tests), assert the right `model`/`api_key`/`messages`/`tools` get passed through, and that
  `NoLlmCredentialConfigured` is raised when no `connection` row exists.

- [ ] **Step 5: Lint, commit**
  ```bash
  git commit -m "feat(agent): litellm wrapper with per-user model and encrypted API key"
  ```

---

### Task 5: Situation Brief builder

**Files:**
- Create: `src/kairos/agent/situation_brief.py`
- Test: `tests/test_situation_brief.py`

**Interfaces:**
- Produces: `async def build_situation_brief(session, *, user_id: UUID, now: datetime) -> str` —
  plain-text block matching the format in `docs/03-agent-design.md` §3 (Datenstand, Erholung,
  Belastung, Kalender, Aktive Ziele, Hinweise). Read-only, deterministic, no LLM call. Sources:
  `build_default_registry()` for HRV/TSB/ACWR/etc. (reuse `metrics.py`'s pattern directly —
  `registry.get(metric_id, default_variant).compute(...)`), `CalendarEventRepository.list_between`
  for today + tomorrow, `SqlGoalRepository.list_for_user` filtered to `status='active'`.
  **No adaptivity in this phase** (design spec Scope-Entscheidung 1) — always the full form.

- [ ] **Step 1: Write the failing test** — feed a session with known seeded data, assert the
  returned string contains the expected HRV/CTL/ATL/TSB numbers formatted as in the example
  block, and that a user with `insufficient_data` on a metric gets a graceful line (not a crash
  or a raw `None`).

- [ ] **Step 2: Implement** — straightforward string-building function; the only real design
  decision is which `variant` to pick per metric when several are registered (default to
  `variants_for(metric_id)[0]`, i.e. alphabetically first, same default `metrics.py`'s
  `get_metric` uses when no `variant` query param is given — consistency, not a new rule).

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(agent): deterministic Situation Brief builder"
  ```

---

### Task 6: Core tool handlers (`src/kairos/agent/tools.py`)

**Files:**
- Create: `src/kairos/agent/tools.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Produces: `ToolSpec` dataclass (see design spec) and `CORE_TOOLS: tuple[ToolSpec, ...]` with
  all 8 entries. Each handler signature: `async def handler(session, *, user_id: UUID,
  **kwargs) -> dict[str, Any]` returning the `{summary, data, meta}` envelope (§4.5). Concretely:
  - `query_health(metric_id, variant=None, as_of=None)` — thin wrapper over the existing
    `registry.get(...).compute(...)` path, same as `routers/metrics.py`'s `get_metric`.
  - `analyze_records(record_type, metric, window_days, stats)` — queries `metric_daily_value`
    (Task 1) or `wellness_daily_stats`/`hr_bucket_seconds_daily` depending on `record_type`,
    computes the requested `stats` (`mean`/`min`/`max`/`trend_slope`) server-side, returns
    numbers only — never a raw per-day list beyond what fits the 2,000-token cap (`meta.truncated`
    + a bounded sample if the window is large).
  - `query_calendar(from_date, to_date)` — wraps `CalendarEventRepository.list_between` +
    `compute_free_blocks` (both already exist, Phase 3).
  - `recall(query=None, limit=10)` — MVP version per the design spec: no embedding search, just
    `SqlMemoryRepository.list_for_user` with an optional naive substring filter on `content` if
    `query` is given, capped at `limit`.
  - `remember(content)` — `SqlMemoryRepository.create(user_id, content, source="agent")` — the
    one `write`-class tool that executes immediately, no Proposal (design spec Scope-Entscheidung
    4). Returns the created entry so the orchestrator/frontend can render the undo chip.
  - `render(component, config)` — validates `component` against the fixed set already used by
    the dashboard (`Gauge`/`TimeSeriesChart`/`BarChart`/`StatCard`/`Table`), returns a spec
    object, no data fetching of its own (data comes from a prior `query_health`/`analyze_records`
    call in the same turn, per `docs/05-erweiterbarkeit.md` §2.3's config shape).
  - `propose_calendar_event(summary, start_at, end_at, description=None)` — `write`, `requires_
    confirmation=True`. On confirmation, calls the existing `POST /api/calendar/events` logic
    directly (import and call the router's handler function, or factor its body into a plain
    function both the router and this tool call — prefer factoring, avoids two code paths).
  - `delete_calendar_event(event_id, confirm=False)` — `destructive`, `requires_confirmation=
    True`. Calls the existing `DELETE /api/calendar/events/{id}` logic the same way — its
    `confirm=True` gate (this session's work) still applies underneath, the tool-level
    confirmation and the endpoint-level confirmation are two independent layers on purpose (the
    design spec's "Nicht verhandelbare Grenzen" table — defense in depth, not redundant).

- [ ] **Step 1: Factor the calendar create/delete logic out of the router** (small, low-risk
  refactor, separate commit before the rest of this task): in `src/kairos/routers/calendar.py`,
  extract `create_event`'s and `delete_event`'s bodies into plain async functions
  (`_create_calendar_event(session, user_id, req) -> dict`, `_delete_calendar_event(session,
  user_id, event_id, confirm) -> None`) that the router endpoints call unchanged — no behavior
  change, verified by the existing `test_calendar_router.py` suite staying green untouched.

- [ ] **Step 2: Write failing tests for each handler** — one test per handler, isolated (mock the
  repository/registry calls, assert the `{summary, data, meta}` shape and the right risk_class/
  requires_confirmation on the `ToolSpec`).

- [ ] **Step 3: Implement** `tools.py` with all 8 `ToolSpec` entries + handlers.

- [ ] **Step 4: Tests, lint, commit** (two commits: the router refactor from Step 1, then the
  tools themselves)
  ```bash
  git commit -m "refactor(calendar): factor create/delete into plain functions the agent can call"
  git commit -m "feat(agent): 8 core tool handlers"
  ```

---

### Task 7: Risk-class dispatcher + Proposal

**Files:**
- Create: `src/kairos/agent/dispatcher.py`
- Test: `tests/test_agent_dispatcher.py`

**Interfaces:**
- Produces: `@dataclass class Proposal: tool_name: str; arguments: dict[str, Any]; summary: str`
  (human-readable description of what would happen, shown in the frontend's confirm card).
  `async def dispatch(session, *, user_id: UUID, tool_call, pending_confirmation: bool) ->
  dict[str, Any] | Proposal` — looks up the `ToolSpec` by `tool_call.name`, and:
  - `risk_class == "read"`, or `tool_name == "remember"` → run the handler immediately, return
    its result dict.
  - otherwise, if not `pending_confirmation` → return a `Proposal` (the orchestrator serializes
    this into the assistant turn instead of a tool result, ending the loop for this turn so the
    user can confirm/reject).
  - otherwise (`pending_confirmation=True`, i.e. this call came from `POST .../confirm`) → run
    the handler, return its result dict.

  This is the single enforcement point referenced everywhere else in this plan and the design
  spec — **no other code path may call a tool handler directly.**

- [ ] **Step 1: Failing tests** — for every risk class: a `read` tool runs immediately; `remember`
  runs immediately despite being `write`; a `write`/`destructive` tool without confirmation
  returns a `Proposal` and does *not* call its handler (assert via a spy/mock that the handler
  was never invoked — this is the regression test the design spec's testing strategy calls for);
  the same tool *with* `pending_confirmation=True` does call its handler.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(agent): risk-class dispatcher enforcing proposal-confirmation"
  ```

---

### Task 8: Orchestrator loop

**Files:**
- Create: `src/kairos/agent/orchestrator.py`
- Test: `tests/test_agent_orchestrator.py`

**Interfaces:**
- Produces: `async def run_turn(session, *, user_id: UUID, conversation_id: UUID, user_message:
  str) -> OrchestratorResult` where `OrchestratorResult` carries the assistant's final text,
  any pending `Proposal`, and any `remember` results from this turn (for the frontend chip).
  Internally: loads recent messages via `ConversationRepository.list_messages`, prepends the
  Situation Brief (Task 5) and a system prompt (persona + health guardrails from
  `docs/03-agent-design.md` §6.3, inlined as a module-level constant) as the first message,
  appends the new user message, persists it, then loops calling `get_completion` (Task 4) →
  `dispatch` (Task 7) per tool call → persists each tool-result message → until the model
  returns a plain text response (or a `Proposal` short-circuits the loop early). Hardcap the
  loop at, say, 8 iterations to avoid a runaway tool-call cycle — return an error result if hit,
  don't loop forever.

- [ ] **Step 1: Failing tests** — mock `get_completion` to return a scripted sequence of
  responses (tool-call turn, then a plain-text turn); assert the right sequence of `dispatch`
  calls and message-persistence calls happens; assert a `Proposal` returned mid-loop ends the
  turn without further `get_completion` calls; assert the 8-iteration hardcap trips on an
  infinite mocked tool-call loop.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(agent): tool-calling orchestrator loop"
  ```

---

### Task 9: Agent router

**Files:**
- Create: `src/kairos/routers/agent.py`
- Modify: `src/kairos/api.py`
- Test: `tests/test_agent_router.py`

**Interfaces:**
- Produces:
  - `POST /api/agent/conversations` — creates a conversation, returns `{id, title, created_at}`.
  - `GET /api/agent/conversations` — list, most-recently-updated first.
  - `GET /api/agent/conversations/{id}/messages` — full message list for the thread view.
  - `POST /api/agent/conversations/{id}/messages` — body `{content: str}`, runs `run_turn`,
    returns the assistant's reply + any `Proposal` + any `remember` results.
  - `POST /api/agent/conversations/{id}/confirm` — body `{tool_name, arguments}` (echoed back
    from the `Proposal` the frontend just showed), re-runs `dispatch` with
    `pending_confirmation=True`, returns the result.

- [ ] **Step 1: Failing router tests** — mock `run_turn`/`dispatch`, assert each endpoint's
  status codes, auth requirement (401 without a session, matching every other router's test
  pattern), and response shape.

- [ ] **Step 2: Implement**, wire `agent_router` into `api.py`.

- [ ] **Step 3: Tests, lint, commit**
  ```bash
  git commit -m "feat(agent): conversation + messaging REST API"
  ```

---

### Task 10: Frontend — `/chat`

**Files:**
- Create: `web/src/routes/chat/+page.server.ts`, `web/src/routes/chat/+page.svelte`
- Modify: `web/src/lib/types.ts`, `web/src/routes/+layout.svelte`
- Test: `web/tests/unit/chat-types.test.ts` (or fold into a component test if one exists by then)

**Interfaces:**
- Produces: `ChatMessage`, `Conversation`, `Proposal` types in `types.ts` mirroring the backend
  response shapes from Task 9. Page: conversation list (left or a top dropdown — reuse the
  `.menu-panel` pattern from `+layout.svelte` if a sidebar feels heavy for v1), message thread,
  input box wired to `POST .../messages` via a form action, a `remember`-chip renderer ("📝
  Gemerkt: {content} · Rückgängig" with a button calling `DELETE /api/memory/{id}` — the page
  already exists at `/memory`, this just reuses the same `apiDelete` call inline), and a proposal
  card (summary text + Bestätigen/Ablehnen buttons calling `POST .../confirm` or discarding).

- [ ] **Step 1: Types** in `types.ts`.

- [ ] **Step 2: `+page.server.ts`** — `load()` fetches the conversation list (and the active
  conversation's messages if one is selected via a query param); `actions.send`/`actions.confirm`/
  `actions.newConversation` call the Task 9 endpoints.

- [ ] **Step 3: `+page.svelte`** — same `app.css` tokens as every other page (`.tile`, `.btn`,
  `.field`), no new visual language. Manual browser verification required per house rules before
  calling this task done — click through: send a read-only question, send a question that
  triggers `remember` (verify the chip + working Rückgängig), send a question that triggers
  `propose_calendar_event` (verify the confirm card, verify Bestätigen actually creates the
  event via the existing `/calendar` page).

- [ ] **Step 4: Nav link** in `+layout.svelte`, after "Gedächtnis" (design spec's decided
  ordering — Dashboard stays the start page).

- [ ] **Step 5: `npm run check`, `eslint`, `npm run test:unit`, commit**
  ```bash
  git commit -m "feat(web): /chat page — conversation thread, proposals, memory chips"
  ```

---

### Task 11: Eval-suite script (13 reference questions)

**Files:**
- Create: `scripts/agent_eval_suite.py`

**Interfaces:**
- Produces: a standalone script (not a pytest test — it makes real, billed LLM calls, per the
  design spec's testing strategy) that seeds a fixed test dataset, asks each of the 13 in-scope
  reference questions (`docs/00-vision-und-scope.md` §5, all except 13 and 15) through
  `run_turn`, extracts the numbers the question expects via regex, and diffs them against the
  actual tool results from that turn. Prints a pass/fail table + median input-token count across
  the run. Mirrors `scripts/garmin_smoke_test.py`'s "manual, not-CI, real external calls" role.

- [ ] **Step 1: Write the script** — one `EvalCase` per question (`question_text`,
  `expected_tool`, `assertion_fn(tool_result) -> bool`), a `main()` that runs them sequentially
  against a fixed seeded user, prints results.

- [ ] **Step 2: Manual run** — requires a real LLM API key configured (Task 4's gap — you'll need
  to insert a `connection` row by hand for this, same as the `smoke_seed.py`-style approach used
  earlier this session). Record the pass count and token telemetry in `docs/HANDOVER.md` once
  this plan's tasks are all merged — not part of this task's commit, part of closing out the
  whole plan.

- [ ] **Step 3: Lint, commit**
  ```bash
  git commit -m "test(agent): manual eval-suite script for the 13 in-scope reference questions"
  ```

---

## Acceptance (whole-plan, not per-task)

Per the design spec: 13/13 in-scope reference questions correct via `scripts/agent_eval_suite.py`
(Task 11), median input < 15,000 tokens. Every `write`/`destructive` tool call except `remember`
demonstrably requires confirmation before executing (Task 7's dispatcher tests +
`test_agent_orchestrator.py`'s end-to-end version of the same assertion). All existing tests
(211 as of this session) still pass, plus every new test listed above. `ruff`/`mypy --strict`/
`npm run check`/`eslint` clean across the whole diff, not just per-task.

**Known gap carried into this plan on purpose (not silently missed):** no UI exists yet for a
user to enter their own LLM API key (Task 4's note) — needed before this is usable by anyone
other than a developer seeding a `connection` row by hand. Worth a small follow-up task on the
`/account` page (same envelope-encryption pattern already used there for Garmin/Google), not
included here because it's independent of every other task and would only add noise to the
dependency chain above.
