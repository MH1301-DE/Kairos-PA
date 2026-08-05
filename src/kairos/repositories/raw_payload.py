from __future__ import annotations

import gzip
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import JSONValue, Window


class SqlRawPayloadRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        window: Window,
        payload: JSONValue,
        content_hash: bytes,
    ) -> int:
        await self._set_rls_user(user_id)

        payload_bytes = _gzip_json(payload)
        raw_id = (
            await self._session.execute(
            text(
                """
                INSERT INTO raw_payload (
                    user_id,
                    connector,
                    kind,
                    window_start,
                    window_end,
                    content_hash,
                    payload_gzip
                )
                VALUES (
                    :user_id,
                    :connector,
                    :kind,
                    :window_start,
                    :window_end,
                    :content_hash,
                    :payload_gzip
                )
                ON CONFLICT (user_id, connector, kind, window_start, content_hash)
                DO UPDATE SET
                    window_end = GREATEST(raw_payload.window_end, EXCLUDED.window_end)
                RETURNING id
                """
            ),
            {
                "user_id": str(user_id),
                "connector": connector_id,
                "kind": kind,
                "window_start": window.start,
                "window_end": window.end,
                "content_hash": content_hash,
                "payload_gzip": payload_bytes,
            },
            )
        ).scalar_one()

        return int(raw_id)

    async def _set_rls_user(self, user_id: UUID) -> None:
        await self._session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


def _gzip_json(payload: JSONValue) -> bytes:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return gzip.compress(serialized)