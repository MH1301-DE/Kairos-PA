from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from kairos.connectors.base import Connector
from kairos.connectors.registry import ConnectorRegistry
from kairos.connectors.types import CanonicalRecord, RawPayloadEnvelope, Window, WriteResult


@dataclass
class DummyConnector:
    connector_id: str = "dummy"

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id, kind
        return RawPayloadEnvelope(window=window, payload={"ok": True})

    def normalize(self, payload: object) -> list[CanonicalRecord]:
        del payload
        return [CanonicalRecord(record_type="activity", external_id="1", data={"distance": 12.3})]

    def write_back(self, user_id: UUID, kind: str, records: list[CanonicalRecord]) -> WriteResult:
        del user_id, kind, records
        return WriteResult(written=0)


def _window() -> Window:
    return Window(
        start=datetime(2026, 8, 1, tzinfo=UTC),
        end=datetime(2026, 8, 2, tzinfo=UTC),
    )


def test_dummy_connector_matches_protocol() -> None:
    connector: Connector = DummyConnector()
    envelope = connector.fetch(uuid4(), "activities", _window())
    rows = connector.normalize(envelope.payload)

    assert connector.connector_id == "dummy"
    assert envelope.window.start < envelope.window.end
    assert len(rows) == 1


def test_registry_register_get_and_list() -> None:
    registry = ConnectorRegistry()
    connector = DummyConnector()

    registry.register(connector)

    assert registry.get("dummy") is connector
    assert registry.list_ids() == ["dummy"]


def test_registry_rejects_duplicate_connector_ids() -> None:
    registry = ConnectorRegistry()
    registry.register(DummyConnector())

    with pytest.raises(ValueError):
        registry.register(DummyConnector())
