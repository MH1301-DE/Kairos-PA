from __future__ import annotations

from datetime import UTC, date, datetime, time


def _parse_expiry(value: str) -> datetime:
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time(23, 59, 59), tzinfo=UTC)
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"expires_at muss ein ISO-Datum sein, nicht {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
