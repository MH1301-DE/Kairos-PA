from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.models import UserDashboardTile
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# mirrors web/src/lib/modules.ts's MODULES order exactly -- this is the
# fallback a user with no saved layout sees, must stay in sync by hand
_DEFAULT_MODULE_ORDER: tuple[str, ...] = (
    "trimp",
    "hr_zone_distribution",
    "training_load",
    "acwr",
    "monotony_strain",
    "hrv_baseline",
    "sleep_debt",
    "resting_hr_trend",
)


class TileLayoutEntry(BaseModel):
    module_id: str
    position: int
    visible: bool


class SaveLayoutRequest(BaseModel):
    tiles: list[TileLayoutEntry]


@router.get("/layout")
async def get_layout(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    rows = (
        await session.execute(
            select(UserDashboardTile)
            .where(UserDashboardTile.user_id == user_id)
            .order_by(UserDashboardTile.position)
        )
    ).scalars().all()

    if not rows:
        return {
            "tiles": [
                {"module_id": module_id, "position": i, "visible": True}
                for i, module_id in enumerate(_DEFAULT_MODULE_ORDER)
            ]
        }
    return {
        "tiles": [
            {"module_id": r.module_id, "position": r.position, "visible": r.visible}
            for r in rows
        ]
    }


@router.put("/layout")
async def save_layout(
    req: SaveLayoutRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    unknown = {t.module_id for t in req.tiles} - set(_DEFAULT_MODULE_ORDER)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown module_id(s): {sorted(unknown)}")

    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    await session.execute(delete(UserDashboardTile).where(UserDashboardTile.user_id == user_id))
    if req.tiles:
        await session.execute(
            insert(UserDashboardTile),
            [
                {
                    "user_id": user_id, "module_id": t.module_id,
                    "position": t.position, "visible": t.visible,
                }
                for t in req.tiles
            ],
        )
    await session.commit()
    return {"status": "ok"}
