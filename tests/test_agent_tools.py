from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.tools import (
    CORE_TOOLS,
    TOOLS_BY_NAME,
    analyze_records_handler,
    delete_calendar_event_handler,
    propose_calendar_event_handler,
    query_calendar_handler,
    query_health_handler,
    recall_handler,
    remember_handler,
    render_handler,
)
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.memory import SqlMemoryRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


def test_core_tools_have_the_expected_risk_classes() -> None:
    risk_by_name = {t.name: (t.risk_class, t.requires_confirmation) for t in CORE_TOOLS}
    assert risk_by_name["query_health"] == ("read", False)
    assert risk_by_name["analyze_records"] == ("read", False)
    assert risk_by_name["query_calendar"] == ("read", False)
    assert risk_by_name["recall"] == ("read", False)
    assert risk_by_name["render"] == ("read", False)
    # remember is write-class but does NOT require confirmation -- the one
    # documented exception (design spec Scope-Entscheidung 4)
    assert risk_by_name["remember"] == ("write", False)
    assert risk_by_name["propose_calendar_event"] == ("write", True)
    assert risk_by_name["delete_calendar_event"] == ("destructive", True)
    assert risk_by_name["plan_propose"] == ("read", False)
    assert risk_by_name["plan_commit"] == ("write", True)
    assert risk_by_name["plan_adjust"] == ("write", True)
    assert risk_by_name["plan_progress"] == ("read", False)
    assert risk_by_name["activity_search"] == ("read", False)
    assert risk_by_name["activity_get"] == ("read", False)
    assert risk_by_name["activity_splits"] == ("read", False)
    assert risk_by_name["activity_analyze"] == ("read", False)
    assert len(CORE_TOOLS) == 16
    assert set(TOOLS_BY_NAME) == {t.name for t in CORE_TOOLS}


