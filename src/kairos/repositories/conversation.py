from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import Conversation, ConversationMessage


class ConversationRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: UUID, title: str | None) -> Conversation:
        conversation = Conversation(id=uuid.uuid4(), user_id=user_id, title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def list_for_user(self, *, user_id: UUID) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, *, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def append_message(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        role: str,
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self._session.add(message)
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(updated_at=datetime.now(UTC))
        )
        await self._session.flush()
        return message

    async def list_messages(
        self, *, conversation_id: UUID, user_id: UUID, limit: int = 50
    ) -> list[ConversationMessage]:
        # most recent `limit` messages, returned oldest-first for feeding back into
        # the LLM -- this is the MVP's "simple context-window cutoff", no compaction
        result = await self._session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
            )
            .order_by(ConversationMessage.seq.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def list_messages_after(
        self, *, conversation_id: UUID, user_id: UUID, after_seq: int | None
    ) -> list[ConversationMessage]:
        stmt = select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.user_id == user_id,
        )
        if after_seq is not None:
            stmt = stmt.where(ConversationMessage.seq > after_seq)
        result = await self._session.execute(stmt.order_by(ConversationMessage.seq.asc()))
        return list(result.scalars().all())

    async def set_compacted_through(
        self, *, conversation_id: UUID, user_id: UUID, seq: int
    ) -> None:
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(compacted_through_seq=seq)
        )

    async def find_tool_call(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        tool_call_id: str,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        stmt = select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.user_id == user_id,
            ConversationMessage.role == "assistant",
            ConversationMessage.tool_calls.contains([{"id": tool_call_id}]),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
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

    async def latest_seq(self, *, conversation_id: UUID, user_id: UUID) -> int | None:
        result = await self._session.execute(
            select(func.max(ConversationMessage.seq)).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def first_user_seq_after(
        self, *, conversation_id: UUID, user_id: UUID, after_seq: int | None
    ) -> int | None:
        stmt = select(func.min(ConversationMessage.seq)).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.user_id == user_id,
            ConversationMessage.role == "user",
        )
        if after_seq is not None:
            stmt = stmt.where(ConversationMessage.seq > after_seq)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def last_assistant_reply(self, *, conversation_id: UUID, user_id: UUID) -> str | None:
        result = await self._session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
                ConversationMessage.role == "assistant",
                ConversationMessage.content.is_not(None),
            )
            .order_by(ConversationMessage.seq.desc())
            .limit(20)
        )
        # tool_calls may be JSON null rather than SQL NULL, so filter here
        return next((m.content for m in result.scalars() if not m.tool_calls), None)
