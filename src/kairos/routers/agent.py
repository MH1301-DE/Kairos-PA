from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import Proposal, ToolCall, dispatch, needs_confirmation
from kairos.agent.events import AgentEvent
from kairos.agent.history import tool_result
from kairos.agent.orchestrator import result_events, stream_continuation, stream_turn
from kairos.agent.tools import TOOLS_BY_NAME
from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.conversation import ConversationRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/conversations", tags=["agent"])

_TITLE_MAX_LEN = 80


class CreateConversationRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str


@router.post("", status_code=201)
async def create_conversation(
    req: CreateConversationRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title=req.title)
    await session.commit()
    return {
        "id": str(conversation.id), "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
    }


@router.get("")
async def list_conversations(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    conversations = await repo.list_for_user(user_id=user_id)
    return {
        "conversations": [
            {"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()}
            for c in conversations
        ]
    }


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    messages = await repo.list_messages(conversation_id=conversation_id, user_id=user_id, limit=200)
    tool_names = {
        call["id"]: call["name"]
        for m in messages if m.role == "assistant" for call in (m.tool_calls or [])
        if isinstance(call, dict) and "id" in call and "name" in call
    }
    return {
        "messages": [
            {
                "id": str(m.id), "role": m.role, "content": m.content,
                "tool_calls": m.tool_calls, "created_at": m.created_at.isoformat(),
                "tool_call_id": m.tool_call_id,
                "tool_name": tool_names.get(m.tool_call_id) if m.role == "tool" else None,
            }
            for m in messages
        ]
    }


@router.post("/{conversation_id}/stream")
async def stream_message(
    conversation_id: UUID,
    req: SendMessageRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if conversation.title is None:
        conversation.title = req.content[:_TITLE_MAX_LEN]
        await session.commit()
    return _event_stream(
        stream_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message=req.content
        )
    )


def _event_stream(events: AsyncIterator[AgentEvent]) -> StreamingResponse:
    return StreamingResponse(
        _sse(events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield event.to_sse()


async def _prefixed(
    first: list[AgentEvent], rest: AsyncIterator[AgentEvent]
) -> AsyncIterator[AgentEvent]:
    for event in first:
        yield event
    async for event in rest:
        yield event


async def _load_pending_proposal(
    repo: ConversationRepository, *, conversation_id: UUID, user_id: UUID, tool_call_id: str
) -> dict[str, Any]:
    # row lock serializes concurrent confirms so has_tool_result below can't race
    call = await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id,
        for_update=True,
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
) -> StreamingResponse:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    if await repo.get(user_id=user_id, conversation_id=conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    call = await _load_pending_proposal(
        repo, conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    try:
        # savepoint: a handler DB error must not abort the transaction holding the row lock
        async with session.begin_nested():
            result = await dispatch(
                session, user_id=user_id,
                tool_call=ToolCall(
                    name=call["name"], arguments=json.loads(call["arguments"] or "{}"),
                    id=tool_call_id,
                ),
                pending_confirmation=True,
            )
    except Exception as exc:
        result = tool_result(f"Fehler: {exc}")
    if isinstance(result, Proposal):
        raise HTTPException(status_code=500, detail="unexpected_proposal_on_confirm")
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id,
    )
    await session.commit()
    return _event_stream(_prefixed(
        result_events(tool_call_id, call["name"], result),
        stream_continuation(session, user_id=user_id, conversation_id=conversation_id),
    ))


@router.post("/{conversation_id}/proposals/{tool_call_id}/reject")
async def reject_proposal(
    conversation_id: UUID,
    tool_call_id: str,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    if await repo.get(user_id=user_id, conversation_id=conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    call = await _load_pending_proposal(
        repo, conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    result = tool_result("Vom Nutzer abgelehnt.")
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id,
    )
    await session.commit()
    return _event_stream(_prefixed(
        result_events(tool_call_id, call["name"], result),
        stream_continuation(session, user_id=user_id, conversation_id=conversation_id),
    ))
