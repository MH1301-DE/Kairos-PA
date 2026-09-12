from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from litellm.types.utils import ChatCompletionMessageToolCall
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import Proposal, ToolCall, dispatch
from kairos.agent.llm_client import get_completion
from kairos.agent.situation_brief import build_situation_brief
from kairos.agent.tools import CORE_TOOLS
from kairos.repositories.conversation import ConversationRepository

# hardcap so a runaway tool-call cycle (model keeps calling tools without ever
# producing a plain-text reply) can't loop forever
_MAX_LOOP_ITERATIONS = 8

# persona + health guardrails, docs/03-agent-design.md §6.3 -- unchanged from
# that spec, just inlined here since there is no prompt-registry in the MVP
_SYSTEM_PROMPT = """\
Du bist Kairos, ein persönlicher Gesundheits- und Trainingsassistent.

Regeln:
- Zahlen kommen ausschließlich aus Tool-Ergebnissen dieses Turns, nie aus deinem \
eigenen Wissen oder einer Schätzung.
- Keine Diagnosen, keine Aussagen über Krankheitsursachen, keine Medikation.
- Bei auffälligen Mustern (z.B. Ruhepuls deutlich über der Baseline über mehrere \
Tage, SpO2-Auffälligkeiten): sachlicher Hinweis auf den Befund plus Empfehlung \
ärztlicher Abklärung, ohne eigene Deutung.
- Keine Empfehlungen zu Gewichtsreduktion, Kalorienzielen oder Nüchterntraining \
ohne ausdrückliche Nachfrage, und dann konservativ.
- Bei Anzeichen für Übertraining wird die Belastungsempfehlung nach unten \
korrigiert, nicht nach oben.
"""


@dataclass(frozen=True)
class OrchestratorResult:
    reply_text: str | None
    proposal: Proposal | None
    remembered: list[dict[str, Any]] = field(default_factory=list)


async def run_turn(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, user_message: str
) -> OrchestratorResult:
    conv_repo = ConversationRepository(session=session)
    brief = await build_situation_brief(session, user_id=user_id, now=datetime.now(UTC))
    history = await conv_repo.list_messages(conversation_id=conversation_id, user_id=user_id)

    system_content = _SYSTEM_PROMPT + "\n\n" + brief
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    for m in history:
        messages.append(_history_message_to_llm(m.role, m.content, m.tool_calls, m.tool_call_id))
    messages.append({"role": "user", "content": user_message})

    await conv_repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="user", content=user_message
    )

    tools_schema = [_to_openai_tool(t) for t in CORE_TOOLS]
    remembered: list[dict[str, Any]] = []

    for _ in range(_MAX_LOOP_ITERATIONS):
        response = await get_completion(
            session, user_id=user_id, messages=messages, tools=tools_schema
        )
        message = response.choices[0].message

        if not message.tool_calls:
            await conv_repo.append_message(
                conversation_id=conversation_id, user_id=user_id, role="assistant",
                content=message.content,
            )
            return OrchestratorResult(
                reply_text=message.content, proposal=None, remembered=remembered
            )

        tool_calls = _function_tool_calls(message.tool_calls)
        tool_calls_data = [
            {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
            for tc in tool_calls
        ]
        await conv_repo.append_message(
            conversation_id=conversation_id, user_id=user_id, role="assistant",
            content=message.content, tool_calls=tool_calls_data,
        )
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            if tc.function.name is None:
                raise ValueError("Tool call from the model is missing a function name")
            call = ToolCall(name=tc.function.name, arguments=json.loads(tc.function.arguments))
            try:
                result = await dispatch(
                    session, user_id=user_id, tool_call=call, pending_confirmation=False
                )
            except Exception as exc:
                result = {"summary": f"Fehler: {exc}", "data": None, "meta": {}}

            if isinstance(result, Proposal):
                # short-circuits the loop -- the user must confirm/reject before
                # anything else happens, no further get_completion calls this turn
                return OrchestratorResult(reply_text=None, proposal=result, remembered=remembered)

            if call.name == "remember":
                remembered.append(result["data"])

            result_json = json.dumps(result)
            await conv_repo.append_message(
                conversation_id=conversation_id, user_id=user_id, role="tool",
                content=result_json, tool_call_id=tc.id,
            )
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})

    return OrchestratorResult(
        reply_text="Zu viele Tool-Aufrufe in diesem Turn -- bitte die Frage neu formulieren.",
        proposal=None, remembered=remembered,
    )


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
            "description": f"{tool.name} ({tool.risk_class})",
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
