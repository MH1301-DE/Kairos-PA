from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session
from kairos.repositories.conversation import ConversationRepository
from kairos.scheduler import loop as loop_module

_BRIEFING = {
    "name": "Morgen-Briefing",
    "cron_exprs": ["0 8 * * *"],
    "timezone": "Europe/Berlin",
    "steps": [
        {"action": "garmin.sync", "params": {}},
        {"action": "calendar.sync", "params": {}},
        {"action": "agent.prompt", "params": {"prompt": "Was gibt es Neues?"}},
    ],
}


async def _insert_user(session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'Europe/Vienna', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    return user_id


@pytest_asyncio.fixture
async def client_for(
    session: AsyncSession, app_db_url: str, run_migrations: None
) -> AsyncIterator[Callable[[uuid.UUID], Any]]:
    # least-privilege role: RLS is enforced like in production
    del run_migrations, session
    engine = create_async_engine(app_db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _client(user_id: uuid.UUID) -> AsyncIterator[AsyncClient]:
        app.dependency_overrides[current_user] = lambda: {"user_id": str(user_id)}

        async def _session() -> AsyncIterator[AsyncSession]:
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                yield c
        finally:
            app.dependency_overrides.clear()

    yield _client
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/scheduler/jobs")).status_code == 401


@pytest.mark.asyncio
async def test_actions_expose_schemas(session: AsyncSession, client_for: Any) -> None:
    async with client_for(await _insert_user(session)) as c:
        body = (await c.get("/api/scheduler/actions")).json()
    by_name = {a["name"]: a for a in body["actions"]}
    assert set(by_name) == {"garmin.sync", "calendar.sync", "metrics.recompute", "agent.prompt"}
    assert by_name["agent.prompt"]["schema"]["properties"]["prompt"]["maxLength"] == 2000
    assert by_name["garmin.sync"]["min_interval_s"] == 3600
    assert body["default_timezone"] == "Europe/Vienna"


@pytest.mark.asyncio
async def test_preview_lists_next_runs_or_errors(session: AsyncSession, client_for: Any) -> None:
    async with client_for(await _insert_user(session)) as c:
        ok = (
            await c.post(
                "/api/scheduler/preview",
                json={"cron_exprs": ["0 8-20/2 * * *"], "timezone": "Europe/Berlin"},
            )
        ).json()
        bad = (
            await c.post(
                "/api/scheduler/preview",
                json={"cron_exprs": ["*/45 * * * *"], "timezone": "Europe/Berlin"},
            )
        ).json()
    assert ok["label"] == "Alle 2 Stunden, 08–20 Uhr"
    assert len(ok["next"]) == 5 and ok["errors"] == []
    assert bad["next"] == [] and "Teilern von 60" in bad["errors"][0]


@pytest.mark.asyncio
async def test_create_read_update_toggle_delete(session: AsyncSession, client_for: Any) -> None:
    async with client_for(await _insert_user(session)) as c:
        created = await c.post("/api/scheduler/jobs", json={**_BRIEFING, "timezone": None})
        assert created.status_code == 201, created.text
        job = created.json()
        # new jobs take the user's home time zone
        assert job["timezone"] == "Europe/Vienna"
        assert job["label"] == "Täglich 08:00" and job["next_run_at"] is not None
        assert job["steps"][2]["params"] == {"prompt": "Was gibt es Neues?"}
        assert job["steps"][0]["params"] == {"kinds": None}

        listed = (await c.get("/api/scheduler/jobs")).json()["jobs"]
        assert [j["steps"] for j in listed] == [["garmin.sync", "calendar.sync", "agent.prompt"]]

        replaced = await c.put(
            f"/api/scheduler/jobs/{job['id']}",
            json={
                **_BRIEFING,
                "name": "Wochenanalyse",
                "cron_exprs": ["0 18 * * 0"],
            },
        )
        assert replaced.json()["label"] == "Sonntags 18:00"

        off = (await c.patch(f"/api/scheduler/jobs/{job['id']}", json={"enabled": False})).json()
        assert off["enabled"] is False and off["next_run_at"] is None
        on = (await c.patch(f"/api/scheduler/jobs/{job['id']}", json={"enabled": True})).json()
        assert on["next_run_at"] is not None

        assert (await c.delete(f"/api/scheduler/jobs/{job['id']}")).status_code == 204
        assert (await c.get(f"/api/scheduler/jobs/{job['id']}")).status_code == 404


@pytest.mark.parametrize(
    ("patch_body", "field", "fragment"),
    [
        ({"name": " "}, "name", "1 bis 80"),
        ({"cron_exprs": ["0 8 1 * *"]}, "cron_exprs", "Tag und Monat"),
        ({"timezone": "Mars/Base"}, "timezone", "Unbekannte Zeitzone"),
        ({"cron_exprs": ["*/30 * * * *"]}, "cron_exprs", "mindestens 60 min"),
        ({"cron_exprs": ["0 8 * * *", "5 8 * * *"]}, "cron_exprs", "der Zeitplan hat 5 min"),
        ({"steps": []}, "steps", "1 bis 8"),
        (
            {"steps": [{"action": "agent.prompt", "params": {"prompt": "a"}}] * 2},
            "steps",
            "Höchstens ein Agent-Schritt",
        ),
        ({"steps": [{"action": "shell.exec", "params": {}}]}, "steps.0.action", "Unbekannte"),
        (
            {"steps": [{"action": "calendar.sync", "params": {"calendar": "caldav"}}]},
            "steps.0.params.calendar",
            "noch nicht verfügbar",
        ),
        (
            {"steps": [{"action": "agent.prompt", "params": {"prompt": "x" * 2001}}]},
            "steps.0.params.prompt",
            "Höchstens 2000 Zeichen",
        ),
        (
            {"steps": [{"action": "metrics.recompute", "params": {"days": 0}}]},
            "steps.0.params.days",
            "Mindestens 1",
        ),
        ({"context_reset_every": 31}, "context_reset_every", "0 (nie) und 30"),
    ],
)
@pytest.mark.asyncio
async def test_validation_errors_are_per_field_and_german(
    session: AsyncSession, client_for: Any, patch_body: dict[str, Any], field: str, fragment: str
) -> None:
    async with client_for(await _insert_user(session)) as c:
        resp = await c.post("/api/scheduler/jobs", json={**_BRIEFING, **patch_body})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert fragment in errors[field], errors


@pytest.mark.asyncio
async def test_at_most_ten_jobs(session: AsyncSession, client_for: Any) -> None:
    simple = {**_BRIEFING, "steps": [{"action": "metrics.recompute", "params": {}}]}
    async with client_for(await _insert_user(session)) as c:
        for _ in range(10):
            assert (await c.post("/api/scheduler/jobs", json=simple)).status_code == 201
        resp = await c.post("/api/scheduler/jobs", json=simple)
    assert resp.status_code == 422
    assert "Höchstens 10" in resp.json()["detail"]["errors"]["jobs"]


@pytest.mark.asyncio
async def test_user_a_does_not_see_user_b_jobs(session: AsyncSession, client_for: Any) -> None:
    user_a, user_b = await _insert_user(session), await _insert_user(session)
    async with client_for(user_b) as c:
        job_id = (await c.post("/api/scheduler/jobs", json=_BRIEFING)).json()["id"]
    async with client_for(user_a) as c:
        assert (await c.get("/api/scheduler/jobs")).json()["jobs"] == []
        assert (await c.get(f"/api/scheduler/jobs/{job_id}")).status_code == 404
        assert (await c.delete(f"/api/scheduler/jobs/{job_id}")).status_code == 404
        assert (await c.post(f"/api/scheduler/jobs/{job_id}/run")).status_code == 404
        assert (await c.get(f"/api/scheduler/jobs/{job_id}/runs")).status_code == 404


@pytest.mark.asyncio
async def test_running_job_refuses_delete_and_second_run(
    session: AsyncSession, client_for: Any
) -> None:
    user_id = await _insert_user(session)
    async with client_for(user_id) as c:
        job_id = (await c.post("/api/scheduler/jobs", json=_BRIEFING)).json()["id"]
        await session.execute(
            text("UPDATE scheduled_job SET running_since = now() WHERE id = :j"), {"j": job_id}
        )
        await session.commit()
        assert (await c.delete(f"/api/scheduler/jobs/{job_id}")).json()["detail"] == "job_running"
        fake = AsyncMock(return_value=None)
        with patch.object(loop_module.SchedulerLoop, "run_now", fake):
            resp = await c.post(f"/api/scheduler/jobs/{job_id}/run")
        assert (resp.status_code, resp.json()["detail"]) == (409, "job_running")
        status = (await c.get("/api/scheduler/jobs")).json()["jobs"][0]
        assert status["running"] is True


@pytest.mark.asyncio
async def test_run_now_returns_202_with_run_id(session: AsyncSession, client_for: Any) -> None:
    user_id = await _insert_user(session)
    run_id = uuid.uuid4()
    async with client_for(user_id) as c:
        job_id = (await c.post("/api/scheduler/jobs", json=_BRIEFING)).json()["id"]
        with patch.object(loop_module.SchedulerLoop, "run_now", AsyncMock(return_value=run_id)):
            resp = await c.post(f"/api/scheduler/jobs/{job_id}/run")
    assert resp.status_code == 202 and resp.json() == {"run_id": str(run_id)}


@pytest.mark.asyncio
async def test_status_counts_failed_jobs_and_runs_are_listed(
    session: AsyncSession, client_for: Any
) -> None:
    user_id = await _insert_user(session)
    async with client_for(user_id) as c:
        job_id = (await c.post("/api/scheduler/jobs", json=_BRIEFING)).json()["id"]
        await session.execute(
            text("UPDATE scheduled_job SET last_status = 'failed' WHERE id = :j;"),
            {"j": job_id},
        )
        await session.execute(
            text(
                "INSERT INTO scheduled_job_run"
                " (id, job_id, user_id, trigger, started_at, status, steps) VALUES"
                " (gen_random_uuid(), :j, :u, 'manual', now(), 'ok', CAST(:s AS jsonb))"
            ),
            {
                "j": job_id,
                "u": str(user_id),
                "s": '[{"action": "agent.prompt", "status": "ok",'
                ' "data": {"proposal_open": true}}]',
            },
        )
        await session.commit()
        assert (await c.get("/api/scheduler/status")).json() == {"failed_jobs": 1}
        runs = (await c.get(f"/api/scheduler/jobs/{job_id}/runs?limit=5")).json()["runs"]
        listed = (await c.get("/api/scheduler/jobs")).json()["jobs"][0]
    assert runs[0]["trigger"] == "manual" and runs[0]["status"] == "ok"
    assert listed["proposal_open"] is True and listed["last_run_at"] is not None


@pytest.mark.asyncio
async def test_messages_carry_seq_and_reset_boundary_and_list_marks_job_chats(
    session: AsyncSession, client_for: Any
) -> None:
    user_id = await _insert_user(session)
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="Scheduler: Morgen-Briefing")
    first = await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="user", content="alt"
    )
    await repo.set_compacted_through(
        conversation_id=conversation.id, user_id=user_id, seq=first.seq
    )
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="user", content="neu"
    )
    await session.commit()
    async with client_for(user_id) as c:
        job = (await c.post("/api/scheduler/jobs", json=_BRIEFING)).json()
        await session.execute(
            text("UPDATE scheduled_job SET conversation_id = :c WHERE id = :j"),
            {"c": str(conversation.id), "j": job["id"]},
        )
        await session.commit()
        body = (await c.get(f"/api/agent/conversations/{conversation.id}/messages")).json()
        listed = (await c.get("/api/agent/conversations")).json()["conversations"]
    assert body["compacted_through_seq"] == first.seq
    assert [m["seq"] for m in body["messages"]][0] == first.seq
    assert listed[0]["scheduled_job_id"] == job["id"]
