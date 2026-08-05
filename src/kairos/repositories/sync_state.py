from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class SqlSyncStateRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def mark_success(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        synced_through: datetime,
    ) -> None:
        await self._set_rls_user(user_id)
        await self._session.execute(
            text(
                """
                INSERT INTO sync_state (
                    user_id,
                    connector,
                    kind,
                    synced_through,
                    last_run_at,
                    last_success_at,
                    consecutive_failures
                )
                VALUES (
                    :user_id,
                    :connector,
                    :kind,
                    :synced_through,
                    NOW(),
                    NOW(),
                    0
                )
                ON CONFLICT (user_id, connector, kind)
                DO UPDATE SET
                    synced_through = COALESCE(
                        GREATEST(sync_state.synced_through, EXCLUDED.synced_through),
                        EXCLUDED.synced_through
                    ),
                    last_run_at = NOW(),
                    last_success_at = NOW(),
                    consecutive_failures = 0
                """
            ),
            {
                "user_id": str(user_id),
                "connector": connector_id,
                "kind": kind,
                "synced_through": synced_through,
            },
        )

    async def _set_rls_user(self, user_id: UUID) -> None:
        await self._session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))

    async def get_backfill_state(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
    ) -> tuple[datetime | None, datetime | None]:
        await self._set_rls_user(user_id)
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT backfill_cursor, backfill_complete_to
                    FROM sync_state
                    WHERE user_id = :user_id AND connector = :connector AND kind = :kind
                    """
                ),
                {
                    "user_id": str(user_id),
                    "connector": connector_id,
                    "kind": kind,
                },
            )
        ).one_or_none()
        if row is None:
            return None, None
        return row.backfill_cursor, row.backfill_complete_to

    async def set_backfill_cursor(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        cursor: datetime,
    ) -> None:
        await self._set_rls_user(user_id)
        await self._session.execute(
            text(
                """
                INSERT INTO sync_state (
                    user_id,
                    connector,
                    kind,
                    backfill_cursor,
                    last_run_at,
                    consecutive_failures
                )
                VALUES (
                    :user_id,
                    :connector,
                    :kind,
                    :cursor,
                    NOW(),
                    0
                )
                ON CONFLICT (user_id, connector, kind)
                DO UPDATE SET
                    backfill_cursor = EXCLUDED.backfill_cursor,
                    last_run_at = NOW()
                """
            ),
            {
                "user_id": str(user_id),
                "connector": connector_id,
                "kind": kind,
                "cursor": cursor,
            },
        )

    async def mark_backfill_complete(
        self,
        *,
        user_id: UUID,
        connector_id: str,
        kind: str,
        complete_to: datetime,
    ) -> None:
        await self._set_rls_user(user_id)
        await self._session.execute(
            text(
                """
                INSERT INTO sync_state (
                    user_id,
                    connector,
                    kind,
                    backfill_cursor,
                    backfill_complete_to,
                    last_run_at,
                    consecutive_failures
                )
                VALUES (
                    :user_id,
                    :connector,
                    :kind,
                    NULL,
                    :complete_to,
                    NOW(),
                    0
                )
                ON CONFLICT (user_id, connector, kind)
                DO UPDATE SET
                    backfill_cursor = NULL,
                    backfill_complete_to = COALESCE(
                        GREATEST(sync_state.backfill_complete_to, EXCLUDED.backfill_complete_to),
                        EXCLUDED.backfill_complete_to
                    ),
                    last_run_at = NOW()
                """
            ),
            {
                "user_id": str(user_id),
                "connector": connector_id,
                "kind": kind,
                "complete_to": complete_to,
            },
        )