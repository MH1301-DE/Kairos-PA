"""Decode Garmin FIT ZIP archives into JSON-serialisable message dicts."""

from __future__ import annotations

import importlib
import io
import zipfile
from datetime import datetime
from typing import Any


def decode_fit_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Extract the first .fit from a ZIP archive and decode it."""
    fit_bytes = _extract_fit(zip_bytes)
    return _decode_fit_bytes(fit_bytes)


def records_to_json(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialise FIT message dicts; converts datetime → ISO string, drops non-JSON types."""
    result = []
    for rec in records:
        row: dict[str, Any] = {}
        for k, v in rec.items():
            # garmin_fit_sdk uses the raw numeric field id (int) as the dict key
            # when it can't resolve a developer field to a name -- stringify so
            # every key is str, otherwise json.dumps(sort_keys=True) later
            # (payload_sha256) crashes comparing int < str during key sort.
            key = str(k)
            if isinstance(v, datetime):
                row[key] = v.isoformat()
            elif isinstance(v, (int, float, str, bool, type(None))):
                row[key] = v
        result.append(row)
    return result


def _extract_fit(data: bytes) -> bytes:
    if data[:2] != b"PK":
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not names:
            raise ValueError("ZIP contains no .fit file")
        return zf.read(names[0])


def _decode_fit_bytes(fit_bytes: bytes) -> dict[str, Any]:
    sdk = importlib.import_module("garmin_fit_sdk")
    stream = sdk.Stream.from_byte_array(fit_bytes)
    decoder = sdk.Decoder(stream)
    messages, _ = decoder.read()
    return messages  # type: ignore[no-any-return]
