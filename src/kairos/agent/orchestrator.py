from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import litellm
import openai
from litellm.types.utils import ChatCompletionMessageToolCall
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import Proposal, ToolCall, dispatch, needs_confirmation
from kairos.agent.events import AgentEvent
from kairos.agent.history import (
    HISTORY_BUDGET_TOKENS,
    NOT_CONFIRMED,
    repair_history,
    split_turns,
    window_turns,
)
from kairos.agent.llm_client import NoLlmCredentialConfigured, stream_completion
from kairos.agent.memory_extraction import compact_conversation
from kairos.agent.prompt import build_system_prompt
from kairos.agent.tools import CORE_TOOLS, TOOLS_BY_NAME
from kairos.repositories.conversation import ConversationRepository

logger = logging.getLogger(__name__)

# hardcap so a runaway tool-call cycle (model keeps calling tools without ever
# producing a plain-text reply) can't loop forever
_MAX_LOOP_ITERATIONS = 8

SKIPPED_PENDING_PROPOSAL = "Nicht ausgeführt: wartet auf Bestätigung eines anderen Vorschlags."
TOO_MANY_TOOL_CALLS = "Zu viele Tool-Aufrufe in diesem Turn -- bitte die Frage neu formulieren."


def tool_result(summary: str) -> dict[str, Any]:
    return {"summary": summary, "data": None, "meta": {}}


@dataclass(frozen=True)
class OrchestratorResult:
    reply_text: str | None
    proposal: Proposal | None
    remembered: list[dict[str, Any]] = field(default_factory=list)


class AgentTurnError(RuntimeError):
    pass


def stream_turn(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, user_message: str
) -> AsyncIterator[AgentEvent]:
    return _run_loop(
        session, user_id=user_id, conversation_id=conversation_id, user_message=user_message
    )


def stream_continuation(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID
) -> AsyncIterator[AgentEvent]:
    return _run_loop(session, user_id=user_id, conversation_id=conversation_id, user_message=None)


async def run_turn(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, user_message: str
) -> OrchestratorResult:
    reply_parts: list[str] = []
    proposal: Proposal | None = None
    remembered: list[dict[str, Any]] = []
    error: str | None = None
    async for event in stream_turn(
        session, user_id=user_id, conversation_id=conversation_id, user_message=user_message
    ):
        if event.type == "token":
            reply_parts.append(event.data["text"])
        elif event.type in ("tool_start", "tool_end"):
            # only the final round's text is the reply
            reply_parts = []
        elif event.type == "proposal":
            proposal = Proposal(
                tool_name=event.data["tool_name"], arguments=event.data["arguments"],
                summary=event.data["summary"], tool_call_id=event.data["tool_call_id"],
            )
        elif event.type == "memory":
            remembered.append(event.data)
        elif event.type == "error":
            error = event.data["detail"]
    if error is not None:
        raise AgentTurnError(error)
    if proposal is not None:
        return OrchestratorResult(reply_text=None, proposal=proposal, remembered=remembered)
    return OrchestratorResult(
        reply_text="".join(reply_parts) if reply_parts else None,
        proposal=None, remembered=remembered,
    )


