from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} muss ein nicht-leerer Text sein")
    return value


def _num(value: Any, path: str) -> int | float:
    # bool is an int subclass but never a valid measurement
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{path} muss eine endliche Zahl sein")
    return value


def _list(value: Any, path: str, lo: int, hi: int) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} muss eine Liste sein")
    if not lo <= len(value) <= hi:
        raise ValueError(f"{path} braucht {lo} bis {hi} Einträge, erhalten: {len(value)}")
    return value


def _obj(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} muss ein Objekt sein")
    return value


def _cell(value: Any, path: str) -> str | int | float:
    if isinstance(value, str):
        return value
    return _num(value, path)


def _time_series(config: dict[str, Any]) -> dict[str, Any]:
    points = []
    for i, raw in enumerate(_list(config.get("points"), "points", 1, 366)):
        p = _obj(raw, f"points[{i}]")
        day = _str(p.get("date"), f"points[{i}].date")
        try:
            if not _DATE_RE.match(day):
                raise ValueError
            date.fromisoformat(day)
        except ValueError:
            raise ValueError(f"points[{i}].date muss ein Datum YYYY-MM-DD sein") from None
        points.append({"date": day, "value": _num(p.get("value"), f"points[{i}].value")})
    return {"title": _str(config.get("title"), "title"),
            "unit": _str(config.get("unit"), "unit"), "points": points}


def _bar(config: dict[str, Any]) -> dict[str, Any]:
    bars = []
    for i, raw in enumerate(_list(config.get("bars"), "bars", 1, 50)):
        b = _obj(raw, f"bars[{i}]")
        bars.append({"label": _str(b.get("label"), f"bars[{i}].label"),
                     "value": _num(b.get("value"), f"bars[{i}].value")})
    return {"title": _str(config.get("title"), "title"),
            "unit": _str(config.get("unit"), "unit"), "bars": bars}


def _gauge(config: dict[str, Any]) -> dict[str, Any]:
    lo = _num(config.get("min"), "min")
    hi = _num(config.get("max"), "max")
    if lo >= hi:
        raise ValueError("min muss kleiner als max sein")
    return {"title": _str(config.get("title"), "title"),
            "unit": _str(config.get("unit"), "unit"),
            "value": _num(config.get("value"), "value"), "min": lo, "max": hi}


def _stat_card(config: dict[str, Any]) -> dict[str, Any]:
    items = []
    for i, raw in enumerate(_list(config.get("items"), "items", 1, 8)):
        it = _obj(raw, f"items[{i}]")
        item: dict[str, Any] = {"label": _str(it.get("label"), f"items[{i}].label"),
                                "value": _cell(it.get("value"), f"items[{i}].value")}
        if it.get("unit") is not None:
            item["unit"] = _str(it["unit"], f"items[{i}].unit")
        items.append(item)
    return {"title": _str(config.get("title"), "title"), "items": items}


def _table(config: dict[str, Any]) -> dict[str, Any]:
    columns = [_str(c, f"columns[{i}]")
               for i, c in enumerate(_list(config.get("columns"), "columns", 1, 8))]
    rows = []
    for i, raw in enumerate(_list(config.get("rows"), "rows", 0, 50)):
        row = _list(raw, f"rows[{i}]", len(columns), len(columns))
        rows.append([_cell(c, f"rows[{i}][{j}]") for j, c in enumerate(row)])
    return {"title": _str(config.get("title"), "title"), "columns": columns, "rows": rows}


_VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "TimeSeriesChart": _time_series,
    "BarChart": _bar,
    "Gauge": _gauge,
    "StatCard": _stat_card,
    "Table": _table,
}

RENDER_COMPONENTS = frozenset(_VALIDATORS)


def validate_render_config(component: str, config: dict[str, Any]) -> dict[str, Any]:
    validator = _VALIDATORS.get(component)
    if validator is None:
        raise ValueError(f"Unbekannte Render-Komponente: {component!r}")
    if not isinstance(config, dict):
        raise ValueError("config muss ein Objekt sein")
    try:
        return validator(config)
    except ValueError as exc:
        raise ValueError(f"Ungültige {component}-Konfiguration: {exc}") from None
