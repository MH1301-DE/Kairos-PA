from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.rls import install_rls_listener
from kairos.metrics.bootstrap import build_default_registry

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent_eval_suite.py"


def _load_seed():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("agent_eval_suite", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves annotations via sys.modules
    spec.loader.exec_module(module)
    return module.seed_test_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metric_id", ["hrv_baseline", "resting_hr_trend", "sleep_debt", "training_load", "trimp"]
)
async def test_seed_leaves_metric_with_data(session: AsyncSession, metric_id: str) -> None:
    user_id = uuid4()
    try:
        await _load_seed()(session, user_id)
        install_rls_listener(session, user_id)
        registry = build_default_registry()
        variant_id = registry.variants_for(metric_id)[0]
        result = await registry.get(metric_id, variant_id).compute(
            session, user_id=user_id, as_of=date.today()
        )
        assert result.confidence != "insufficient_data"
    finally:
        await session.rollback()
        await session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": str(user_id)})
        await session.commit()
