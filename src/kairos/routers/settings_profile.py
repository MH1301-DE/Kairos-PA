from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.metrics.hr_zones import resolve_hr_max
from kairos.repositories.user_setting import (
    get_or_default_user_setting,
    measured_max_hr_12m,
    upsert_profile,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProfileUpdateRequest(BaseModel):
    birth_date: date | None = None
    hr_max_override: int | None = Field(default=None, ge=120, le=230)
    resting_hr_override: int | None = Field(default=None, ge=30, le=100)

    @field_validator("birth_date")
    @classmethod
    def _birth_date_in_past(cls, value: date | None) -> date | None:
        if value is not None and not (date(1900, 1, 1) <= value < datetime.now(UTC).date()):
            raise ValueError("birth_date must be in the past and not before 1900")
        return value


async def _profile(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    setting = await get_or_default_user_setting(session, user_id=user_id)
    used, source = resolve_hr_max(
        setting.birth_date, setting.hr_max_override, as_of=datetime.now(UTC).date()
    )
    measured = await measured_max_hr_12m(session, user_id=user_id)
    warning = None
    if used is not None and measured is not None and measured > used:
        warning = f"gemessen {measured} bpm, {source} {used} – prüfen"
    return {
        "birth_date": setting.birth_date.isoformat() if setting.birth_date else None,
        "hr_max_override": setting.hr_max_override,
        "resting_hr_override": setting.resting_hr_override,
        "hr_max_used": used,
        "hr_max_source": source,
        "hr_max_measured_12m": measured,
        "hr_max_warning": warning,
    }


@router.get("/profile")
async def get_profile(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    return await _profile(session, user_id)


@router.put("/profile")
async def put_profile(
    req: ProfileUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    await upsert_profile(
        session,
        user_id=user_id,
        birth_date=req.birth_date,
        hr_max_override=req.hr_max_override,
        resting_hr_override=req.resting_hr_override,
    )
    await session.commit()
    return await _profile(session, user_id)