async def _run_loop(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, user_message: str | None
) -> AsyncIterator[AgentEvent]:
    conv_repo = ConversationRepository(session=session)
    messages = await _load_llm_messages(
        session, conv_repo, user_id=user_id, conversation_id=conversation_id
    )
    if user_message is not None:
        messages.append({"role": "user", "content": user_message})
        await conv_repo.append_message(
            conversation_id=conversation_id, user_id=user_id, role="user", content=user_message
        )
    await session.commit()

    tools_schema = [_to_openai_tool(t) for t in CORE_TOOLS]

    try:
        for _ in range(_MAX_LOOP_ITERATIONS):
            chunks: list[Any] = []
            async for chunk in stream_completion(
                session, user_id=user_id, messages=messages, tools=tools_schema
            ):
                chunks.append(chunk)
                text = _delta_text(chunk)
                if text:
                    yield AgentEvent("token", {"text": text})
            content, raw_tool_calls = _assemble(chunks, messages)

            if not raw_tool_calls:
                await conv_repo.append_message(
                    conversation_id=conversation_id, user_id=user_id, role="assistant",
                    content=content,
                )
                # persist the reply before extraction so a failing extraction cannot lose it
                await session.commit()
                try:
                    extracted = await compact_conversation(
                        session, user_id=user_id, conversation_id=conversation_id,
                        now=datetime.now(UTC),
                    )
                except Exception:
                    await session.rollback()
                    logger.warning("Memory compaction failed", exc_info=True)
                    extracted = []
                for entry in extracted:
                    yield AgentEvent("memory", {
                        "id": str(entry.id), "content": entry.content,
                        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
                    })
                yield AgentEvent("done", {})
                return

            tool_calls = _function_tool_calls(raw_tool_calls)
            tool_calls_data = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in tool_calls
            ]
            await conv_repo.append_message(
                conversation_id=conversation_id, user_id=user_id, role="assistant",
                content=content, tool_calls=tool_calls_data,
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc.id, "type": "function",
                            "function": {
                                "name": tc.function.name, "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # one transaction per round: a disconnect never leaves tool calls without results
            round_events: list[AgentEvent] = []
            for index, tc in enumerate(tool_calls):
                name = tc.function.name
                if name is None:
                    raise ValueError("Tool call from the model is missing a function name")
                spec = TOOLS_BY_NAME.get(name)
                if spec is None or not needs_confirmation(spec):
                    yield AgentEvent("tool_start", {"id": tc.id, "name": name})
                result = await _execute(session, user_id=user_id, tool_call=tc, name=name)

                if isinstance(result, Proposal):
                    # the user must confirm/reject first; later sibling calls still need a result
                    for skipped in tool_calls[index + 1:]:
                        await conv_repo.append_message(
                            conversation_id=conversation_id, user_id=user_id, role="tool",
                            content=json.dumps(
                                tool_result(SKIPPED_PENDING_PROPOSAL), ensure_ascii=False
                            ),
                            tool_call_id=skipped.id,
                        )
                    await session.commit()
                    for event in round_events:
                        yield event
                    yield AgentEvent("proposal", {
                        "tool_call_id": result.tool_call_id or tc.id,
                        "tool_name": result.tool_name, "summary": result.summary,
                        "arguments": result.arguments,
                    })
                    yield AgentEvent("done", {})
                    return

                result_json = json.dumps(result, ensure_ascii=False)
                await conv_repo.append_message(
                    conversation_id=conversation_id, user_id=user_id, role="tool",
                    content=result_json, tool_call_id=tc.id,
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})
                round_events.extend(result_events(tc.id, name, result))
            await session.commit()
            for event in round_events:
                yield event

        yield AgentEvent("token", {"text": TOO_MANY_TOOL_CALLS})
        yield AgentEvent("done", {})
    except NoLlmCredentialConfigured:
        yield AgentEvent("error", {"detail": "no_llm_provider_configured"})
        yield AgentEvent("done", {})
    except openai.OpenAIError as exc:
        # litellm maps every provider error onto the openai.* hierarchy
        logger.warning("LLM call failed for user %s: %s", user_id, exc)
        yield AgentEvent("error", {"detail": "llm_provider_error"})
        yield AgentEvent("done", {})


def result_events(call_id: str, name: str, result: dict[str, Any]) -> list[AgentEvent]:
    summary = str(result.get("summary") or "")
    ok = not summary.startswith(("Fehler", "Ungültige"))
    events = [AgentEvent("tool_end", {"id": call_id, "name": name, "summary": summary, "ok": ok})]
    data = result.get("data")
    if ok and isinstance(data, dict):
        if name == "render":
            events.append(AgentEvent("render", {
                "id": call_id, "component": data.get("component"), "config": data.get("config"),
            }))
        elif name == "remember":
            events.append(AgentEvent("memory", {
                "id": data.get("id"), "content": data.get("content"),
                "expires_at": data.get("expires_at"),
            }))
    return events


async def _execute(
    session: AsyncSession, *, user_id: UUID, tool_call: ChatCompletionMessageToolCall, name: str
) -> dict[str, Any] | Proposal:
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("Argumente müssen ein JSON-Objekt sein")
    except ValueError as exc:  # JSONDecodeError is a ValueError
        return tool_result(f"Ungültige JSON-Argumente: {exc}")
    try:
        # savepoint so a failing handler cannot poison the round's open transaction
        async with session.begin_nested():
            return await dispatch(
                session, user_id=user_id,
                tool_call=ToolCall(name=name, arguments=arguments, id=tool_call.id),
                pending_confirmation=False,
            )
    except Exception as exc:
        return tool_result(f"Fehler: {exc}")


async def _load_llm_messages(
    session: AsyncSession, conv_repo: ConversationRepository, *, user_id: UUID,
    conversation_id: UUID,
) -> list[dict[str, Any]]:
    conversation = await conv_repo.get(user_id=user_id, conversation_id=conversation_id)
    after_seq = conversation.compacted_through_seq if conversation else None
    history = await conv_repo.list_messages_after(
        conversation_id=conversation_id, user_id=user_id, after_seq=after_seq
    )

    # an unanswered proposal leaves tool calls without results; close them in the DB
    answered = {m.tool_call_id for m in history if m.role == "tool"}
    closed_any = False
    for m in history:
        for open_call in (m.tool_calls or []) if m.role == "assistant" else []:
            if open_call["id"] not in answered:
                answered.add(open_call["id"])
                closed_any = True
                await conv_repo.append_message(
                    conversation_id=conversation_id, user_id=user_id, role="tool",
                    content=json.dumps(tool_result(NOT_CONFIRMED), ensure_ascii=False),
                    tool_call_id=open_call["id"],
                )
    if closed_any:
        history = await conv_repo.list_messages_after(
            conversation_id=conversation_id, user_id=user_id, after_seq=after_seq
        )
    kept_turns, _ = window_turns(split_turns(history), HISTORY_BUDGET_TOKENS)
    history = [m for turn in kept_turns for m in turn]

    system_content = await build_system_prompt(session, user_id=user_id, now=datetime.now(UTC))
    history_messages = [
        _history_message_to_llm(m.role, m.content, m.tool_calls, m.tool_call_id) for m in history
    ]
    return [{"role": "system", "content": system_content}, *repair_history(history_messages)]


def _delta_text(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    content = getattr(getattr(choices[0], "delta", None), "content", None)
    return content if isinstance(content, str) else None


def _assemble(chunks: list[Any], messages: list[dict[str, Any]]) -> tuple[str | None, list[Any]]:
    built: Any = litellm.stream_chunk_builder(chunks, messages=messages) if chunks else None
    if built is None or not built.choices:
        return None, []
    message = built.choices[0].message
    return message.content, list(message.tool_calls or [])


def _function_tool_calls(
    tool_calls: list[Any],
) -> list[ChatCompletionMessageToolCall]:
    # litellm's Message.tool_calls type also allows "custom" tool calls (a
    # newer OpenAI variant with no .function attribute) -- CORE_TOOLS only ever
    # registers standard function tools, so this should never actually fire
    result = []
    for tc in tool_calls:
        if not isinstance(tc, ChatCompletionMessageToolCall):
            raise ValueError(f"Unsupported tool call type: {type(tc).__name__}")
        result.append(tc)
    return result


def _to_openai_tool(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.json_schema,
        },
    }


def _history_message_to_llm(
    role: str,
    content: str | None,
    tool_calls: list[dict[str, Any]] | None,
    tool_call_id: str | None,
) -> dict[str, Any]:
    if role == "assistant" and tool_calls:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ],
        }
    if role == "tool":
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
    return {"role": role, "content": content}
