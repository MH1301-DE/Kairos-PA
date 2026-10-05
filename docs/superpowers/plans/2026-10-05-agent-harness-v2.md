# Agent-Harness v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Kairos chat agent correct (valid history after proposals, no crash on bad tool JSON), informed (metric catalog + real tool descriptions), memory-aware (expiring memories, token-budgeted history with memory extraction) and fast to respond (SSE streaming with inline charts).

**Architecture:** The orchestrator becomes an async generator (`stream_turn`) that yields typed events; a thin non-streaming wrapper (`run_turn`) keeps the eval suite and existing tests working. Proposals are bound to the model's own `tool_call_id` and resolved server-side. History is windowed on turn boundaries under a token budget; turns that fall out of the window are distilled into `agent_memory` rows (optionally expiring) after the reply has finished streaming.

**Tech Stack:** Python 3.12+, FastAPI (`StreamingResponse`), SQLAlchemy async, Alembic, litellm 1.100 (`acompletion(stream=True)`, `stream_chunk_builder`), pytest + testcontainers; SvelteKit 2 / Svelte 5 runes, ECharts 6, `marked` + `dompurify`.

**Spec:** `docs/superpowers/specs/2026-10-05-agent-harness-v2-design.md`

## Global Constraints

- Tests: `.venv/Scripts/python -m pytest -q` must stay fully green with Docker running (currently 307 passed, 0 skipped); every task adds its own tests.
- `ruff check` (line-length 100) and `mypy --strict src` clean on touched files. Pre-existing `B008` on FastAPI `Depends(...)` defaults is accepted repo-wide — do not "fix" it.
- Frontend: `cd web && npm run check` (0 errors) and `npx vitest run --project server` green. In the Bash tool prefix npm commands with `export PATH="/c/Program Files/nodejs:$PATH" &&`.
- Every session touching RLS tables calls `install_rls_listener(session, user_id)` (FORCE ROW LEVEL SECURITY on all tenant tables).
- Comments: one short line, only what the code cannot show. No docstrings on code you didn't change.
- Conventional commits; end each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- All user-facing strings (tool results, prompts, UI) are German.
- History budget: 12 000 estimated tokens; memory block budget: 1 500 estimated tokens; token estimate = `len(json.dumps(obj, ensure_ascii=False)) // 4` (deterministic, no tokenizer download — deliberate deviation from the spec's `litellm.token_counter`).
- Render components: exactly `TimeSeriesChart`, `BarChart`, `Gauge`, `StatCard`, `Table`.
- SSE event names: exactly `token`, `tool_start`, `tool_end`, `render`, `memory`, `proposal`, `error`, `done`.

### Documented deviations from the spec

- Custom metrics are **not** listed in the metric catalog: no agent tool can query them today (`query_health`/`analyze_records` only consult `build_default_registry()` and `metric_daily_value`, which never contains custom codes). Listing them would make the model call tools that are guaranteed to fail.
- Token counting uses the char/4 estimate above instead of `litellm.token_counter` (offline, deterministic in tests).

## Review Focus

1. **Existing conversations created before this plan** contain assistant tool calls with no tool result (old `/confirm` flow) — loading them must not break the next LLM call. Pinned in Task 1 (`repair_history` test with a dangling call) and Task 5 (window loader test).
2. **User double-clicks "Bestätigen"** — the second confirm must not execute the tool twice. Pinned in Task 2 (`409 proposal_already_resolved` test).
3. **Client disconnects mid-stream** (tab closed) — the turn's messages written so far must still be committed, no half-written assistant/tool pair. Pinned in Task 6 (generator closed early test).
4. **Model emits a `render` config that doesn't match the component schema** — must come back to the model as a tool error, never reach the browser as a broken chart. Pinned in Task 7.
5. **Memory extraction LLM call fails or returns non-JSON** — the user's turn must still succeed and `compacted_through_seq` must not advance. Pinned in Task 5.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/kairos/agent/dispatcher.py` | `ToolCall.id`, `Proposal.tool_call_id`, `needs_confirmation(spec)` |
| `src/kairos/agent/history.py` (new) | pure functions: `repair_history`, `split_turns`, `estimate_tokens`, `window_turns` |
| `src/kairos/agent/metric_catalog.py` (new) | `METRIC_CATALOG`, `render_metric_catalog()` |
| `src/kairos/agent/prompt.py` (new) | `SYSTEM_PROMPT`, `build_system_prompt(session, user_id, now)` (persona + catalog + memories + situation brief) |
| `src/kairos/agent/render_schemas.py` (new) | per-component config validation for `render` |
| `src/kairos/agent/memory_extraction.py` (new) | `extract_memories_from_turns`, `compact_conversation` |
| `src/kairos/agent/events.py` (new) | `AgentEvent` dataclass + `to_sse()` |
| `src/kairos/agent/orchestrator.py` | `stream_turn` / `stream_continuation` generators, `run_turn` wrapper |
| `src/kairos/agent/tools.py` | `ToolSpec.description`, `remember` expiry, `recall` active-only, render validation |
| `src/kairos/agent/llm_client.py` | `stream_completion` (async, streaming) next to `get_completion` |
| `src/kairos/repositories/conversation.py` | `find_tool_call`, `has_tool_result`, `list_messages_after`, `set_compacted_through` |
| `src/kairos/repositories/memory.py` | `expires_at`, `list_active`, `delete_expired` |
| `src/kairos/routers/agent.py` | `/stream`, `/proposals/{id}/confirm`, `/proposals/{id}/reject`; old `/messages` POST and `/confirm` removed |
| `alembic/versions/7a1c2e9d4b30_memory_expiry_and_compaction.py` (new) | `agent_memory.expires_at`, `conversation.compacted_through_seq` |
| `web/src/lib/chat/sse.ts` (new) | SSE parser over `fetch` body |
| `web/src/lib/chat/ChatChart.svelte` (new) | renders a `render` event via `EChartsBase` |
| `web/src/lib/chat/Markdown.svelte` (new) | `marked` + `DOMPurify` |
| `web/src/routes/chat/+page.svelte`, `+page.server.ts` | streaming chat UI |
| `scripts/agent_eval_suite.py` | real seed data, multi-turn case, TTFT |

---

### Task 1: Orchestrator — invalid tool JSON, proposal binding, history repair

**Files:**
- Create: `src/kairos/agent/history.py`
- Modify: `src/kairos/agent/dispatcher.py`, `src/kairos/agent/orchestrator.py`
- Test: `tests/test_agent_history.py` (new), `tests/test_agent_orchestrator.py`

**Interfaces:**
- Produces: `ToolCall(name: str, arguments: dict[str, Any], id: str | None = None)`; `Proposal(tool_name, arguments, summary, tool_call_id: str | None = None)`; `needs_confirmation(spec: ToolSpec) -> bool`; `history.repair_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]`; orchestrator constants `SKIPPED_PENDING_PROPOSAL`, `NOT_CONFIRMED`, helper `tool_result(summary: str) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests for `repair_history`** (`tests/test_agent_history.py`)

```python
from __future__ import annotations

from kairos.agent.history import repair_history


def _assistant(*ids: str) -> dict:
    return {
        "role": "assistant", "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "query_health", "arguments": "{}"}}
            for i in ids
        ],
    }


def test_dangling_tool_call_gets_synthetic_result_right_after_its_assistant_message() -> None:
    messages = [
        {"role": "user", "content": "a"},
        _assistant("call_1"),
        {"role": "user", "content": "b"},
    ]
    repaired = repair_history(messages)
    assert [m["role"] for m in repaired] == ["user", "assistant", "tool", "user"]
    assert repaired[2]["tool_call_id"] == "call_1"
    assert "nicht" in repaired[2]["content"].lower()


def test_existing_results_are_kept_and_only_missing_ones_added() -> None:
    messages = [
        {"role": "user", "content": "a"},
        _assistant("call_1", "call_2"),
        {"role": "tool", "tool_call_id": "call_2", "content": "{}"},
    ]
    repaired = repair_history(messages)
    tool_ids = [m["tool_call_id"] for m in repaired if m["role"] == "tool"]
    assert sorted(tool_ids) == ["call_1", "call_2"]
    assert len(repaired) == 4


