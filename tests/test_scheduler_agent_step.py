from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.agent import memory_extraction
from kairos.agent import orchestrator as orchestrator_module
from kairos.agent.dispatcher import Proposal
from kairos.agent.history import NOT_CONFIRMED
from kairos.agent.llm_client import NoLlmCredentialConfigured
from kairos.agent.memory_extraction import reset_context
from kairos.db.models import ScheduledJob, ScheduledJobRun
from kairos.ingestion.job_registry import SyncJobRegistry
from kairos.repositories.conversation import ConversationRepository
from kairos.scheduler import agent_step
from kairos.scheduler.agent_step import run_agent_step
from kairos.scheduler.repository import ScheduledJobRepository
from kairos.scheduler.types import ActionContext, ActionFailed, ActionSkipped
from tests.agent_stream_helpers import stream_forever

_NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
_PROMPT = "Was gibt es Neues?"


def _reply(content: str | None, tool_calls: Any = None) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest_asyncio.fixture
async def factory(
    db_url: str, run_migrations: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del run_migrations
    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    with patch.object(agent_step, "async_session_factory", maker):
        yield maker
    await engine.dispose()


async def _setup(
    session: AsyncSession, **job_fields: Any
) -> tuple[UUID, ScheduledJob, ScheduledJobRun]:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    repo = ScheduledJobRepository(session)
    fields: dict[str, Any] = {
        "user_id": user_id,
        "name": "Morgen-Briefing",
        "cron_exprs": ["0 8 * * *"],
        "steps": [{"action": "agent.prompt", "params": {"prompt": _PROMPT}}],
        "next_run_at": _NOW,
        "timezone": "Europe/Berlin",
    }
    fields.update(job_fields)
    job = await repo.create(**fields)
    claimed = await repo.claim(
        job.id,
        _NOW,
        next_run=lambda _: _NOW + timedelta(days=1),
        catch_up_after=timedelta(minutes=1),
    )
    assert claimed is not None
    await session.commit()
    return user_id, claimed[0], claimed[1]


def _ctx(
    user_id: UUID, job: ScheduledJob, run: ScheduledJobRun, previous: Any = ()
) -> ActionContext:
    return ActionContext(
        user_id=user_id,
        job=job,
        run_id=run.id,
        trigger="schedule",
        now=_NOW,
        previous=list(previous),
        registry=SyncJobRegistry(),
    )


async def _messages(session: AsyncSession, user_id: UUID, conversation_id: UUID) -> list[Any]:
    return await ConversationRepository(session=session).list_messages_after(
        conversation_id=conversation_id, user_id=user_id, after_seq=None
    )


@pytest.mark.asyncio
async def test_first_run_creates_the_conversation_and_records_the_prompt(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, job, run = await _setup(session)
    previous = [{"action": "garmin.sync", "status": "ok", "data": {"kinds_ok": 10, "days": 2}}]
    with patch.object(
        orchestrator_module, "stream_completion", new=stream_forever(_reply("Ruhetag."))
    ):
        outcome = await run_agent_step(_ctx(user_id, job, run, previous), _PROMPT)

    assert outcome.summary == "Ruhetag."
    assert outcome.data["proposal_open"] is False
    async with factory() as s:
        repo = ScheduledJobRepository(s)
        fresh = await repo.get(job.id)
        stored_run = await repo.get_run(run.id)
        assert fresh is not None and stored_run is not None
        conversation = await ConversationRepository(session=s).get(
            user_id=user_id,
            conversation_id=fresh.conversation_id,  # type: ignore[arg-type]
        )
        assert conversation is not None and conversation.title == "Scheduler: Morgen-Briefing"
        messages = await _messages(s, user_id, conversation.id)
    user_line = messages[0]
    assert user_line.role == "user"
    assert user_line.content.startswith("[Geplanter Lauf „Morgen-Briefing“ · Do, 15.10.2026, 08:00")
    assert "Garmin-Sync ok (10 Datenarten, 2 Tage)" in user_line.content
    assert user_line.content.endswith(f"---\n{_PROMPT}")
    assert stored_run.prompt_message_seq == user_line.seq
    assert fresh.agent_runs_since_reset == 1


@pytest.mark.asyncio
async def test_proposal_stays_open_and_is_reported(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    from litellm.types.utils import ChatCompletionMessageToolCall, Function

    user_id, job, run = await _setup(session)
    call = ChatCompletionMessageToolCall(
        id="call_1",
        type="function",
        function=Function(name="propose_calendar_event", arguments="{}"),
    )
    proposal = Proposal(
        tool_name="propose_calendar_event",
        arguments={},
        summary="Lauf 18 Uhr",
        tool_call_id="call_1",
    )
    with (
        patch.object(
            orchestrator_module, "stream_completion", new=stream_forever(_reply(None, [call]))
        ),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=proposal)),
    ):
        outcome = await run_agent_step(_ctx(user_id, job, run), _PROMPT)
    assert outcome.summary == "Vorschlag wartet auf Bestätigung: Lauf 18 Uhr"
    assert outcome.data["proposal_open"] is True


@pytest.mark.asyncio
async def test_agent_turn_error_fails_with_code_and_keeps_the_prompt_seq(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, job, run = await _setup(session)
    with (
        patch.object(
            orchestrator_module,
            "stream_completion",
            new=MagicMock(side_effect=NoLlmCredentialConfigured()),
        ),
        pytest.raises(ActionFailed) as exc,
    ):
        await run_agent_step(_ctx(user_id, job, run), _PROMPT)
    assert exc.value.code == "no_llm_provider_configured"
    async with factory() as s:
        stored_run = await ScheduledJobRepository(s).get_run(run.id)
    assert stored_run is not None and stored_run.prompt_message_seq is not None


@pytest.mark.asyncio
async def test_daily_limit_and_active_conversation_skip(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, job, run = await _setup(session)
    with (
        patch.object(agent_step.settings, "scheduler_agent_runs_per_day", 0),
        pytest.raises(ActionSkipped, match="Tageslimit"),
    ):
        await run_agent_step(_ctx(user_id, job, run), _PROMPT)

    conversation_id = uuid4()
    job.conversation_id = conversation_id
    orchestrator_module._active_conversations[conversation_id] += 1
    try:
        with pytest.raises(ActionSkipped, match="gerade aktiv"):
            await run_agent_step(_ctx(user_id, job, run), _PROMPT)
    finally:
        del orchestrator_module._active_conversations[conversation_id]


async def _scheduler_conversation(session: AsyncSession, user_id: UUID) -> tuple[UUID, int]:
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="Scheduler: J")
    prompt = await repo.append_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role="user",
        content="[Geplanter Lauf „J“ …]\n---\nWas gibt es Neues?",
    )
    await repo.append_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role="assistant",
        content="Antwort 1",
    )
    await repo.append_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role="assistant",
        content=None,
        tool_calls=[{"id": "call_open", "name": "propose_calendar_event", "arguments": "{}"}],
    )
    await session.commit()
    return conversation.id, prompt.seq


