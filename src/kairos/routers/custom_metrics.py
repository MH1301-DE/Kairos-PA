from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.models import MetricDef
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.metrics.bootstrap import build_default_registry
from kairos.metrics.custom_eval import InvalidExpression, extract_metric_refs
from kairos.repositories.custom_metrics import CustomMetricRepository

router = APIRouter(prefix="/api/metrics/custom", tags=["custom-metrics"])


class CustomMetricCreateRequest(BaseModel):
    code: str
    display_name: str
    expression: str


def _definition_to_dict(d: Any) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "code": d.code,
        "display_name": d.display_name,
        "expression": d.expression,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat(),
    }


async def _known_metric_codes(session: AsyncSession) -> set[str]:
    raw_codes = (await session.execute(select(MetricDef.code))).scalars().all()
    # formula IDs (e.g. 'trimp', 'acwr') from the same registry metric_daily_value
    # recomputes against -- a custom metric can reference either kind
    formula_ids = build_default_registry().metric_ids()
    return set(raw_codes) | set(formula_ids)


@router.get("")
async def list_custom_metrics(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CustomMetricRepository(session=session)
    definitions = await repo.list_for_user(user_id=user_id)
    return {"definitions": [_definition_to_dict(d) for d in definitions]}


@router.post("", status_code=201)
async def create_custom_metric(
    req: CustomMetricCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    try:
        refs = extract_metric_refs(req.expression)
    except InvalidExpression as exc:
        raise HTTPException(status_code=422, detail=f"invalid expression: {exc}") from exc

    known = await _known_metric_codes(session)
    unknown = refs - known
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown metric reference(s): {sorted(unknown)}"
        )

    repo = CustomMetricRepository(session=session)
    definition = await repo.create(
        user_id=user_id,
        code=req.code,
        display_name=req.display_name,
        expression=req.expression,
        # always "user" here -- an agent-created custom metric is written internally
        # by the future agent tool layer via CustomMetricRepository directly, never
        # through this client-facing endpoint
        created_by="user",
    )
    await session.commit()
    return _definition_to_dict(definition)


@router.delete("/{definition_id}", status_code=204, response_model=None)
async def delete_custom_metric(
    definition_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CustomMetricRepository(session=session)
    deleted = await repo.delete(user_id=user_id, definition_id=definition_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="custom metric not found")
    await session.commit()
