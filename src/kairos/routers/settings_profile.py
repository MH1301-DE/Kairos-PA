from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive.service import rederive_all
from kairos.auth.deps import current_user
from kairos.db.models import HrBucketSecondsDaily
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory, get_session
from kairos.metrics.hr_zones import hr_max_warning, resolve_hr_max
from kairos.repositories.metrics_recompute import recompute_metric_daily_values
from kairos.repositories.user_setting import (
    get_or_default_user_setting,
    measured_max_hr_12m,
    upsert_profile,
)

logger = logging.getLogger(__name__)

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
    return {
        "birth_date": setting.birth_date.isoformat() if setting.birth_date else None,
        "hr_max_override": setting.hr_max_override,
        "resting_hr_override": setting.resting_hr_override,
        "hr_max_used": used,
        "hr_max_source": source,
        "hr_max_measured_12m": measured,
        "hr_max_warning": hr_max_warning(used, source, measured),
    }


@router.get("/profile")
async def get_profile(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    return await _profile(session, user_id)


async def _rederive_history(user_id: UUID) -> None:
    # spec A.6: a new HRmax changes zones and TRIMP of the whole history
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        try:
            await rederive_all(session, user_id=user_id)
            await session.commit()
            first = (
                await session.execute(
                    select(func.min(HrBucketSecondsDaily.day)).where(
                        HrBucketSecondsDaily.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if first is not None:
                await recompute_metric_daily_values(
                    session, user_id=user_id, start=first, end=datetime.now(UTC).date()
                )
                await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Re-derive after HRmax change failed for user %s", user_id)


@router.put("/profile")
async def put_profile(
    req: ProfileUpdateRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    before = await get_or_default_user_setting(session, user_id=user_id)
    hr_inputs = (before.birth_date, before.hr_max_override)
    await upsert_profile(
        session,
        user_id=user_id,
        birth_date=req.birth_date,
        hr_max_override=req.hr_max_override,
        resting_hr_override=req.resting_hr_override,
    )
    await session.commit()
    if (req.birth_date, req.hr_max_override) != hr_inputs:
        background_tasks.add_task(_rederive_history, user_id)
    return await _profile(session, user_id)