@pytest.mark.asyncio
async def test_query_health_handler_raises_on_unknown_metric(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Unknown metric_id"):
        await query_health_handler(session, user_id=uuid4(), metric_id="not_a_real_metric")


@pytest.mark.asyncio
async def test_query_health_handler_reports_insufficient_data(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await query_health_handler(session, user_id=user_id, metric_id="training_load")
    assert result["data"]["confidence"] == "insufficient_data"
    assert "training_load" in result["summary"]


@pytest.mark.asyncio
async def test_analyze_records_handler_computes_stats(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    today = date.today()
    for i, value in enumerate((10.0, 20.0, 30.0)):
        await session.execute(
            text(
                "INSERT INTO metric_daily_value (user_id, metric_id, variant_id, day, value, "
                "confidence) VALUES (:uid, 'trimp', 'edwards', :day, :val, 'high')"
            ),
            {"uid": str(user_id), "day": today - timedelta(days=2 - i), "val": value},
        )
    await session.commit()

    result = await analyze_records_handler(
        session, user_id=user_id, metric_id="trimp", variant="edwards"
    )
    assert result["data"]["mean"] == pytest.approx(20.0)
    assert result["data"]["min"] == pytest.approx(10.0)
    assert result["data"]["max"] == pytest.approx(30.0)
    assert result["data"]["trend_slope"] > 0  # rising series


@pytest.mark.asyncio
async def test_analyze_records_handler_defaults_trimp_to_edwards(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    today = date.today()
    for variant, value in (("edwards", 50.0), ("banister", None)):
        await session.execute(
            text(
                "INSERT INTO metric_daily_value (user_id, metric_id, variant_id, day, value, "
                "confidence) VALUES (:uid, 'trimp', :variant, :day, :val, 'high')"
            ),
            {"uid": str(user_id), "variant": variant, "day": today, "val": value},
        )
    await session.commit()

    result = await analyze_records_handler(session, user_id=user_id, metric_id="trimp")
    assert result["data"]["mean"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_analyze_records_handler_handles_empty_series(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await analyze_records_handler(session, user_id=user_id, metric_id="trimp")
    assert result["data"]["mean"] is None
    assert result["meta"]["coverage"] == "0/28 Tage"


@pytest.mark.asyncio
async def test_query_calendar_handler_lists_events(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = CalendarEventRepository(session)
    await repo.upsert_kairos_event(
        user_id, "google_calendar", "evt-1", "Long Run",
        datetime(2026, 8, 1, 9, 0, tzinfo=UTC), datetime(2026, 8, 1, 10, 0, tzinfo=UTC), None,
    )
    await session.commit()

    result = await query_calendar_handler(
        session, user_id=user_id, from_date="2026-08-01", to_date="2026-08-02"
    )
    assert len(result["data"]) == 1
    assert result["data"][0]["summary"] == "Long Run"


@pytest.mark.asyncio
async def test_query_calendar_handler_with_duration_returns_free_blocks(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await query_calendar_handler(
        session, user_id=user_id, from_date="2026-08-01", to_date="2026-08-02",
        duration_minutes=60,
    )
    assert "free_blocks" in result["data"]
    assert len(result["data"]["free_blocks"]) > 0


@pytest.mark.asyncio
async def test_remember_handler_persists_with_agent_source(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await remember_handler(session, user_id=user_id, content="läuft ungern vor 7 Uhr")
    assert result["data"]["source"] == "agent"

    recalled = await recall_handler(session, user_id=user_id)
    assert recalled["data"][0]["content"] == "läuft ungern vor 7 Uhr"
    assert recalled["data"][0]["source"] == "agent"


@pytest.mark.asyncio
async def test_remember_handler_stores_expiry(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await remember_handler(
        session, user_id=user_id, content="Stress", expires_at="2026-10-11"
    )
    expected = datetime(2026, 10, 11, 23, 59, 59, tzinfo=UTC)
    assert result["data"]["expires_at"] == expected.isoformat()
    entry = (await SqlMemoryRepository(session=session).list_for_user(user_id=user_id))[0]
    assert entry.expires_at == expected


@pytest.mark.asyncio
async def test_remember_handler_rejects_bad_expiry(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="expires_at"):
        await remember_handler(
            session, user_id=uuid4(), content="x", expires_at="nächste Woche"
        )


@pytest.mark.asyncio
async def test_recall_handler_skips_expired(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    await remember_handler(session, user_id=user_id, content="alt", expires_at="2020-01-01")
    await remember_handler(session, user_id=user_id, content="aktuell")

    result = await recall_handler(session, user_id=user_id)
    assert [e["content"] for e in result["data"]] == ["aktuell"]


@pytest.mark.asyncio
async def test_recall_handler_filters_by_query(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    await remember_handler(session, user_id=user_id, content="mag keine Sprints")
    await remember_handler(session, user_id=user_id, content="Halbmarathon-Ziel im Herbst")

    result = await recall_handler(session, user_id=user_id, query="sprint")
    assert len(result["data"]) == 1
    assert "Sprints" in result["data"][0]["content"]


@pytest.mark.asyncio
async def test_render_handler_rejects_unknown_component(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Unbekannte Render-Komponente"):
        await render_handler(session, user_id=uuid4(), component="NotAComponent", config={})


@pytest.mark.asyncio
async def test_render_handler_accepts_known_component(session: AsyncSession) -> None:
    result = await render_handler(
        session, user_id=uuid4(), component="Gauge",
        config={"title": "HRV", "unit": "ms", "value": 60, "min": 0, "max": 100},
    )
    assert result["data"]["component"] == "Gauge"


@pytest.mark.asyncio
async def test_propose_calendar_event_handler_creates_event(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    mock_client = MagicMock()
    mock_client.create_event.return_value = {"id": "google-evt-tool-1"}
    with patch(
        "kairos.routers.calendar._build_google_calendar_client",
        new=AsyncMock(return_value=mock_client),
    ):
        result = await propose_calendar_event_handler(
            session, user_id=user_id, summary="Long Run",
            start_at="2026-09-01T07:00:00+00:00", end_at="2026-09-01T08:00:00+00:00",
        )
    assert result["data"]["summary"] == "Long Run"
    assert result["data"]["source"] == "kairos"


@pytest.mark.asyncio
async def test_delete_calendar_event_handler_requires_confirm_for_external(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = CalendarEventRepository(session)
    from kairos.connectors.types import CanonicalRecord

    await repo.upsert_from_records(
        user_id, "google_calendar",
        [
            CanonicalRecord(
                record_type="calendar_event", external_id="evt-ext-1",
                data={
                    "summary": "Zahnarzt", "description": None, "location": None,
                    "start_at": "2026-09-01T09:00:00+00:00", "end_at": "2026-09-01T10:00:00+00:00",
                    "all_day": False, "status": "confirmed",
                },
                occurred_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            )
        ],
    )
    await session.commit()
    row = (
        await session.execute(
            text("SELECT id FROM calendar_event WHERE user_id = :uid"), {"uid": str(user_id)}
        )
    ).scalar_one()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await delete_calendar_event_handler(session, user_id=user_id, event_id=str(row))
    assert exc_info.value.status_code == 409
