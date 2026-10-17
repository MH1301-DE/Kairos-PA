from __future__ import annotations

from datetime import UTC, datetime

from kairos.db.models import Connection


def mark_reauth_required(conn_row: Connection, error: str) -> None:
    conn_row.status = "reauth_required"
    conn_row.last_error = error
    # set once, when the connection first breaks -- not bumped on every retry
    if conn_row.reauth_since is None:
        conn_row.reauth_since = datetime.now(UTC)


def mark_connection_healthy(conn_row: Connection) -> None:
    conn_row.status = "active"
    conn_row.last_error = None
    conn_row.reauth_since = None
    conn_row.last_ok_at = datetime.now(UTC)
