from __future__ import annotations

from kairos.connectors.base import Connector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        if connector.connector_id in self._connectors:
            raise ValueError(f"Connector already registered: {connector.connector_id}")
        self._connectors[connector.connector_id] = connector

    def get(self, connector_id: str) -> Connector:
        return self._connectors[connector_id]

    def list_ids(self) -> list[str]:
        return sorted(self._connectors)
