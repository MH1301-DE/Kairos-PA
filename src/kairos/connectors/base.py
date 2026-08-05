from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from kairos.connectors.types import (
    CanonicalRecord,
    JSONValue,
    RawPayloadEnvelope,
    Window,
    WriteResult,
)


class Connector(Protocol):
    connector_id: str

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        ...

    def normalize(self, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
        ...

    def write_back(
        self,
        user_id: UUID,
        kind: str,
        records: Sequence[CanonicalRecord],
    ) -> WriteResult:
        ...
