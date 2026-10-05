from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import openai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import Proposal, ToolCall, dispatch, needs_confirmation
from kairos.agent.llm_client import NoLlmCredentialConfigured
from kairos.agent.orchestrator import run_turn, tool_result
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


def _proposal_to_dict(p: Proposal) -> dict[str, Any]:
    return {
        "tool_name": p.tool_name, "arguments": p.arguments, "summary": p.summary,
        "tool_call_id": p.tool_call_id,
    }


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

    try:
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message=req.content
        )
    except NoLlmCredentialConfigured as exc:
        raise HTTPException(status_code=503, detail="no_llm_provider_configured") from exc
    except openai.OpenAIError as exc:
        # litellm normalizes every provider's errors onto the openai.* hierarchy
        # (AuthenticationError, RateLimitError, APIConnectionError, ...) -- a
        # wrong/expired key or an upstream outage must not surface as a raw 500
        logger.warning("LLM call failed for user %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="llm_provider_error") from exc
    await session.commit()
    return {
        "reply": result.reply_text,
        "proposal": _proposal_to_dict(result.proposal) if result.proposal else None,
        "remembered": result.remembered,
    }


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
        content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id,
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
        content=json.dumps(tool_result("Vom Nutzer abgelehnt."), ensure_ascii=False),
        tool_call_id=tool_call_id,
    )
    await session.commit()
    return {"rejected": True}
