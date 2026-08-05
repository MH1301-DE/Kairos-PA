from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class RawPayloadEnvelope:
    window: Window
    payload: JSONValue


@dataclass(frozen=True)
class CanonicalRecord:
    record_type: str
    external_id: str
    data: JSONValue
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class WriteResult:
    written: int
    failed: int = 0
