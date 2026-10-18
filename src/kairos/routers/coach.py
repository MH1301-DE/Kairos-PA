from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.coach.knowledge import get_knowledge
from kairos.coach.model import WEEKDAY_KEYS
from kairos.db.models import CoachProfile
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.coach import CoachProfileRepository

router = APIRouter(prefix="/api/coach", tags=["coach"])

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class DayAvailabilityIn(BaseModel):
    max_min: int = Field(ge=0, le=600)
    quality: bool = False
    time: str | None = None

    @field_validator("time")
    @classmethod
    def _hh_mm(cls, value: str | None) -> str | None:
        if value is not None and not _TIME.match(value):
            raise ValueError("time must be HH:MM")
        return value


class CoachProfileRequest(BaseModel):
    plan_type: str
    availability: dict[str, DayAvailabilityIn]

    @field_validator("availability")
    @classmethod
    def _weekdays(cls, value: dict[str, DayAvailabilityIn]) -> dict[str, DayAvailabilityIn]:
        unknown = set(value) - set(WEEKDAY_KEYS)
        if unknown:
            raise ValueError(f"unknown weekdays: {sorted(unknown)}")
        if not any(day.max_min > 0 for day in value.values()):
            raise ValueError("at least one training day is required")
        return value


def _plan_types() -> list[dict[str, str]]:
    kb = get_knowledge()
    return [
        {"id": pid, "titel": pt.head.titel, "hauptsport": pt.head.hauptsport}
        for pid, pt in sorted(kb.plan_types.items())
    ]


def _out(profile: CoachProfile | None) -> dict[str, Any]:
    return {
        "profile": None
        if profile is None
        else {
            "plan_type": profile.plan_type,
            "main_sport": profile.main_sport,
            "availability": profile.availability,
            "onboarded_at": profile.onboarded_at.isoformat() if profile.onboarded_at else None,
        },
        "plan_types": _plan_types(),
    }


@router.get("/profile")
async def get_profile(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    return _out(await CoachProfileRepository(session).get(user_id))


@router.put("/profile")
async def put_profile(
    req: CoachProfileRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    plan_type = get_knowledge().plan_types.get(req.plan_type)
    if plan_type is None:
        raise HTTPException(status_code=422, detail=f"unknown plan_type {req.plan_type}")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    profile = await CoachProfileRepository(session).upsert(
        user_id,
        plan_type=req.plan_type,
        main_sport=plan_type.head.hauptsport,
        availability={
            key: day.model_dump(exclude_none=True) for key, day in req.availability.items()
        },
    )
    await session.commit()
    return _out(profile)
