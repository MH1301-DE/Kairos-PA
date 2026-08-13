from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from kairos.connectors.google_calendar.client import (
    GoogleCalendarClient,
    TokenExpired,
    UpstreamUnavailable,
)


def _client() -> GoogleCalendarClient:
    return GoogleCalendarClient(
        refresh_token="test-refresh-token",
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_list_events_refreshes_token_then_lists(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    events_resp = MagicMock()
    events_resp.status_code = 200
    events_resp.json.return_value = {"items": [{"id": "evt1"}], "nextSyncToken": "sync-tok-1"}
    mock_http.post.return_value = token_resp
    mock_http.get.return_value = events_resp

    client = _client()
    result = client.list_events(
        "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
    )

    assert result["items"] == [{"id": "evt1"}]
    assert result["nextSyncToken"] == "sync-tok-1"
    # token refresh happened before the events call
    assert mock_http.post.called
    get_kwargs = mock_http.get.call_args.kwargs
    assert get_kwargs["headers"]["Authorization"] == "Bearer fresh-access-token"


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_list_events_follows_next_page_token(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {"items": [{"id": "evt1"}], "nextPageToken": "page-2"}
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {"items": [{"id": "evt2"}], "nextSyncToken": "sync-tok-2"}
    mock_http.post.return_value = token_resp
    mock_http.get.side_effect = [page1, page2]

    client = _client()
    result = client.list_events(
        "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
    )

    assert result["items"] == [{"id": "evt1"}, {"id": "evt2"}]
    assert result["nextSyncToken"] == "sync-tok-2"
    assert mock_http.get.call_count == 2
    assert mock_http.get.call_args_list[0].kwargs["params"]["singleEvents"] == "true"
    assert "pageToken" not in mock_http.get.call_args_list[0].kwargs["params"]
    assert mock_http.get.call_args_list[1].kwargs["params"]["pageToken"] == "page-2"


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_token_refresh_failure_raises_token_expired(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 400
    token_resp.json.return_value = {"error": "invalid_grant"}
    mock_http.post.return_value = token_resp

    client = _client()
    with pytest.raises(TokenExpired):
        client.list_events(
            "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
        )


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_create_event_sends_timed_event_body(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    create_resp = MagicMock()
    create_resp.status_code = 200
    create_resp.json.return_value = {"id": "new-evt-id", "summary": "Long Run"}
    mock_http.post.side_effect = [token_resp, create_resp]

    client = _client()
    result = client.create_event(
        "primary",
        summary="Long Run",
        start=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
    )

    assert result["id"] == "new-evt-id"
    create_call = mock_http.post.call_args_list[1]
    body = create_call.kwargs["json"]
    assert body["summary"] == "Long Run"
    assert body["start"]["dateTime"] == "2026-03-01T07:00:00+00:00"
    assert body["end"]["dateTime"] == "2026-03-01T08:30:00+00:00"


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_upstream_5xx_raises_upstream_unavailable(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    error_resp = MagicMock()
    error_resp.status_code = 503
    mock_http.post.return_value = token_resp
    mock_http.get.return_value = error_resp

    client = _client()
    with pytest.raises(UpstreamUnavailable):
        client.list_events(
            "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
        )
