from typing import Any

from fastapi import Cookie, HTTPException

from kairos.auth.session import get_session


async def current_user(session_id: str | None = Cookie(default=None)) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="session_expired")
    return session