def test_orphan_tool_message_without_preceding_call_is_dropped() -> None:
    messages = [
        {"role": "tool", "tool_call_id": "gone", "content": "{}"},
        {"role": "user", "content": "a"},
    ]
    assert repair_history(messages) == [{"role": "user", "content": "a"}]
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q tests/test_agent_history.py` — expect FAIL (`ModuleNotFoundError: kairos.agent.history`).

- [ ] **Step 3: Implement `src/kairos/agent/history.py`**

```python
from __future__ import annotations

import json
from typing import Any

NOT_CONFIRMED = (
    "Nicht ausgeführt: der Nutzer hat diesen Vorschlag weder bestätigt noch abgelehnt."
)


def _synthetic_result(tool_call_id: str) -> dict[str, Any]:
    return {
        "role": "tool", "tool_call_id": tool_call_id,
        "content": json.dumps({"summary": NOT_CONFIRMED, "data": None, "meta": {}}),
    }


def repair_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # providers reject tool calls without results and results without calls
    answered = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    known_calls: set[str] = set()
    repaired: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "tool":
            if m["tool_call_id"] in known_calls:
                repaired.append(m)
            continue
        repaired.append(m)
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                known_calls.add(tc["id"])
                if tc["id"] not in answered:
                    repaired.append(_synthetic_result(tc["id"]))
    return repaired
```

- [ ] **Step 4: Run** the history tests — expect PASS.

- [ ] **Step 5: Write failing orchestrator tests** (append to `tests/test_agent_orchestrator.py`, reusing its `_new_conversation`, `_fake_response`, `_fake_tool_call` helpers)

```python
@pytest.mark.asyncio
async def test_invalid_tool_json_is_returned_to_the_model_not_raised(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    bad_call = _fake_tool_call("call_1", "query_health", '{"metric_id": ')
    completion = AsyncMock(side_effect=[
        _fake_response(None, [bad_call]), _fake_response("Korrigiert."),
    ])
    with (
        patch.object(orchestrator_module, "get_completion", new=completion),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock()) as mock_dispatch,
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="x"
        )
    assert result.reply_text == "Korrigiert."
    mock_dispatch.assert_not_called()
    second_call_messages = completion.call_args_list[1].kwargs["messages"]
    tool_msg = next(m for m in second_call_messages if m["role"] == "tool")
    assert "Ungültige JSON-Argumente" in tool_msg["content"]


@pytest.mark.asyncio
async def test_proposal_carries_tool_call_id_and_siblings_get_skipped_results(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    calls = [
        _fake_tool_call("call_p", "propose_calendar_event",
                        '{"summary": "Lauf", "start_at": "2026-10-06T07:00:00+00:00",'
                        ' "end_at": "2026-10-06T08:00:00+00:00"}'),
        _fake_tool_call("call_q", "query_health", '{"metric_id": "hrv_baseline"}'),
    ]
    proposal = Proposal(tool_name="propose_calendar_event", arguments={}, summary="s",
                        tool_call_id="call_p")
    with (
        patch.object(orchestrator_module, "get_completion",
                     new=AsyncMock(return_value=_fake_response(None, calls))),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=proposal)),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="plan"
        )
    assert result.proposal is not None
    assert result.proposal.tool_call_id == "call_p"
    repo = ConversationRepository(session=session)
    tool_msgs = [m for m in await repo.list_messages(conversation_id=conversation_id,
                                                     user_id=user_id) if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["call_q"]
    assert "wartet auf Bestätigung" in (tool_msgs[0].content or "")


@pytest.mark.asyncio
async def test_unanswered_proposal_is_closed_when_the_user_writes_again(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    repo = ConversationRepository(session=session)
    await repo.append_message(conversation_id=conversation_id, user_id=user_id, role="user",
                              content="plan")
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event", "arguments": "{}"}],
    )
    await session.commit()
    completion = AsyncMock(return_value=_fake_response("Ok."))
    with patch.object(orchestrator_module, "get_completion", new=completion):
        await run_turn(session, user_id=user_id, conversation_id=conversation_id,
                       user_message="lieber nicht")
    stored = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    closing = [m for m in stored if m.role == "tool" and m.tool_call_id == "call_p"]
    assert len(closing) == 1
    sent = completion.call_args.kwargs["messages"]
    assert any(m["role"] == "tool" and m["tool_call_id"] == "call_p" for m in sent)
```

- [ ] **Step 6: Run** `.venv/Scripts/python -m pytest -q tests/test_agent_orchestrator.py` — the three new tests FAIL.

- [ ] **Step 7: Implement.** In `dispatcher.py`:

```python
@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class Proposal:
    tool_name: str
    arguments: dict[str, Any]
    summary: str
    tool_call_id: str | None = None


def needs_confirmation(spec: ToolSpec) -> bool:
    # remember is the one write-class tool that runs immediately (undo chip instead)
    return spec.risk_class != "read" and spec.name != "remember"
```

(import `ToolSpec` from `kairos.agent.tools`; in `dispatch` replace the inline condition with `if not needs_confirmation(spec):` and build `Proposal(..., tool_call_id=tool_call.id)`).

In `orchestrator.py`:
- add `SKIPPED_PENDING_PROPOSAL = "Nicht ausgeführt: wartet auf Bestätigung eines anderen Vorschlags."` and `def tool_result(summary: str) -> dict[str, Any]: return {"summary": summary, "data": None, "meta": {}}`;
- before building `messages`, close open calls in the DB: for every `tool_calls` id in `history` that has no `role='tool'` message with that `tool_call_id`, `append_message(role="tool", content=json.dumps(tool_result(NOT_CONFIRMED)), tool_call_id=id)` (import `NOT_CONFIRMED` from `history`), then reload `history`;
- build the LLM message list as now, then pass it through `repair_history(...)` (excluding the system message) before the loop;
- in the tool loop parse arguments safely and bind the id:

```python
for index, tc in enumerate(tool_calls):
    if tc.function.name is None:
        raise ValueError("Tool call from the model is missing a function name")
    try:
        arguments = json.loads(tc.function.arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("Argumente müssen ein JSON-Objekt sein")
    except ValueError as exc:  # JSONDecodeError is a ValueError
        result: dict[str, Any] | Proposal = tool_result(f"Ungültige JSON-Argumente: {exc}")
        call_name = tc.function.name
    else:
        call = ToolCall(name=tc.function.name, arguments=arguments, id=tc.id)
        call_name = call.name
        try:
            result = await dispatch(
                session, user_id=user_id, tool_call=call, pending_confirmation=False
            )
        except Exception as exc:
            result = tool_result(f"Fehler: {exc}")

    if isinstance(result, Proposal):
        for skipped in tool_calls[index + 1:]:
            await conv_repo.append_message(
                conversation_id=conversation_id, user_id=user_id, role="tool",
                content=json.dumps(tool_result(SKIPPED_PENDING_PROPOSAL)),
                tool_call_id=skipped.id,
            )
        return OrchestratorResult(reply_text=None, proposal=result, remembered=remembered)

    if call_name == "remember" and result.get("data"):
        remembered.append(result["data"])
    # ...existing append of the tool message + messages.append(...) unchanged
```

- [ ] **Step 8: Run** `.venv/Scripts/python -m pytest -q tests/test_agent_history.py tests/test_agent_orchestrator.py tests/test_agent_dispatcher.py` — expect PASS. Then `ruff check src/kairos/agent tests/test_agent_history.py tests/test_agent_orchestrator.py` and `mypy --strict src`.

- [ ] **Step 9: Commit**

```bash
git add src/kairos/agent/history.py src/kairos/agent/dispatcher.py src/kairos/agent/orchestrator.py tests/test_agent_history.py tests/test_agent_orchestrator.py
git commit -m "fix(agent): bind proposals to tool_call_id, repair history, survive bad tool JSON"
```

---

### Task 2: Server-side proposal confirm/reject

**Files:**
- Modify: `src/kairos/repositories/conversation.py`, `src/kairos/routers/agent.py`, `web/src/lib/types.ts`, `web/src/routes/chat/+page.server.ts`, `web/src/routes/chat/+page.svelte`
- Test: `tests/test_agent_router.py`, `tests/test_conversation_repository_integration.py`

**Interfaces:**
- Consumes: `ToolCall(..., id=)`, `needs_confirmation(spec)`, `tool_result(summary)` (Task 1), `TOOLS_BY_NAME`.
- Produces: `ConversationRepository.find_tool_call(*, conversation_id: UUID, user_id: UUID, tool_call_id: str) -> dict[str, Any] | None` (returns the stored `{"id","name","arguments"}` dict); `ConversationRepository.has_tool_result(*, conversation_id, user_id, tool_call_id) -> bool`; routes `POST /api/agent/conversations/{conversation_id}/proposals/{tool_call_id}/confirm` → tool result envelope JSON; `.../reject` → `{"rejected": true}`; `_proposal_to_dict` now includes `"tool_call_id"`; TS `Proposal.tool_call_id: string`.

- [ ] **Step 1: Failing repository test** (append to `tests/test_conversation_repository_integration.py`, mirror its user/conversation setup helpers)

```python
@pytest.mark.asyncio
async def test_find_tool_call_and_has_tool_result(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)  # use the file's existing helper
    repo = ConversationRepository(session=session)
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event", "arguments": "{\"a\": 1}"}],
    )
    found = await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )
    assert found == {"id": "call_p", "name": "propose_calendar_event", "arguments": "{\"a\": 1}"}
    assert await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="nope"
    ) is None
    assert not await repo.has_tool_result(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )
    await repo.append_message(conversation_id=conversation_id, user_id=user_id, role="tool",
                              content="{}", tool_call_id="call_p")
    assert await repo.has_tool_result(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )
```

(If the file has no `_new_conversation` helper, add one identical to the one in `tests/test_agent_orchestrator.py`.)

- [ ] **Step 2: Run it** — FAIL (`AttributeError: find_tool_call`).

- [ ] **Step 3: Implement in `ConversationRepository`**

```python
    async def find_tool_call(
        self, *, conversation_id: UUID, user_id: UUID, tool_call_id: str
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
                ConversationMessage.role == "assistant",
                ConversationMessage.tool_calls.contains([{"id": tool_call_id}]),
            )
        )
        message = result.scalars().first()
        if message is None or not message.tool_calls:
            return None
        return next((tc for tc in message.tool_calls if tc["id"] == tool_call_id), None)

    async def has_tool_result(
        self, *, conversation_id: UUID, user_id: UUID, tool_call_id: str
    ) -> bool:
        result = await self._session.execute(
            select(ConversationMessage.id).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
                ConversationMessage.role == "tool",
                ConversationMessage.tool_call_id == tool_call_id,
            )
        )
        return result.first() is not None
```

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Failing router tests** (append to `tests/test_agent_router.py`; uses its `authed_client`, `db_session`, `test_user_id` fixtures)

```python
from kairos.routers import agent as agent_router_module
from kairos.repositories.conversation import ConversationRepository


async def _conversation_with_pending_proposal(
    db_session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID:
    repo = ConversationRepository(session=db_session)
    conversation = await repo.create(user_id=user_id, title="t")
    await repo.append_message(conversation_id=conversation.id, user_id=user_id, role="user",
                              content="Termin bitte")
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event",
                     "arguments": '{"summary": "Lauf", "start_at": "2026-10-06T07:00:00+00:00",'
                                  ' "end_at": "2026-10-06T08:00:00+00:00"}'}],
    )
    await db_session.commit()
    return conversation.id


@pytest.mark.asyncio
async def test_confirm_executes_stored_arguments_and_answers_the_original_call(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    executed = AsyncMock(return_value={"summary": "Termin angelegt", "data": {}, "meta": {}})
    with patch.object(agent_router_module, "dispatch", new=executed):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm"
        )
    assert resp.status_code == 200
    call = executed.call_args.kwargs["tool_call"]
    assert call.name == "propose_calendar_event"
    assert call.arguments["summary"] == "Lauf"
    assert executed.call_args.kwargs["pending_confirmation"] is True
    repo = ConversationRepository(session=db_session)
    assert await repo.has_tool_result(conversation_id=conversation_id, user_id=test_user_id,
                                      tool_call_id="call_p")


