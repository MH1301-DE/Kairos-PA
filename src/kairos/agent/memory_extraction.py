from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.expiry import _parse_expiry
from kairos.agent.history import HISTORY_BUDGET_TOKENS, split_turns, window_turns
from kairos.agent.llm_client import get_completion
from kairos.db.models import AgentMemory
from kairos.repositories.conversation import ConversationRepository
from kairos.repositories.memory import SqlMemoryRepository

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Du extrahierst aus einem Gesprächsausschnitt Fakten über den Nutzer, die in künftigen \
Gesprächen wichtig sind (Ziele, Verletzungen, Vorlieben, Lebensumstände, Absprachen). \
Keine Messwerte, keine Smalltalk-Inhalte, nichts, was schon in BEREITS GESPEICHERT steht. \
Zeitlich begrenzte Fakten bekommen expires_at (ISO-Datum), stabile Fakten null. \
Antworte ausschließlich mit einem JSON-Array [{"content": str, "expires_at": str|null}], \
leer wenn nichts Neues."""

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_items(raw: str | None) -> list[tuple[str, datetime | None]]:
    text = (raw or "").strip()
    if (fenced := _FENCE.match(text)) is not None:
        text = fenced.group(1)
    data: Any = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Extraktion muss ein JSON-Array liefern")
    items: list[tuple[str, datetime | None]] = []
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("content"), str):
            raise ValueError("Ungültiger Eintrag in der Extraktion")
        expiry = entry.get("expires_at")
        items.append((entry["content"], _parse_expiry(expiry) if expiry else None))
    return items


async def compact_conversation(
    session: AsyncSession, *, user_id: UUID, conversation_id: UUID, now: datetime
) -> list[AgentMemory]:
    conv_repo = ConversationRepository(session=session)
    conversation = await conv_repo.get(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        return []
    messages = await conv_repo.list_messages_after(
        conversation_id=conversation_id, user_id=user_id,
        after_seq=conversation.compacted_through_seq,
    )
    _, evicted = window_turns(split_turns(messages), HISTORY_BUDGET_TOKENS)
    if not evicted:
        return []

    memory_repo = SqlMemoryRepository(session=session)
    transcript = "\n".join(
        f"{m.role}: {m.content}"
        for turn in evicted for m in turn
        if m.role in ("user", "assistant") and m.content
    )
    active = await memory_repo.list_active(user_id=user_id, now=now)
    stored = "\n".join(f"- {m.content}" for m in active) or "(nichts)"
    try:
        response = await get_completion(
            session, user_id=user_id,
            messages=[
                {"role": "system", "content": _EXTRACTION_PROMPT},
                {
                    "role": "user",
                    "content": f"BEREITS GESPEICHERT:\n{stored}\n\nGESPRÄCH:\n{transcript}",
                },
            ],
            tools=None,
        )
        items = _parse_items(response.choices[0].message.content)
    except Exception:
        logger.warning(
            "Memory extraction failed for conversation %s", conversation_id, exc_info=True
        )
        return []

    created = [
        await memory_repo.create(
            user_id=user_id, content=content, source="agent", expires_at=expires_at
        )
        for content, expires_at in items
    ]
    await conv_repo.set_compacted_through(
        conversation_id=conversation_id, user_id=user_id, seq=evicted[-1][-1].seq
    )
    await session.commit()
    return created
