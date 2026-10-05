from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.tools import TOOLS_BY_NAME, ToolSpec


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


async def dispatch(
    session: AsyncSession, *, user_id: UUID, tool_call: ToolCall, pending_confirmation: bool
) -> dict[str, Any] | Proposal:
    """The single enforcement point for risk-class rules (design spec §6.1 /
    Backend-Architektur "Risikoklassen-Durchsetzung"). No other code path may
    call a tool handler directly -- the orchestrator always goes through here.
    """
    spec = TOOLS_BY_NAME.get(tool_call.name)
    if spec is None:
        raise ValueError(f"Unknown tool: {tool_call.name!r}")

    # read tools and remember execute immediately; every other tool needs a
    # Proposal first, unless this call IS the confirmation (POST .../confirm)
    if needs_confirmation(spec) and not pending_confirmation:
        return Proposal(
            tool_name=spec.name,
            arguments=tool_call.arguments,
            summary=_summarize(spec.name, tool_call.arguments),
            tool_call_id=tool_call.id,
        )

    return await spec.handler(session, user_id=user_id, **tool_call.arguments)


def _summarize(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "propose_calendar_event":
        return (
            f"Termin \"{arguments.get('summary')}\" anlegen: "
            f"{arguments.get('start_at')} - {arguments.get('end_at')}"
        )
    if tool_name == "delete_calendar_event":
        return f"Termin {arguments.get('event_id')} löschen"
    return f"{tool_name} ausführen mit {arguments}"
