from __future__ import annotations

import hashlib
import json

from kairos.connectors.types import JSONValue


def payload_sha256(payload: JSONValue) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).digest()
