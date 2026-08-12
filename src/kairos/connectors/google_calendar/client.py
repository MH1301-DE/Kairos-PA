from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
EVENT_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"


class TokenExpired(Exception):
    pass


class UpstreamUnavailable(Exception):
    pass


class GoogleCalendarClient:
    def __init__(self, refresh_token: str, client_id: str, client_secret: str) -> None:
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret

    def list_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            params: dict[str, str] = {}
            if sync_token:
                params["syncToken"] = sync_token
            else:
                params["timeMin"] = time_min.isoformat()
                params["timeMax"] = time_max.isoformat()
            resp = http.get(
                EVENTS_URL.format(calendar_id=calendar_id),
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar list_events: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def create_event(
        self,
        calendar_id: str,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            body["description"] = description
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.post(
                EVENTS_URL.format(calendar_id=calendar_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar create_event: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def update_event(self, calendar_id: str, event_id: str, **fields: Any) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.patch(
                EVENT_URL.format(calendar_id=calendar_id, event_id=event_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json=fields,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar update_event: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.delete(
                EVENT_URL.format(calendar_id=calendar_id, event_id=event_id),
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar delete_event: {resp.status_code}")

    def _refresh_access_token(self, http: httpx.Client) -> str:
        resp = http.post(
            TOKEN_URL,
            data={
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code >= 400:
            raise TokenExpired("Google refresh token is no longer valid")
        access_token: str = resp.json()["access_token"]
        return access_token
