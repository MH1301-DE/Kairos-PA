from __future__ import annotations

from kairos.agent.metric_catalog import METRIC_CATALOG, render_metric_catalog
from kairos.agent.tools import CORE_TOOLS
from kairos.metrics.bootstrap import build_default_registry


def test_every_registered_metric_has_a_catalog_entry() -> None:
    registry = build_default_registry()
    assert set(registry.metric_ids()) == set(METRIC_CATALOG)


def test_rendered_catalog_lists_ids_variants_and_series_flag() -> None:
    text = render_metric_catalog()
    assert "trimp (Varianten: banister, edwards)" in text
    assert "hrv_baseline" in text
    assert "Zeitreihe: ja" in text and "Zeitreihe: nein" in text


def test_every_tool_has_a_real_description() -> None:
    for tool in CORE_TOOLS:
        assert len(tool.description) > 40, tool.name
