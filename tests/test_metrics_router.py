from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.deps as _deps
from kairos.api import app
from kairos.metrics.registry import MetricRegistry
from kairos.metrics.types import MetricResult
from kairos.routers import metrics as metrics_router_module


class _StubVariant:
    metric_id = "trimp"
    variant_id = "edwards"

    async def compute(self, session: object, *, user_id: UUID, as_of: date) -> MetricResult:
        del session, user_id
        return MetricResult(
            value=42.0, unit="trimp_pt", confidence="high",
            coverage_days=1, coverage_required_days=1, as_of=as_of.isoformat(),
        )


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant())
    monkeypatch.setattr(metrics_router_module, "_registry", registry)


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        if session_id == "valid":
            return {"user_id": str(uuid4())}
        return None

    # patched on kairos.auth.deps (the consumer), not kairos.auth.session (the
    # definer) — deps.py does `from kairos.auth.session import get_session`,
    # which binds its own name at import time; patching the source module
    # leaves that binding untouched and the real function (hitting Redis) runs.
    monkeypatch.setattr(_deps, "get_session", _fake_get_session)


@pytest.mark.asyncio
async def test_get_metric_returns_computed_value() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics/trimp", params={"variant": "edwards", "as_of": "2026-08-01"},
            cookies={"session_id": "valid"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 42.0
    assert body["confidence"] == "high"


@pytest.mark.asyncio
async def test_get_metric_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/trimp")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_metric_unknown_variant_returns_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics/trimp", params={"variant": "nonexistent"},
            cookies={"session_id": "valid"},
        )

    assert resp.status_code == 404