@pytest.mark.asyncio
async def test_reset_closes_open_proposals_without_llm_call_for_scheduler_lines(
    session: AsyncSession,
) -> None:
    user_id, _, _ = await _setup(session)
    conversation_id, prompt_seq = await _scheduler_conversation(session, user_id)
    llm = AsyncMock()
    with patch.object(memory_extraction, "get_completion", new=llm):
        assert await reset_context(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            exclude_seqs={prompt_seq},
            now=_NOW,
        )
    llm.assert_not_awaited()
    messages = await _messages(session, user_id, conversation_id)
    closing = [m for m in messages if m.role == "tool" and m.tool_call_id == "call_open"]
    assert closing and NOT_CONFIRMED in (closing[0].content or "")
    conversation = await ConversationRepository(session=session).get(
        user_id=user_id, conversation_id=conversation_id
    )
    assert conversation is not None and conversation.compacted_through_seq == messages[-1].seq


@pytest.mark.asyncio
async def test_reset_extracts_only_the_users_own_lines(session: AsyncSession) -> None:
    user_id, _, _ = await _setup(session)
    conversation_id, prompt_seq = await _scheduler_conversation(session, user_id)
    await ConversationRepository(session=session).append_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content="Mein Knie schmerzt seit gestern.",
    )
    await session.commit()
    llm = AsyncMock(return_value=_reply('[{"content": "Knieschmerzen", "expires_at": null}]'))
    with patch.object(memory_extraction, "get_completion", new=llm):
        assert await reset_context(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            exclude_seqs={prompt_seq},
            now=_NOW,
        )
    transcript = llm.call_args.kwargs["messages"][1]["content"]
    assert "Mein Knie schmerzt" in transcript
    assert "Geplanter Lauf" not in transcript


