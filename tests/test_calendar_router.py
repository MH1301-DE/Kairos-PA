from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from kairos.api import app
from kairos.auth.deps import current_user


@pytest.fixture(autouse=True)
def _override_auth_and_session():
    # get_session is intentionally NOT overridden with a mock: AsyncMock() has no real
    # sync_session, so install_rls_listener's event.listens_for(session.sync_session,
    # "after_begin") raises InvalidRequestError. The real get_session lazily builds an
    # AsyncSession (no connection opened until first execute), which is fine here since
    # every test patches out the repository/_load_prefs calls that would touch the DB.
    app.dependency_overrides[current_user] = lambda: {"user_id": str(uuid4())}
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_events_requires_auth() -> None:
    app.dependency_overrides.pop(current_user, None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/calendar/events?from=2026-01-01&to=2026-01-08")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_events_returns_shaped_list() -> None:
    fake_event = AsyncMock()
    fake_event.id = uuid4()
    fake_event.summary = "Long Run"
    fake_event.description = None
    fake_event.location = None
    fake_event.start_at = datetime(2026, 1, 2, 7, 0, tzinfo=UTC)
    fake_event.end_at = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    fake_event.all_day = False
    fake_event.status = "confirmed"
    fake_event.source = "external"

    with patch(
        "kairos.routers.calendar.CalendarEventRepository.list_between",
        new=AsyncMock(return_value=[fake_event]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/calendar/events?from=2026-01-01&to=2026-01-08")

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["summary"] == "Long Run"


@pytest.mark.asyncio
async def test_get_free_slots_filters_by_min_duration() -> None:
    with (
        patch(
            "kairos.routers.calendar.CalendarEventRepository.list_between",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "kairos.routers.calendar._load_prefs",
            new=AsyncMock(
                return_value={
                    "work_hours_start": None,
                    "work_hours_end": None,
                    "calendar_buffer_minutes": 0,
                    "min_free_block_minutes": 30,
                }
            ),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/calendar/free-slots?from=2026-01-01&to=2026-01-02&duration_minutes=60"
            )

    assert response.status_code == 200
    body = response.json()
    assert len(body["slots"]) == 1


@pytest.mark.asyncio
async def test_post_event_creates_via_connector_and_persists() -> None:
    # GoogleCalendarClient.create_event is synchronous (httpx.Client, not AsyncClient) —
    # a MagicMock reflects that; an AsyncMock's child attrs are AsyncMock too, so calling
    # create_event() without await (matching production) would return an unawaited coroutine.
    mock_client = MagicMock()
    mock_client.create_event.return_value = {"id": "google-event-1"}

    # upsert_kairos_event returns the persisted row now (see Task 9 review fix round 1):
    # create_event's response must match list_events's per-event shape, which needs the
    # local calendar_event.id -- a plain AsyncMock() default return_value is a MagicMock
    # whose .start_at.isoformat() etc. aren't real strings, so this fakes a real row shape.
    fake_row = MagicMock()
    fake_row.id = uuid4()
    fake_row.summary = "Long Run"
    fake_row.description = None
    fake_row.location = None
    fake_row.start_at = datetime(2026, 3, 1, 7, 0, tzinfo=UTC)
    fake_row.end_at = datetime(2026, 3, 1, 8, 30, tzinfo=UTC)
    fake_row.all_day = False
    fake_row.status = "confirmed"
    fake_row.source = "kairos"

    with (
        patch(
            "kairos.routers.calendar._build_google_calendar_client",
            new=AsyncMock(return_value=mock_client),
        ),
        patch(
            "kairos.routers.calendar.GoogleCalendarConnector.write_back",
        ) as mock_write_back,
        patch(
            "kairos.routers.calendar.CalendarEventRepository.upsert_kairos_event",
            new=AsyncMock(return_value=fake_row),
        ) as mock_upsert,
    ):
        from kairos.connectors.types import WriteResult

        mock_write_back.return_value = WriteResult(written=1, failed=0)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/calendar/events",
                json={
                    "summary": "Long Run",
                    "start_at": "2026-03-01T07:00:00+00:00",
                    "end_at": "2026-03-01T08:30:00+00:00",
                    "description": None,
                },
            )

    assert response.status_code == 201
    mock_upsert.assert_called_once()
    body = response.json()
    assert body["id"] == str(fake_row.id)
    assert body == {
        "id": str(fake_row.id),
        "summary": "Long Run",
        "description": None,
        "location": None,
        "start_at": "2026-03-01T07:00:00+00:00",
        "end_at": "2026-03-01T08:30:00+00:00",
        "all_day": False,
        "status": "confirmed",
        "source": "kairos",
    }


@pytest.mark.asyncio
async def test_post_event_returns_503_without_active_connection() -> None:
    with patch(
        "kairos.routers.calendar._build_google_calendar_client", new=AsyncMock(return_value=None)
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/calendar/events",
                json={
                    "summary": "Long Run",
                    "start_at": "2026-03-01T07:00:00+00:00",
                    "end_at": "2026-03-01T08:30:00+00:00",
                    "description": None,
                },
            )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_delete_event_returns_404_for_missing_event() -> None:
    with patch(
        "kairos.routers.calendar.CalendarEventRepository.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/calendar/events/{uuid4()}")
    assert response.status_code == 404
