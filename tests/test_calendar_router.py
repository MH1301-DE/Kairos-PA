from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
async def test_get_free_slots_returns_slots_of_requested_duration() -> None:
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
    # the 24h free block is sliced into 60-minute candidates, capped at _MAX_SLOTS_PER_BLOCK
    assert len(body["slots"]) == 20
    for slot in body["slots"]:
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        assert end - start == timedelta(minutes=60)


@pytest.mark.asyncio
async def test_get_free_slots_slices_multi_day_block_into_duration_sized_slots() -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 1, 4, tzinfo=UTC)

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
                "/api/calendar/free-slots?from=2026-01-01&to=2026-01-04&duration_minutes=60"
            )

    assert response.status_code == 200
    slots = response.json()["slots"]
    assert slots
    for slot in slots:
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])
        assert end - start == timedelta(minutes=60)
        assert window_start <= start
        assert end <= window_end


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


def _fake_calendar_event(source: str) -> MagicMock:
    event = MagicMock()
    event.id = uuid4()
    event.calendar_id = "primary"
    event.external_id = "google-event-1"
    event.connector = "google_calendar"
    event.summary = "Zahnarzt"
    event.start_at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    event.source = source
    return event


@pytest.mark.asyncio
async def test_delete_external_event_without_confirm_returns_409() -> None:
    """A real, Google-synced event must never be deleted without an explicit
    confirmation -- enforced server-side so a future agent tool can't bypass it
    by skipping the frontend's confirm() dialog."""
    with (
        patch(
            "kairos.routers.calendar.CalendarEventRepository.get_by_id",
            new=AsyncMock(return_value=_fake_calendar_event("external")),
        ),
        patch(
            "kairos.routers.calendar.CalendarEventRepository.mark_deleted",
            new=AsyncMock(),
        ) as mock_mark_deleted,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/calendar/events/{uuid4()}")
    assert response.status_code == 409
    assert response.json()["detail"]["needs_confirmation"] is True
    mock_mark_deleted.assert_not_called()


@pytest.mark.asyncio
async def test_delete_external_event_with_confirm_succeeds() -> None:
    with (
        patch(
            "kairos.routers.calendar.CalendarEventRepository.get_by_id",
            new=AsyncMock(return_value=_fake_calendar_event("external")),
        ),
        patch(
            "kairos.routers.calendar._build_google_calendar_client",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "kairos.routers.calendar.CalendarEventRepository.mark_deleted",
            new=AsyncMock(),
        ) as mock_mark_deleted,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/calendar/events/{uuid4()}?confirm=true")
    assert response.status_code == 204
    mock_mark_deleted.assert_called_once()


@pytest.mark.asyncio
async def test_delete_kairos_event_needs_no_confirmation() -> None:
    """Kairos' own proposed events are low-risk (not the user's real synced
    calendar) and delete on a single click, same as before this change."""
    with (
        patch(
            "kairos.routers.calendar.CalendarEventRepository.get_by_id",
            new=AsyncMock(return_value=_fake_calendar_event("kairos")),
        ),
        patch(
            "kairos.routers.calendar._build_google_calendar_client",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "kairos.routers.calendar.CalendarEventRepository.mark_deleted",
            new=AsyncMock(),
        ) as mock_mark_deleted,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/calendar/events/{uuid4()}")
    assert response.status_code == 204
    mock_mark_deleted.assert_called_once()