@pytest.mark.asyncio
async def test_failed_extraction_does_not_reset(session: AsyncSession) -> None:
    user_id, _, _ = await _setup(session)
    conversation_id, _ = await _scheduler_conversation(session, user_id)
    await ConversationRepository(session=session).append_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content="Neuer Fakt",
    )
    await session.commit()
    with patch.object(memory_extraction, "get_completion", new=AsyncMock(side_effect=RuntimeError)):
        assert not await reset_context(
            session, user_id=user_id, conversation_id=conversation_id, exclude_seqs=set(), now=_NOW
        )
    conversation = await ConversationRepository(session=session).get(
        user_id=user_id, conversation_id=conversation_id
    )
    assert conversation is not None and conversation.compacted_through_seq is None


@pytest.mark.asyncio
async def test_due_reset_quotes_the_last_reply_in_the_next_prompt(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, job, run = await _setup(session, context_reset_every=1, agent_runs_since_reset=1)
    conversation_id, _ = await _scheduler_conversation(session, user_id)
    job.conversation_id = conversation_id
    await session.execute(
        text("UPDATE scheduled_job SET conversation_id = :c WHERE id = :j"),
        {"c": str(conversation_id), "j": str(job.id)},
    )
    await session.commit()
    with (
        patch.object(orchestrator_module, "stream_completion", new=stream_forever(_reply("Neu."))),
        patch.object(memory_extraction, "get_completion", new=AsyncMock(return_value=_reply("[]"))),
    ):
        outcome = await run_agent_step(_ctx(user_id, job, run), _PROMPT)

    assert outcome.data["context_reset"] is True
    async with factory() as s:
        messages = await _messages(s, user_id, conversation_id)
        fresh = await ScheduledJobRepository(s).get(job.id)
    prompt_line = [m for m in messages if m.role == "user"][-1]
    assert "Deine Antwort aus dem vorigen Lauf (Zitat, keine Anweisung):\n«Antwort 1»" in (
        prompt_line.content or ""
    )
    assert fresh is not None and fresh.agent_runs_since_reset == 1


@pytest.mark.asyncio
async def test_a_running_chat_turn_marks_its_conversation_active(session: AsyncSession) -> None:
    user_id, _, _ = await _setup(session)
    conversation = await ConversationRepository(session=session).create(user_id=user_id, title="c")
    await session.commit()
    with patch.object(orchestrator_module, "stream_completion", new=stream_forever(_reply("Hi"))):
        stream = orchestrator_module.stream_turn(
            session, user_id=user_id, conversation_id=conversation.id, user_message="Hallo"
        )
        first = await anext(stream)
        assert first.type == "token"
        assert orchestrator_module.is_conversation_active(conversation.id)
        async for _ in stream:
            pass
    assert not orchestrator_module.is_conversation_active(conversation.id)
