from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.goals import SqlGoalRepository

router = APIRouter(prefix="/api/goals", tags=["goals"])

_VALID_STATUSES = frozenset({"active", "completed", "abandoned"})


class GoalCreateRequest(BaseModel):
    title: str
    target_value: float | None = None
    target_unit: str | None = None
    target_date: date | None = None
    notes: str | None = None


class GoalUpdateRequest(BaseModel):
    title: str | None = None
    target_value: float | None = None
    target_unit: str | None = None
    target_date: date | None = None
    notes: str | None = None
    status: str | None = None


def _goal_to_dict(goal: Any) -> dict[str, Any]:
    return {
        "id": str(goal.id),
        "title": goal.title,
        "target_value": goal.target_value,
        "target_unit": goal.target_unit,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "notes": goal.notes,
        "status": goal.status,
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
    }


@router.get("")
async def list_goals(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlGoalRepository(session=session)
    goals = await repo.list_for_user(user_id=user_id)
    return {"goals": [_goal_to_dict(g) for g in goals]}


@router.post("", status_code=201)
async def create_goal(
    req: GoalCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlGoalRepository(session=session)
    goal = await repo.create(
        user_id=user_id,
        title=req.title,
        target_value=req.target_value,
        target_unit=req.target_unit,
        target_date=req.target_date,
        notes=req.notes,
    )
    await session.commit()
    return _goal_to_dict(goal)


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: UUID,
    req: GoalUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if req.status is not None and req.status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"invalid status: {req.status}")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlGoalRepository(session=session)
    goal = await repo.update(
        user_id=user_id,
        goal_id=goal_id,
        title=req.title,
        target_value=req.target_value,
        target_unit=req.target_unit,
        target_date=req.target_date,
        notes=req.notes,
        status=req.status,
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    await session.commit()
    return _goal_to_dict(goal)


@router.delete("/{goal_id}", status_code=204, response_model=None)
async def delete_goal(
    goal_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlGoalRepository(session=session)
    deleted = await repo.delete(user_id=user_id, goal_id=goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="goal not found")
    await session.commit()
