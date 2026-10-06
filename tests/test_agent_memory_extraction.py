from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent import memory_extraction
from kairos.agent.memory_extraction import compact_conversation
from kairos.repositories.conversation import ConversationRepository

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _fake_response(content: str | None):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def _new_conversation(session: AsyncSession) -> tuple[UUID, UUID]:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="Test")
    await session.commit()
    return user_id, conversation.id


async def _long_conversation(session: AsyncSession) -> tuple[UUID, UUID]:
    user_id, conversation_id = await _new_conversation(session)
    repo = ConversationRepository(session=session)
    for i in range(6):
        await repo.append_message(
            conversation_id=conversation_id, user_id=user_id,
            role="user", content=f"Frage {i} " + "w" * 12_000,
        )
        await repo.append_message(
            conversation_id=conversation_id, user_id=user_id,
            role="assistant", content="Antwort",
        )
    await session.commit()
    return user_id, conversation_id


@pytest.mark.asyncio
async def test_evicted_turns_become_memories_and_compaction_advances(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _long_conversation(session)
    repo = ConversationRepository(session=session)
    llm = AsyncMock(return_value=_fake_response(
        '[{"content": "Läuft gern morgens", "expires_at": null},'
        ' {"content": "Erkältet", "expires_at": "2026-10-08"}]'
    ))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        )
    assert [m.content for m in created] == ["Läuft gern morgens", "Erkältet"]
    assert created[1].expires_at == datetime(2026, 10, 8, 23, 59, 59, tzinfo=UTC)
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    assert conversation is not None and conversation.compacted_through_seq is not None
    llm_input = llm.call_args.kwargs["messages"][-1]["content"]
    assert "Frage 2" in llm_input and "Frage 5" not in llm_input


@pytest.mark.asyncio
async def test_failed_extraction_creates_nothing_and_does_not_advance(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _long_conversation(session)
    repo = ConversationRepository(session=session)
    llm = AsyncMock(return_value=_fake_response("das ist kein JSON"))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        )
    assert created == []
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    assert conversation is not None and conversation.compacted_through_seq is None


@pytest.mark.asyncio
async def test_nothing_to_compact_makes_no_llm_call(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    repo = ConversationRepository(session=session)
    for content in ("Hallo", "Wie geht's?"):
        await repo.append_message(
            conversation_id=conversation_id, user_id=user_id, role="user", content=content
        )
    await session.commit()
    llm = AsyncMock()
    with patch.object(memory_extraction, "get_completion", new=llm):
        assert await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        ) == []
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_llm_exception_creates_nothing_and_does_not_advance(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _long_conversation(session)
    repo = ConversationRepository(session=session)
    llm = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        )
    assert created == []
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    assert conversation is not None and conversation.compacted_through_seq is None


@pytest.mark.asyncio
async def test_invalid_items_are_skipped_and_compaction_still_advances(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _long_conversation(session)
    repo = ConversationRepository(session=session)
    llm = AsyncMock(return_value=_fake_response(
        '[{"content": "Läuft gern morgens", "expires_at": null},'
        ' {"content": "Erkältet", "expires_at": "nächste Woche"},'
        ' "kein Objekt", {"expires_at": null},'
        ' {"content": "Ziel: Halbmarathon", "expires_at": "2026-12-01"}]'
    ))
    with patch.object(memory_extraction, "get_completion", new=llm):
        created = await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        )
    assert [m.content for m in created] == ["Läuft gern morgens", "Ziel: Halbmarathon"]
    conversation = await repo.get(user_id=user_id, conversation_id=conversation_id)
    assert conversation is not None and conversation.compacted_through_seq is not None


@pytest.mark.asyncio
async def test_extraction_transcript_is_capped_to_the_most_recent_part(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    repo = ConversationRepository(session=session)
    for i in range(12):
        await repo.append_message(
            conversation_id=conversation_id, user_id=user_id,
            role="user", content=f"Frage {i} " + "w" * 12_000,
        )
    await session.commit()
    llm = AsyncMock(return_value=_fake_response("[]"))
    with patch.object(memory_extraction, "get_completion", new=llm):
        await compact_conversation(
            session, user_id=user_id, conversation_id=conversation_id, now=_NOW
        )
    llm_input = llm.call_args.kwargs["messages"][-1]["content"]
    transcript = llm_input.split("GESPRÄCH:\n", 1)[1]
    assert len(transcript) <= memory_extraction.TRANSCRIPT_MAX_CHARS
    assert "Frage 0" not in transcript and "Frage 8" in transcript


def test_extraction_prompt_only_trusts_user_lines() -> None:
    prompt = memory_extraction._EXTRACTION_PROMPT
    assert "ausschließlich aus Aussagen des Nutzers" in prompt
    assert "assistant:" in prompt
