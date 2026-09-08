from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.data_read import SqlDataReadRepository

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/wellness/{metric}")
async def wellness_series(
    metric: str,
    from_date: date | None = None,
    to_date: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    points = await repo.list_wellness_series(
        user_id=user_id,
        metric=metric,
        from_date=_to_utc_midnight(from_date or date.today().replace(day=1)),
        # +1 day: the repository bound is exclusive, so this covers all of to_date
        to_date=_to_utc_midnight(to_date or date.today()) + timedelta(days=1),
    )
    return {
        "metric": metric,
        "points": [
            {"observed_at": p.observed_at.isoformat(), "value": p.value, "quality": p.quality}
            for p in points
        ],
    }


@router.get("/activities")
async def list_activities(
    limit: int = 50,
    cursor: str | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    page = await repo.list_activities(user_id=user_id, limit=limit, cursor=cursor)
    return {
        "items": [
            {
                "external_id": a.external_id,
                "name": a.name,
                "sport": a.sport,
                "start_at": a.start_at.isoformat() if a.start_at else None,
                "distance_m": a.distance_m,
                "duration_s": a.duration_s,
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
            }
            for a in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.get("/activities/{external_id}")
async def activity_detail(
    external_id: str,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id=external_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="activity not found")
    return {
        "external_id": detail.activity.external_id,
        "name": detail.activity.name,
        "sport": detail.activity.sport,
        "start_at": detail.activity.start_at.isoformat() if detail.activity.start_at else None,
        "records": [
            {"recorded_at": r.recorded_at.isoformat(), "metric": r.metric, "value": r.value}
            for r in detail.records
        ],
    }


@router.get("/sleep")
async def sleep_sessions(
    from_date: date | None = None,
    to_date: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = SqlDataReadRepository(session=session)
    sessions = await repo.list_sleep_sessions(
        user_id=user_id,
        from_date=_to_utc_midnight(from_date or date.today().replace(day=1)),
        # +1 day: the repository bound is exclusive, so this covers all of to_date
        to_date=_to_utc_midnight(to_date or date.today()) + timedelta(days=1),
    )
    return {
        "sessions": [
            {
                "start_at": s.start_at.isoformat(),
                "end_at": s.end_at.isoformat() if s.end_at else None,
                "duration_seconds": s.duration_seconds,
            }
            for s in sessions
        ]
    }


def _to_utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
