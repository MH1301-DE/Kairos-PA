from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import Proposal, ToolCall, dispatch
from kairos.agent.orchestrator import run_turn
from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.conversation import ConversationRepository

router = APIRouter(prefix="/api/agent/conversations", tags=["agent"])

_TITLE_MAX_LEN = 80


class CreateConversationRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str


class ConfirmRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


def _proposal_to_dict(p: Proposal) -> dict[str, Any]:
    return {"tool_name": p.tool_name, "arguments": p.arguments, "summary": p.summary}


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
    return {
        "messages": [
            {
                "id": str(m.id), "role": m.role, "content": m.content,
                "tool_calls": m.tool_calls, "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    }


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    req: SendMessageRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ConversationRepository(session=session)
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    if conversation.title is None:
        conversation.title = req.content[:_TITLE_MAX_LEN]

    result = await run_turn(
        session, user_id=user_id, conversation_id=conversation_id, user_message=req.content
    )
    await session.commit()
    return {
        "reply": result.reply_text,
        "proposal": _proposal_to_dict(result.proposal) if result.proposal else None,
        "remembered": result.remembered,
    }


@router.post("/{conversation_id}/confirm")
async def confirm_proposal(
    conversation_id: UUID,
    req: ConfirmRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    conv_repo = ConversationRepository(session=session)
    conversation = await conv_repo.get(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")

    # a fresh tool_call_id -- the Proposal's originating assistant tool_call was
    # already persisted (without a matching tool result) when run_turn() returned
    # early; this records the confirmed execution as its own well-formed
    # assistant/tool pair rather than threading the original id through
    tool_call_id = str(uuid.uuid4())
    tool_calls_data = [
        {"id": tool_call_id, "name": req.tool_name, "arguments": json.dumps(req.arguments)}
    ]
    await conv_repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=tool_calls_data,
    )

    try:
        result = await dispatch(
            session, user_id=user_id,
            tool_call=ToolCall(name=req.tool_name, arguments=req.arguments),
            pending_confirmation=True,
        )
    except Exception as exc:
        result = {"summary": f"Fehler: {exc}", "data": None, "meta": {}}

    if isinstance(result, Proposal):
        # confirm always executes -- dispatch only returns another Proposal if
        # the tool name doesn't actually require one, which would be a bug
        raise HTTPException(status_code=500, detail="unexpected_proposal_on_confirm")

    await conv_repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(result), tool_call_id=tool_call_id,
    )
    await session.commit()
    return result
