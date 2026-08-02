import uuid
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession


def install_rls_listener(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Sets app.current_user_id for every transaction on this session."""

    @event.listens_for(session.sync_session, "after_begin")
    def _set_rls(session_sync: Any, transaction: Any, connection: Any) -> None:
        # SET LOCAL doesn't accept bind parameters; UUID str is hex+dashes so interpolation is safe
        connection.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
