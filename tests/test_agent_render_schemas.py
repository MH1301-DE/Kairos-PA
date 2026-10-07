from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.render_schemas import validate_render_config
from kairos.agent.tools import render_handler

VALID: dict[str, dict[str, Any]] = {
    "TimeSeriesChart": {"title": "HRV", "unit": "ms",
                        "points": [{"date": "2026-10-01", "value": 61.5}]},
    "BarChart": {"title": "Load", "unit": "TRIMP", "bars": [{"label": "Mo", "value": 40}]},
    "Gauge": {"title": "Readiness", "unit": "%", "value": 70, "min": 0, "max": 100},
    "StatCard": {"title": "Heute", "items": [{"label": "HRV", "value": 62, "unit": "ms"},
                                             {"label": "Status", "value": "gut"}]},
    "Table": {"title": "Läufe", "columns": ["Tag", "km"], "rows": [["Mo", 10], ["Di", "5"]]},
}


@pytest.mark.parametrize("component", sorted(VALID))
def test_valid_config_is_returned_normalized(component: str) -> None:
    config = {**VALID[component], "extra": "dropped"}
    assert validate_render_config(component, config) == VALID[component]


def test_empty_points_rejected() -> None:
    with pytest.raises(ValueError, match="points"):
        validate_render_config("TimeSeriesChart", {**VALID["TimeSeriesChart"], "points": []})


def test_bad_date_rejected() -> None:
    config = {**VALID["TimeSeriesChart"], "points": [{"date": "01.10.2026", "value": 1}]}
    with pytest.raises(ValueError, match="date"):
        validate_render_config("TimeSeriesChart", config)


def test_boolean_is_not_a_number() -> None:
    config = {**VALID["Gauge"], "value": True}
    with pytest.raises(ValueError, match="value"):
        validate_render_config("Gauge", config)


@pytest.mark.parametrize("lo,hi", [(100, 0), (5, 5)])
def test_gauge_min_must_be_below_max(lo: int, hi: int) -> None:
    with pytest.raises(ValueError, match="min"):
        validate_render_config("Gauge", {**VALID["Gauge"], "min": lo, "max": hi})


def test_table_row_length_mismatch_rejected() -> None:
    config = {**VALID["Table"], "rows": [["Mo"]]}
    with pytest.raises(ValueError, match="rows"):
        validate_render_config("Table", config)


def test_statcard_item_limit() -> None:
    items = [{"label": str(i), "value": i} for i in range(9)]
    with pytest.raises(ValueError, match="items"):
        validate_render_config("StatCard", {"title": "x", "items": items})


def test_unknown_component_rejected() -> None:
    with pytest.raises(ValueError, match="Unbekannte"):
        validate_render_config("ScatterChart", {})


@pytest.mark.asyncio
async def test_render_handler_returns_normalized_config(session: AsyncSession) -> None:
    result = await render_handler(
        session, user_id=uuid4(), component="Gauge", config={**VALID["Gauge"], "extra": 1}
    )
    assert result["data"] == {"component": "Gauge", "config": VALID["Gauge"]}


@pytest.mark.asyncio
async def test_render_handler_raises_on_invalid_config(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Gauge"):
        await render_handler(session, user_id=uuid4(), component="Gauge", config={"title": "x"})