@pytest.mark.asyncio
async def test_second_confirm_is_rejected_without_executing_twice(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    executed = AsyncMock(return_value={"summary": "ok", "data": {}, "meta": {}})
    with patch.object(agent_router_module, "dispatch", new=executed):
        first = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
        second = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "proposal_already_resolved"
    assert executed.await_count == 1


@pytest.mark.asyncio
async def test_reject_records_rejection_and_unknown_proposal_is_404(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    resp = await authed_client.post(
        f"/api/agent/conversations/{conversation_id}/proposals/call_p/reject")
    assert resp.status_code == 200
    missing = await authed_client.post(
        f"/api/agent/conversations/{conversation_id}/proposals/nope/confirm")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "proposal_not_found"


@pytest.mark.asyncio
async def test_read_tool_call_cannot_be_confirmed(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    repo = ConversationRepository(session=db_session)
    conversation = await repo.create(user_id=test_user_id, title="t")
    await repo.append_message(
        conversation_id=conversation.id, user_id=test_user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_r", "name": "query_health", "arguments": "{}"}],
    )
    await db_session.commit()
    resp = await authed_client.post(
        f"/api/agent/conversations/{conversation.id}/proposals/call_r/confirm")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "not_a_proposal"
```

Delete any existing test in this file that exercises the removed `POST /{id}/confirm` with a `tool_name`/`arguments` body.

- [ ] **Step 6: Run** — new tests FAIL (404 routes).

- [ ] **Step 7: Implement in `routers/agent.py`:** remove `ConfirmRequest` and the old `confirm_proposal`; add `"tool_call_id": p.tool_call_id` to `_proposal_to_dict`; add:

```python
async def _load_pending_proposal(
    repo: ConversationRepository, *, conversation_id: UUID, user_id: UUID, tool_call_id: str
) -> dict[str, Any]:
    call = await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    if call is None:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    spec = TOOLS_BY_NAME.get(call["name"])
    if spec is None or not needs_confirmation(spec):
        raise HTTPException(status_code=409, detail="not_a_proposal")
    if await repo.has_tool_result(
        conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    ):
        raise HTTPException(status_code=409, detail="proposal_already_resolved")
    return call


@router.post("/{conversation_id}/proposals/{tool_call_id}/confirm")
async def confirm_proposal(
    conversation_id: UUID,
    tool_call_id: str,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    if await repo.get(user_id=user_id, conversation_id=conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    call = await _load_pending_proposal(
        repo, conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    try:
        result = await dispatch(
            session, user_id=user_id,
            tool_call=ToolCall(name=call["name"], arguments=json.loads(call["arguments"] or "{}"),
                               id=tool_call_id),
            pending_confirmation=True,
        )
    except Exception as exc:
        result = tool_result(f"Fehler: {exc}")
    if isinstance(result, Proposal):
        raise HTTPException(status_code=500, detail="unexpected_proposal_on_confirm")
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(result), tool_call_id=tool_call_id,
    )
    await session.commit()
    return result


@router.post("/{conversation_id}/proposals/{tool_call_id}/reject")
async def reject_proposal(
    conversation_id: UUID,
    tool_call_id: str,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    if await repo.get(user_id=user_id, conversation_id=conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    await _load_pending_proposal(
        repo, conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(tool_result("Vom Nutzer abgelehnt.")), tool_call_id=tool_call_id,
    )
    await session.commit()
    return {"rejected": True}
```

- [ ] **Step 8: Frontend (minimal, Task 8 rewrites the page).** `types.ts`: add `tool_call_id: string;` to `Proposal`. `+page.server.ts` `confirm` action: read `tool_call_id` from the form and `apiPost(fetch, \`/api/agent/conversations/${conversationId}/proposals/${toolCallId}/confirm\`, {})`; add a `reject` action posting to `.../reject` returning `{ rejected: true }`. `+page.svelte`: the confirm form sends `tool_call_id` (hidden input) instead of `tool_name`/`arguments`; replace the "Ablehnen" link with a `<form method="POST" action="?/reject" use:enhance>` carrying `conversation_id` and `tool_call_id`.

- [ ] **Step 9: Run** `.venv/Scripts/python -m pytest -q tests/test_agent_router.py tests/test_conversation_repository_integration.py`, ruff, mypy, and `cd web && npm run check` — expect green.

- [ ] **Step 10: Commit**

```bash
git add src/kairos/repositories/conversation.py src/kairos/routers/agent.py tests/test_agent_router.py tests/test_conversation_repository_integration.py web/src/lib/types.ts web/src/routes/chat/+page.server.ts web/src/routes/chat/+page.svelte
git commit -m "fix(agent): confirm/reject proposals server-side by tool_call_id"
```

---

### Task 3: Metric catalog, tool descriptions, system prompt module

**Files:**
- Create: `src/kairos/agent/metric_catalog.py`, `src/kairos/agent/prompt.py`
- Modify: `src/kairos/agent/tools.py` (`ToolSpec.description` + text per tool), `src/kairos/agent/orchestrator.py` (use `build_system_prompt`, `_to_openai_tool` uses `description`)
- Test: `tests/test_agent_metric_catalog.py` (new), `tests/test_agent_tools.py`

**Interfaces:**
- Produces: `METRIC_CATALOG: dict[str, MetricInfo]` with `MetricInfo(description: str, value_shape: str, daily_series: bool)`; `render_metric_catalog() -> str`; `prompt.SYSTEM_PROMPT: str`; `async def build_system_prompt(session: AsyncSession, *, user_id: UUID, now: datetime) -> str` (Task 4 extends it with the memory block); `ToolSpec.description: str` (required, placed after `name`).

- [ ] **Step 1: Failing tests** (`tests/test_agent_metric_catalog.py`)

```python
from __future__ import annotations

from kairos.agent.metric_catalog import METRIC_CATALOG, render_metric_catalog
from kairos.agent.tools import CORE_TOOLS
from kairos.metrics.bootstrap import build_default_registry


def test_every_registered_metric_has_a_catalog_entry() -> None:
    registry = build_default_registry()
    assert set(registry.metric_ids()) == set(METRIC_CATALOG)


def test_rendered_catalog_lists_ids_variants_and_series_flag() -> None:
    text = render_metric_catalog()
    assert "trimp (Varianten: banister, edwards)" in text
    assert "hrv_baseline" in text
    assert "Zeitreihe: ja" in text and "Zeitreihe: nein" in text


def test_every_tool_has_a_real_description() -> None:
    for tool in CORE_TOOLS:
        assert len(tool.description) > 40, tool.name
```

- [ ] **Step 2: Run** — FAIL (module missing).

- [ ] **Step 3: Implement `metric_catalog.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from kairos.metrics.bootstrap import build_default_registry


@dataclass(frozen=True)
class MetricInfo:
    description: str
    value_shape: str
    # only scalar metrics get a metric_daily_value series (see recompute_metric_daily_values)
    daily_series: bool


METRIC_CATALOG: dict[str, MetricInfo] = {
    "trimp": MetricInfo(
        "Trainingsbelastung eines einzelnen Tages aus Herzfrequenz und Dauer.",
        "Zahl in TRIMP-Punkten (0 = kein Training)", True,
    ),
    "training_load": MetricInfo(
        "Fitness (CTL, 42 Tage), Ermüdung (ATL, 7 Tage) und Form (TSB = CTL - ATL).",
        "Objekt {ctl, atl, tsb}", False,
    ),
    "acwr": MetricInfo(
        "Verhältnis akute (7 Tage) zu chronischer (28 Tage) Belastung; > 1,5 = Verletzungsrisiko.",
        "Objekt {ratio}", False,
    ),
    "monotony_strain": MetricInfo(
        "Foster-Monotonie und -Strain der letzten 7 Tage (Gleichförmigkeit der Belastung).",
        "Objekt {monotony, strain}", False,
    ),
    "hr_zone_distribution": MetricInfo(
        "Sekunden in den Herzfrequenzzonen am gewählten Tag.",
        "Objekt {Zonenname: Sekunden}", False,
    ),
    "hrv_baseline": MetricInfo(
        "Heutige HRV gegen das persönliche Baseline-Band der letzten 60 Tage.",
        "Objekt {today, baseline_mean, baseline_low, baseline_high} in ms", False,
    ),
    "resting_hr_trend": MetricInfo(
        "Ruhepuls der letzten Tage gegen den Zeitraum davor.",
        "Objekt {recent_avg, prior_avg, delta_bpm} in bpm", False,
    ),
    "sleep_debt": MetricInfo(
        "Schlafdefizit der letzten 7 Nächte gegen das persönliche Schlafziel.",
        "Zahl in Stunden", True,
    ),
}


def render_metric_catalog() -> str:
    registry = build_default_registry()
    lines = ["VERFÜGBARE KENNZAHLEN (metric_id für query_health/analyze_records):"]
    for metric_id in registry.metric_ids():
        info = METRIC_CATALOG[metric_id]
        variants = ", ".join(registry.variants_for(metric_id))
        series = "ja" if info.daily_series else "nein"
        lines.append(
            f"- {metric_id} (Varianten: {variants}): {info.description} "
            f"Wert: {info.value_shape}. Zeitreihe: {series}."
        )
    lines.append(
        "analyze_records funktioniert nur für Kennzahlen mit Zeitreihe: ja. "
        "Für alle anderen query_health mit as_of für einzelne Tage nutzen."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Implement `prompt.py`** — move `_SYSTEM_PROMPT` from the orchestrator into `SYSTEM_PROMPT` here (unchanged text) and add:

```python
async def build_system_prompt(session: AsyncSession, *, user_id: UUID, now: datetime) -> str:
    brief = await build_situation_brief(session, user_id=user_id, now=now)
    return "\n\n".join([SYSTEM_PROMPT, render_metric_catalog(), brief])
```

In `orchestrator.run_turn` replace the `brief`/`system_content` lines with `system_content = await build_system_prompt(session, user_id=user_id, now=datetime.now(UTC))`.

- [ ] **Step 5: Add `description` to `ToolSpec`** (`name: str`, `description: str`, then existing fields) and give each of the 12 tools a German description. Use exactly these:

| Tool | description |
|---|---|
| query_health | "Wert einer Kennzahl an einem Tag (Default heute). metric_id aus VERFÜGBARE KENNZAHLEN. Für Erholung: hrv_baseline, resting_hr_trend, sleep_debt; für Belastung: training_load, acwr." |
| analyze_records | "Tages-Zeitreihe einer Kennzahl über window_days (max. 60) mit Mittelwert/Min/Max. Nur für Kennzahlen mit 'Zeitreihe: ja' (trimp, sleep_debt)." |
| query_calendar | "Termine zwischen from_date und to_date; mit duration_minutes zusätzlich freie Blöcke mindestens dieser Länge (für Trainingsplanung)." |
| recall | "Durchsucht gespeicherte Erinnerungen über den Nutzer (Ziele, Vorlieben, Einschränkungen). Ohne query: die neuesten Einträge." |
| remember | "Speichert einen Fakt über den Nutzer, der in späteren Gesprächen wichtig ist (Ziel, Verletzung, Vorliebe). Keine Messwerte speichern." |
| render | "Zeigt Daten aus einem vorherigen Tool-Ergebnis als Diagramm oder Karte im Chat. Nur Zahlen aus Tool-Ergebnissen dieses Turns verwenden." |
| propose_calendar_event | "Schlägt einen Kalendertermin vor; wird erst nach Bestätigung durch den Nutzer in Google Calendar angelegt." |
| delete_calendar_event | "Schlägt das Löschen eines Kalendertermins vor; wird erst nach Bestätigung ausgeführt." |
| plan_propose | "Erstellt einen Trainingsplan-Entwurf für weeks Wochen auf Basis freier Kalenderzeit und aktueller Belastung, optional bis goal_date." |
| plan_commit | "Überträgt einen Plan-Entwurf in den Kalender; wird erst nach Bestätigung ausgeführt." |
| plan_adjust | "Reduziert die Belastung künftiger Einheiten eines Plans (z.B. bei Stress oder Krankheit); wird erst nach Bestätigung ausgeführt." |
| plan_progress | "Soll/Ist-Vergleich des aktiven (oder angegebenen) Trainingsplans für die laufende Woche." |

`_to_openai_tool` uses `"description": tool.description`. Any test constructing `ToolSpec(...)` directly must pass `description="..."`.

- [ ] **Step 6: Run** `.venv/Scripts/python -m pytest -q tests/test_agent_metric_catalog.py tests/test_agent_tools.py tests/test_agent_tools_planning.py tests/test_agent_orchestrator.py tests/test_agent_dispatcher.py` + ruff + mypy — PASS.

- [ ] **Step 7: Commit**

```bash
git add src/kairos/agent/metric_catalog.py src/kairos/agent/prompt.py src/kairos/agent/tools.py src/kairos/agent/orchestrator.py tests/test_agent_metric_catalog.py tests/test_agent_tools.py
git commit -m "feat(agent): metric catalog and real tool descriptions in the system prompt"
```

---

### Task 4: Expiring memories + memory block in the prompt

**Files:**
- Create: `alembic/versions/7a1c2e9d4b30_memory_expiry_and_compaction.py`
- Modify: `src/kairos/db/models.py` (`AgentMemory.expires_at`, `Conversation.compacted_through_seq`), `src/kairos/repositories/memory.py`, `src/kairos/agent/tools.py` (`remember`, `recall`), `src/kairos/agent/prompt.py`, `src/kairos/routers/memory.py`, `web/src/lib/types.ts`, `web/src/routes/memory/+page.svelte`
- Test: `tests/test_memory_repository_expiry.py` (new), `tests/test_agent_tools.py`, `tests/test_agent_prompt.py` (new)

**Interfaces:**
- Consumes: `build_system_prompt` (Task 3).
- Produces: `AgentMemory.expires_at: datetime | None`; `Conversation.compacted_through_seq: int | None` (column only — used by Task 5); `SqlMemoryRepository.create(*, user_id, content, source, expires_at: datetime | None = None)`; `list_active(*, user_id: UUID, now: datetime) -> list[AgentMemory]` (newest first); `delete_expired(*, user_id: UUID, now: datetime) -> int`; `remember_handler(..., content: str, expires_at: str | None = None)` (ISO date or datetime; a bare date means end of that day 23:59:59 UTC); memory dict includes `"expires_at": str | None`; `prompt.render_memory_block(entries: list[AgentMemory], budget_tokens: int = 1500) -> str`.

- [ ] **Step 1: Migration** (`down_revision = "27d8fcfada03"`, pattern of `1d9489995959_conversation_message_tool_call_id.py`)

```python
def upgrade() -> None:
    op.add_column(
        "agent_memory", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversation", sa.Column("compacted_through_seq", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("conversation", "compacted_through_seq")
    op.drop_column("agent_memory", "expires_at")
```

Add the matching mapped columns to the two ORM models.

- [ ] **Step 2: Failing repository test** (`tests/test_memory_repository_expiry.py`, integration with the `session` fixture; insert a user like `tests/test_agent_orchestrator.py::_insert_user`, then `install_rls_listener(session, user_id)`)

```python
@pytest.mark.asyncio
async def test_expired_memories_are_hidden_and_deleted(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    await repo.create(user_id=user_id, content="dauerhaft", source="agent")
    await repo.create(user_id=user_id, content="bald weg", source="agent",
                      expires_at=now + timedelta(days=1))
    await repo.create(user_id=user_id, content="abgelaufen", source="agent",
                      expires_at=now - timedelta(minutes=1))
    active = await repo.list_active(user_id=user_id, now=now)
    assert {m.content for m in active} == {"dauerhaft", "bald weg"}
    assert await repo.delete_expired(user_id=user_id, now=now) == 1
    assert len(await repo.list_for_user(user_id=user_id)) == 2
```

- [ ] **Step 3: Run** — FAIL. **Step 4: Implement** `create(..., expires_at=None)` (pass through), and

```python
    async def list_active(self, *, user_id: UUID, now: datetime) -> list[AgentMemory]:
        result = await self._session.execute(
            select(AgentMemory)
            .where(
                AgentMemory.user_id == user_id,
                or_(AgentMemory.expires_at.is_(None), AgentMemory.expires_at > now),
            )
            .order_by(AgentMemory.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_expired(self, *, user_id: UUID, now: datetime) -> int:
        result = await self._session.execute(
            delete(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.expires_at.is_not(None),
                AgentMemory.expires_at <= now,
            )
        )
        rowcount: int = cast(CursorResult[Any], result).rowcount
        return rowcount
```

Run — PASS.

- [ ] **Step 5: Failing tool + prompt tests.** In `tests/test_agent_tools.py`: `remember_handler(session, user_id=..., content="Stress", expires_at="2026-10-11")` stores `expires_at == datetime(2026, 10, 11, 23, 59, 59, tzinfo=UTC)` and returns it in `data["expires_at"]`; an invalid `expires_at="nächste Woche"` raises `ValueError`; `recall_handler` does not return an expired entry. New `tests/test_agent_prompt.py`:

```python
def _entry(content: str, expires_at: datetime | None = None) -> AgentMemory:
    return AgentMemory(id=uuid4(), user_id=uuid4(), content=content, source="agent",
                       expires_at=expires_at)


def test_memory_block_lists_entries_with_expiry_and_respects_budget() -> None:
    entries = [_entry("Ziel: Halbmarathon"),
               _entry("Viel Stress", datetime(2026, 10, 11, 23, 59, 59, tzinfo=UTC))]
    block = render_memory_block(entries)
    assert block.startswith("ERINNERUNGEN")
    assert "- Ziel: Halbmarathon" in block
    assert "- Viel Stress (gilt bis 11.10.2026)" in block
    many = [_entry("x" * 400) for _ in range(50)]
    assert len(render_memory_block(many, budget_tokens=300)) // 4 <= 300


def test_empty_memory_block() -> None:
    assert render_memory_block([]) == "ERINNERUNGEN: keine"
```

- [ ] **Step 6: Run** — FAIL. **Step 7: Implement.**
  - `remember_handler`: parse `expires_at` with a helper `_parse_expiry(value: str) -> datetime` — `date.fromisoformat` for a 10-char value → `datetime.combine(d, time(23, 59, 59), tzinfo=UTC)`, otherwise `datetime.fromisoformat` (naive → assume UTC); on failure raise `ValueError(f"expires_at muss ein ISO-Datum sein, nicht {value!r}")`. JSON schema gains `"expires_at": {"type": "string", "description": "ISO-Datum, nur für zeitlich begrenzte Fakten (z.B. 'nächste Woche viel Stress' → Sonntag dieser Woche). Stabile Fakten ohne Ablauf."}`. Returned `data` includes `"expires_at": entry.expires_at.isoformat() if entry.expires_at else None`.
  - `recall_handler`: use `list_active(user_id=user_id, now=datetime.now(UTC))`.
  - `prompt.py`:

```python
def render_memory_block(entries: list[AgentMemory], budget_tokens: int = 1500) -> str:
    if not entries:
        return "ERINNERUNGEN: keine"
    lines = ["ERINNERUNGEN (vom Nutzer oder von dir gespeichert, neueste zuerst):"]
    used = len(lines[0]) // 4
    for e in entries:
        suffix = f" (gilt bis {e.expires_at.strftime('%d.%m.%Y')})" if e.expires_at else ""
        line = f"- {e.content}{suffix}"
        if used + len(line) // 4 > budget_tokens:
            break
        lines.append(line)
        used += len(line) // 4
    return "\n".join(lines)
```

    and in `build_system_prompt`: `repo = SqlMemoryRepository(session=session)`, `await repo.delete_expired(user_id=user_id, now=now)`, `entries = await repo.list_active(user_id=user_id, now=now)`, join order `[SYSTEM_PROMPT, render_metric_catalog(), render_memory_block(entries), brief]`.
  - `routers/memory.py` `_memory_to_dict` adds `"expires_at"`; `types.ts` `MemoryEntry.expires_at: string | null`; `/memory` page shows `Gilt bis {formatDate(entry.expires_at)}` in the meta line when set.

- [ ] **Step 8: Run** `.venv/Scripts/python -m alembic upgrade head` against the dev DB is NOT part of the task (the controller applies it); run `.venv/Scripts/python -m pytest -q tests/test_memory_repository_expiry.py tests/test_agent_prompt.py tests/test_agent_tools.py tests/test_memory_router.py tests/test_migrations*.py` + ruff + mypy + `npm run check` — PASS.

- [ ] **Step 9: Commit** `feat(agent): expiring memories and a budgeted memory block in the prompt`.

---

### Task 5: Token-budgeted history window + memory extraction

**Files:**
- Modify: `src/kairos/agent/history.py`, `src/kairos/repositories/conversation.py`, `src/kairos/agent/orchestrator.py`
- Create: `src/kairos/agent/memory_extraction.py`
- Test: `tests/test_agent_history.py`, `tests/test_agent_memory_extraction.py` (new)

**Interfaces:**
- Consumes: `repair_history` (Task 1), `Conversation.compacted_through_seq`, `SqlMemoryRepository.create(..., expires_at=)`, `list_active` (Task 4), `get_completion` (existing).
- Produces:
  - `history.estimate_tokens(obj: Any) -> int`
  - `history.split_turns(messages: list[ConversationMessage]) -> list[list[ConversationMessage]]` — a new turn starts at each `role == "user"` message; leading non-user messages form their own first group.
  - `history.window_turns(turns: list[list[ConversationMessage]], budget_tokens: int) -> tuple[list[list[ConversationMessage]], list[list[ConversationMessage]]]` → `(kept, evicted)`; always keeps the newest turn even if it alone exceeds the budget; evicted are the oldest.
  - `history.HISTORY_BUDGET_TOKENS = 12_000`
  - `ConversationRepository.list_messages_after(*, conversation_id, user_id, after_seq: int | None) -> list[ConversationMessage]` (oldest first, all of them, no limit)
  - `ConversationRepository.set_compacted_through(*, conversation_id, user_id, seq: int) -> None`
  - `memory_extraction.compact_conversation(session, *, user_id: UUID, conversation_id: UUID, now: datetime) -> list[AgentMemory]` — runs extraction for turns evicted by the current window and advances `compacted_through_seq` to the last evicted message's `seq`; returns created entries; on any LLM/parse failure logs a warning, creates nothing and leaves `compacted_through_seq` unchanged.
  - Orchestrator: `run_turn` builds history from `list_messages_after(after_seq=conversation.compacted_through_seq)` → `window_turns(...)[0]`; after the final reply it calls `compact_conversation` and appends its results to `OrchestratorResult.remembered`.

- [ ] **Step 1: Failing pure tests** (append to `tests/test_agent_history.py`; build `ConversationMessage(role=..., content=..., seq=n, tool_calls=None, tool_call_id=None)` objects directly)

```python
def _msg(seq: int, role: str, content: str = "x") -> ConversationMessage:
    return ConversationMessage(seq=seq, role=role, content=content, tool_calls=None,
                               tool_call_id=None)


def test_split_turns_starts_a_turn_at_each_user_message() -> None:
    msgs = [_msg(1, "user"), _msg(2, "assistant"), _msg(3, "tool"), _msg(4, "user")]
    assert [[m.seq for m in t] for t in split_turns(msgs)] == [[1, 2, 3], [4]]


def test_window_keeps_newest_turns_within_budget_and_evicts_oldest() -> None:
    turns = [[_msg(i, "user", "y" * 400)] for i in range(1, 6)]  # ~100+ tokens each
    kept, evicted = window_turns(turns, budget_tokens=250)
    assert [t[0].seq for t in kept] == [4, 5]
    assert [t[0].seq for t in evicted] == [1, 2, 3]


def test_window_always_keeps_the_newest_turn() -> None:
    turns = [[_msg(1, "user", "z" * 10_000)]]
    kept, evicted = window_turns(turns, budget_tokens=10)
    assert len(kept) == 1 and evicted == []
```

Token estimate of a turn = `estimate_tokens([{"role": m.role, "content": m.content, "tool_calls": m.tool_calls} for m in turn])`.

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the three functions + constant in `history.py`. Run — PASS.

- [ ] **Step 4: Failing extraction tests** (`tests/test_agent_memory_extraction.py`, integration; patch `memory_extraction.get_completion`)

```python
@pytest.mark.asyncio
async def test_evicted_turns_become_memories_and_compaction_advances(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)  # same helper as orchestrator tests
    repo = ConversationRepository(session=session)
    for i in range(6):
        await repo.append_message(conversation_id=conversation_id, user_id=user_id,
                                  role="user", content=f"Frage {i} " + "w" * 12_000)
        await repo.append_message(conversation_id=conversation_id, user_id=user_id,
                                  role="assistant", content="Antwort")
    await session.commit()
    llm = AsyncMock(return_value=_fake_response(
        '[{"content": "Läuft gern morgens", "expires_at": null},'
        ' {"content": "Erkältet", "expires_at": "2026-10-08"}]'
    ))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id,
            now=datetime(2026, 10, 5, tzinfo=UTC),
        )
    assert [m.content for m in created] == ["Läuft gern morgens", "Erkältet"]
    assert created[1].expires_at == datetime(2026, 10, 8, 23, 59, 59, tzinfo=UTC)
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    assert conversation is not None and conversation.compacted_through_seq is not None
    llm_input = llm.call_args.kwargs["messages"][-1]["content"]
    assert "Frage 0" in llm_input and "Frage 5" not in llm_input


@pytest.mark.asyncio
async def test_failed_extraction_creates_nothing_and_does_not_advance(
    session: AsyncSession,
) -> None:
    # same setup as above
    llm = AsyncMock(return_value=_fake_response("das ist kein JSON"))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(...)
    assert created == []
    assert conversation.compacted_through_seq is None


@pytest.mark.asyncio
async def test_nothing_to_compact_makes_no_llm_call(session: AsyncSession) -> None:
    # two short turns only
    llm = AsyncMock()
    with patch.object(memory_extraction, "get_completion", new=llm):
        assert await compact_conversation(...) == []
    llm.assert_not_called()
```

(Write the elided setup out in full in the test file — copy the first test's setup.)

- [ ] **Step 5: Run** — FAIL. **Step 6: Implement** the repository methods and `memory_extraction.py`:

```python
_EXTRACTION_PROMPT = """\
Du extrahierst aus einem Gesprächsausschnitt Fakten über den Nutzer, die in künftigen \
Gesprächen wichtig sind (Ziele, Verletzungen, Vorlieben, Lebensumstände, Absprachen). \
Keine Messwerte, keine Smalltalk-Inhalte, nichts, was schon in BEREITS GESPEICHERT steht. \
Zeitlich begrenzte Fakten bekommen expires_at (ISO-Datum), stabile Fakten null. \
Antworte ausschließlich mit einem JSON-Array [{"content": str, "expires_at": str|null}], \
leer wenn nichts Neues."""
```

`compact_conversation`: load conversation; `messages = list_messages_after(after_seq=conversation.compacted_through_seq)`; `kept, evicted = window_turns(split_turns(messages), HISTORY_BUDGET_TOKENS)`; if no `evicted` return `[]`; transcript = lines `"{role}: {content}"` for user/assistant messages with content (tool messages skipped); `active = list_active(...)`; call `get_completion(session, user_id=user_id, messages=[{"role": "system", "content": _EXTRACTION_PROMPT}, {"role": "user", "content": "BEREITS GESPEICHERT:\n" + ... + "\n\nGESPRÄCH:\n" + transcript}], tools=None)`; parse `response.choices[0].message.content` with `json.loads` (strip a surrounding ```json fence first); validate list of dicts with str `content`; expiry via the `_parse_expiry` helper from Task 4 (move it to `kairos/agent/expiry.py` if importing it from `tools.py` would create a cycle); create rows `source="agent"`; `set_compacted_through(seq=evicted[-1][-1].seq)`; `commit`. Wrap LLM call + parsing in `try/except Exception` → `logger.warning(...)`, `return []`.

  Orchestrator: replace `list_messages(...)` with `list_messages_after(after_seq=conversation.compacted_through_seq)` + `window_turns(split_turns(...), HISTORY_BUDGET_TOKENS)[0]` flattened (load the conversation via `conv_repo.get`); after persisting the final assistant reply call `compact_conversation(...)` and extend `remembered` with `{"id", "content", "source", "expires_at"}` dicts of the created entries.

- [ ] **Step 7: Run** all agent tests + ruff + mypy — PASS. **Step 8: Commit** `feat(agent): token-budgeted history window with memory extraction`.

---

### Task 6: Streaming orchestrator + SSE endpoints

**Files:**
- Create: `src/kairos/agent/events.py`
- Modify: `src/kairos/agent/llm_client.py`, `src/kairos/agent/orchestrator.py`, `src/kairos/routers/agent.py`
- Test: `tests/test_agent_streaming.py` (new), `tests/test_agent_router.py`, `tests/test_agent_orchestrator.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `events.AgentEvent(type: str, data: dict[str, Any])` with `to_sse() -> str` returning `f"event: {type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"`.
  - `llm_client.stream_completion(session, *, user_id, messages, tools) -> AsyncIterator[Any]` — `await litellm.acompletion(..., stream=True)` and yields chunks; raises `NoLlmCredentialConfigured` like `get_completion`.
  - `orchestrator.stream_turn(session, *, user_id, conversation_id, user_message) -> AsyncIterator[AgentEvent]`
  - `orchestrator.stream_continuation(session, *, user_id, conversation_id) -> AsyncIterator[AgentEvent]` — same loop without appending a user message (used after confirm/reject).
  - `run_turn(...) -> OrchestratorResult` — now consumes `stream_turn` and assembles `reply_text` (joined `token` texts of the final round), `proposal` (from the `proposal` event, rebuilt as `Proposal`), `remembered` (`memory` event payloads).
  - Routes: `POST /{conversation_id}/stream` (body `SendMessageRequest`) → `StreamingResponse(media_type="text/event-stream")`; `POST .../proposals/{id}/confirm` and `/reject` now resolve as in Task 2 and then return a `StreamingResponse` of `stream_continuation` whose **first** event is `tool_end` for the resolved call; `POST /{conversation_id}/messages` is removed.

Event emission rules inside the loop (one round = one `stream_completion`):
- each non-empty `delta.content` → `token {text}`;
- after the round, rebuild the full message with `litellm.stream_chunk_builder(chunks, messages=messages)`;
- per executed tool call: `tool_start {id, name}` before dispatch, `tool_end {id, name, summary, ok}` after (`ok = not summary.startswith(("Fehler", "Ungültige"))`);
- `render` tool success → additionally `render {id, component, config}`;
- `remember` success and every entry from `compact_conversation` → `memory {id, content, expires_at}`;
- Proposal → `proposal {tool_call_id, tool_name, summary}` then `done {}` and stop;
- final text round → persist reply, `compact_conversation`, then `done {}`;
- iteration cap → `token` with the existing "Zu viele Tool-Aufrufe…" text, then `done`;
- `NoLlmCredentialConfigured` → `error {detail: "no_llm_provider_configured"}`; `openai.OpenAIError` → `error {detail: "llm_provider_error"}` (logged); then `done`.
- Commit after every persisted message batch (user message, assistant+tool messages of a round) so a disconnect never loses a written pair; on `GeneratorExit` do not swallow it, just let the already-committed state stand.

- [ ] **Step 1: Failing tests** (`tests/test_agent_streaming.py`). Fake streaming with chunk objects litellm accepts: build them with `litellm.ModelResponse(stream=True, choices=[litellm.utils.StreamingChoices(delta=litellm.utils.Delta(content="Hal"))])`; a tool-call chunk uses `Delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function", "function": {"name": "query_health", "arguments": "{\"metric_id\": \"hrv_baseline\"}"}}])`; final chunk has `finish_reason="stop"` / `"tool_calls"`. Patch `orchestrator_module.stream_completion` with a function returning an async generator per round (use a list of rounds and `side_effect`). Tests:
  1. text-only round yields `token` events whose texts join to the reply, then `done`; DB has user + assistant messages.
  2. tool round then text round yields `tool_start`, `tool_end` (ok true), `token`…, `done` in that order.
  3. a `render` tool call with a valid `StatCard` config yields a `render` event with the config.
  4. proposal yields `proposal` with `tool_call_id` then `done`, no `token` after it.
  5. closing the generator after the first `tool_end` (`await agen.aclose()`) leaves the user, assistant(tool_calls) and tool messages committed (re-read them through a fresh `ConversationRepository` on the same session after `session.rollback()`).
  6. `NoLlmCredentialConfigured` raised by `stream_completion` yields `error {detail: "no_llm_provider_configured"}` then `done`.
  7. `run_turn` still returns `OrchestratorResult(reply_text="Hallo")` for a two-chunk text stream.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** `events.py`, `stream_completion`, `stream_turn`/`stream_continuation` (shared private `_run_loop(...)` generator), rewrite `run_turn` as wrapper. Update existing orchestrator tests that patch `get_completion` to patch `stream_completion` via a small helper `_stream_of(response)` that turns one fake non-streaming response into a chunk stream (put it in `tests/agent_stream_helpers.py` and import it from both test files).
- [ ] **Step 4: Router tests** (append to `tests/test_agent_router.py`): `POST /stream` with `stream_turn` patched to yield two events returns `200`, `content-type` starts with `text/event-stream`, body equals the two `to_sse()` strings; unknown conversation → `404` before streaming; confirm endpoint returns a stream whose first event is `tool_end` with the confirmed call's id; `POST /{id}/messages` returns `405`/`404`.
- [ ] **Step 5: Implement routes.** Use `StreamingResponse(_sse(gen), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})` with `async def _sse(gen): async for ev in gen: yield ev.to_sse()`. Validate conversation ownership and proposal state **before** creating the response so 404/409 stay real HTTP statuses. Set the conversation title from the first message in `/stream` exactly as `send_message` did.
- [ ] **Step 6: Run** full `pytest -q` + ruff + mypy — PASS. **Step 7: Commit** `feat(agent): SSE streaming orchestrator and endpoints`.

---

### Task 7: Render component schemas + tool names in message history

**Files:**
- Create: `src/kairos/agent/render_schemas.py`
- Modify: `src/kairos/agent/tools.py` (`_RENDER_COMPONENTS`, render JSON schema + description, `render_handler`), `src/kairos/routers/agent.py` (`list_messages` adds `tool_name` for tool messages)
- Test: `tests/test_agent_render_schemas.py` (new), `tests/test_agent_router.py`

**Interfaces:**
- Produces: `validate_render_config(component: str, config: dict[str, Any]) -> dict[str, Any]` (returns normalized config, raises `ValueError` with a German message naming the missing/invalid field). Config schemas:
  - `TimeSeriesChart`: `{title: str, unit: str, points: [{date: "YYYY-MM-DD", value: number}] (1..366)}`
  - `BarChart`: `{title: str, unit: str, bars: [{label: str, value: number}] (1..50)}`
  - `Gauge`: `{title: str, unit: str, value: number, min: number, max: number}` with `min < max`
  - `StatCard`: `{title: str, items: [{label: str, value: str|number, unit?: str}] (1..8)}`
  - `Table`: `{title: str, columns: [str] (1..8), rows: [[str|number]] (each row same length as columns, max 50 rows)}`
- `GET .../messages` items gain `"tool_name": str | None` (for `role == "tool"`, resolved from the preceding assistant message's `tool_calls` by `tool_call_id`) and `"tool_call_id"`.

- [ ] **Step 1: Failing tests:** one valid config per component passes and returns the normalized dict; `TimeSeriesChart` with `points: []` → `ValueError` containing "points"; `Gauge` with `min >= max` → `ValueError`; `Table` row length mismatch → `ValueError`; unknown component → `ValueError`; `render_handler` with an invalid config raises (so the orchestrator turns it into a `Fehler:` tool result — assert via `run_turn`-free direct handler call); `GET .../messages` returns `tool_name == "render"` for a stored render tool message.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** with plain Python checks (no new dependency). Set `_RENDER_COMPONENTS` to the five names; the render tool's JSON schema keeps `component` enum + `config: object`, and its `description` gets the five schemas appended in one compact line each so the model knows them. **Step 4: Run** tests + ruff + mypy — PASS. **Step 5: Commit** `feat(agent): validated render components and tool names in message history`.

---

### Task 8: Streaming chat UI with inline charts

**Files:**
- Create: `web/src/lib/chat/sse.ts`, `web/src/lib/chat/ChatChart.svelte`, `web/src/lib/chat/Markdown.svelte`, `web/tests/chat-sse.test.ts`, `web/tests/chat-chart-option.test.ts`
- Modify: `web/package.json` (`marked`, `dompurify`), `web/src/lib/types.ts`, `web/src/routes/chat/+page.svelte`, `web/src/routes/chat/+page.server.ts`

**Interfaces:**
- Consumes: SSE events and payloads from Task 6, render config schemas from Task 7, `GET .../messages` `tool_name` (Task 7).
- Produces:
  - `sse.ts`: `export type ChatEvent = { type: string; data: Record<string, unknown> }`; `export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent>` (splits on blank lines, supports `event:`/`data:` lines, multi-line data joined with `\n`, tolerates `\r\n`); `export async function postStream(path: string, body?: unknown): Promise<AsyncGenerator<ChatEvent>>` — `fetch(path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body ?? {})})`, throws `ApiError(status)` on non-2xx (401 → caller redirects to `/auth/login`).
  - `ChatChart.svelte` props `{ component: string; config: Record<string, unknown> }`; pure helper `export function chartOption(component, config): EChartsOption | null` in `web/src/lib/chat/chartOption.ts` (null for `StatCard`/`Table`, which render as HTML).
  - `Markdown.svelte` prop `{ text: string }` → `{@html DOMPurify.sanitize(marked.parse(text, { async: false }) as string)}`.

- [ ] **Step 1: Install deps:** `cd web && npm install marked dompurify` (dompurify ships its own types).
- [ ] **Step 2: Failing vitest tests** (`web/tests/chat-sse.test.ts`, server project): build a `ReadableStream` from chunks that split an event across chunk boundaries and use `\r\n`; assert `readSse` yields `[{type:'token',data:{text:'Hal'}},{type:'token',data:{text:'lo'}},{type:'done',data:{}}]`. `web/tests/chat-chart-option.test.ts`: `chartOption('TimeSeriesChart', {title:'HRV', unit:'ms', points:[{date:'2026-10-01', value:50}]})` has `xAxis.data == ['2026-10-01']` and `series[0].data == [50]`; `Gauge` produces a `gauge` series with `min`/`max`; `StatCard` → `null`.
- [ ] **Step 3: Run** `npx vitest run --project server` — FAIL. **Step 4: Implement** `sse.ts`, `chartOption.ts`, `ChatChart.svelte` (ECharts via `EChartsBase` with `renderer="svg"` for chart components; `StatCard` as a small grid of label/value; `Table` as a `<table>`), `Markdown.svelte`.
- [ ] **Step 5: Rewrite the chat page** (`+page.svelte`): keep the conversation list/drawer markup and styles; replace the `send` form with a client-side handler:
  - on submit: push the user message locally, create an empty assistant bubble, `for await (const ev of await postStream(\`/api/agent/conversations/${id}/stream\`, {content}))` → `token` appends text (rendered through `Markdown`), `tool_start` shows a muted status line `"{TOOL_LABELS[name] ?? name} …"` (labels: query_health "Kennzahl abfragen", analyze_records "Verlauf analysieren", query_calendar "Kalender prüfen", recall "Erinnerungen durchsuchen", remember "Merken", render "Diagramm erstellen", plan_propose "Plan entwerfen", plan_progress "Planfortschritt prüfen"), `tool_end` clears it, `render` appends a `ChatChart` to the current assistant bubble, `memory` adds the existing undo chip plus "bis {date}" when `expires_at` is set, `proposal` shows the proposal card, `error` shows `status-error` text ("Kein LLM-Anbieter konfiguriert." / "Der KI-Anbieter ist gerade nicht erreichbar."), `done` re-enables input and calls `invalidate('chat:conversations')` (title may have changed).
  - Proposal card buttons call `postStream(.../proposals/${tool_call_id}/confirm)` / `/reject` and feed the returned events into a new assistant bubble the same way.
  - History rendering on load: user/assistant text as before (assistant via `Markdown`); for `role === 'tool' && tool_name === 'render'`, parse `content` and render `ChatChart` from `data.component`/`data.config`.
  - Remove the `send`, `confirm` and `reject` actions from `+page.server.ts` (keep `newConversation` and `forgetRemembered`).
- [ ] **Step 6: Run** `npm run check`, `npx vitest run --project server`, `npx eslint src/routes/chat src/lib/chat` — green.
- [ ] **Step 7: Manual check against the running dev servers** (backend on :8000, `npm run dev` on :5173 — the controller has them running): `curl -N -X POST http://127.0.0.1:8000/api/agent/conversations/<id>/stream` needs a session cookie, so instead verify the Vite proxy streams by requesting `/api/agent/conversations/<random-uuid>/stream` through `http://localhost:5173` and confirming a `401` arrives (proxy path wired); full click-through is done by the human afterwards.
- [ ] **Step 8: Commit** `feat(web): streaming chat with markdown, tool status and inline charts`.

---

### Task 9: Eval suite with real data, multi-turn proposal case, TTFT

**Files:**
- Modify: `scripts/agent_eval_suite.py`
- Test: `tests/test_agent_eval_seed.py` (new, integration)

**Interfaces:**
- Consumes: `stream_turn`, `stream_continuation`, confirm path (`ConversationRepository.find_tool_call` + `dispatch(pending_confirmation=True)`), recompute functions in `kairos.repositories.metrics_recompute`.
- Produces: `seed_test_data(session, user_id) -> None` that leaves `hrv_baseline`, `resting_hr_trend`, `sleep_debt`, `training_load` and `trimp` with `confidence != "insufficient_data"` for `as_of=date.today()`.

- [ ] **Step 1: Failing test** (`tests/test_agent_eval_seed.py`): import `seed_test_data` from `scripts.agent_eval_suite` (add `scripts/__init__.py` if needed, or load via `importlib.util.spec_from_file_location`), run it for a fresh user on the testcontainer session, `install_rls_listener`, then for each of the five metric ids assert `registry.get(metric_id, registry.variants_for(metric_id)[0]).compute(...)` has `confidence != "insufficient_data"`.
- [ ] **Step 2: Run** — FAIL (today's seed yields insufficient data everywhere).
- [ ] **Step 3: Implement the seed.** Read each variant's data source (`src/kairos/metrics/variants/*.py` and the repositories they call) and seed exactly those tables for the last 60 days: an active `connection` row for `garmin` (`credentials_enc` may be a dummy byte string — nothing decrypts it in the eval), `wellness_sample` rows for the HR/HRV metric codes those variants read, `sleep_session` rows (~7 h per night), the existing activity/activity_record HR data; then call `recompute_hr_bucket_seconds_daily`, `recompute_wellness_daily_stats` and `recompute_metric_daily_values` for the 60-day range. Run — PASS.
- [ ] **Step 4: Switch the runner to `stream_turn`:** record `tools_called` from `tool_start` events (drop the dispatch monkeypatch), measure `ttft = time of first token event - start` and total seconds, print both. Add case 16 (multi-turn): "Trag mir morgen um 7 Uhr einen lockeren Lauf von 45 Minuten ein." → expect a `proposal` event; resolve it by executing the stored call through `dispatch(pending_confirmation=True)` with `kairos.agent.tools._create_calendar_event` patched to return a fake event dict (no real Google write), append the tool result, then `stream_continuation` → expect a non-empty reply and no exception, then a follow-up `stream_turn` "Danke, und wie erholt bin ich?" in the same conversation → expect `query_health` and no provider error (this is the regression check for the history bug). Summary prints tool accuracy, median TTFT, median total time.
- [ ] **Step 5: Run** `pytest -q tests/test_agent_eval_seed.py`, ruff, mypy on the script. Do **not** run the live suite in the task (the controller runs it once at the end). **Step 6: Commit** `test(eval): real seed data, multi-turn proposal case and TTFT`.

---

## Final steps (controller)

1. Apply the migration to the dev DB (`.venv/Scripts/python -m alembic upgrade head`) and restart the backend (no backfill is running).
2. Full suite with Docker: `.venv/Scripts/python -m pytest -q`; `npm run check`; vitest.
3. Whole-branch review on the most capable model.
4. Live eval run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/agent_eval_suite.py`.
5. Update `docs/HANDOVER.md` (new section "Agent-Harness v2"), and `CLAUDE.md`'s stale "272 passed" test count.
