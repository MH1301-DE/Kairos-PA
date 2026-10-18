from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kairos.coach.knowledge import REQUIRED_SECTIONS, USER_SECTION, KnowledgeBase, load_knowledge
from kairos.coach.rules import Einheit, Schritt

KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge" / "training"

# spec 6.6: the first guard rails and rules from the research
_REQUIRED_ENTRIES = {
    "lauf.progression.einzellauf": "leitplanke",
    "lauf.intensitaet.z1-anteil": "leitplanke",
    "lauf.einheit.long-run": "einheit",
    "lauf.progression.wochenzuwachs": "regel",
    "lauf.einheit.schwelle": "einheit",
    "lauf.einheit.intervall": "einheit",
    "lauf.einheit.wiederholung": "einheit",
    "lauf.einheit.marathontempo": "einheit",
    "kraft.abstand": "regel",
    "alle.taper.standard": "regel",
}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_knowledge(KNOWLEDGE)


def test_every_entry_and_plan_type_is_valid(kb: KnowledgeBase) -> None:
    assert kb.errors == []
    assert kb.unavailable == {}
    assert "ausdauer-laufen-pyramidal" in kb.plan_types


def test_entries_cite_known_sources_and_explain_themselves(kb: KnowledgeBase) -> None:
    for entry in kb.entries.values():
        assert entry.head.quellen and all(q in kb.sources for q in entry.head.quellen)
        for section in (*REQUIRED_SECTIONS, USER_SECTION):
            assert entry.sections.get(section), f"{entry.id}: {section}"
        assert entry.path.startswith("regeln/")


def test_first_guard_rails_exist(kb: KnowledgeBase) -> None:
    for rule_id, art in _REQUIRED_ENTRIES.items():
        assert kb.entries[rule_id].head.art == art, rule_id


def _variable_steps(steps: list[Schritt]) -> int:
    return sum((_variable_steps(s.schritte) if s.schritte else 0) + int(s.variabel) for s in steps)


def test_every_unit_is_a_well_formed_workout(kb: KnowledgeBase) -> None:
    plan_type = kb.plan_types["ausdauer-laufen-pyramidal"]
    for unit_id, entry in plan_type.units().items():
        unit = entry.head.regel
        assert isinstance(unit, Einheit), unit_id
        # the generator sizes at most one step from the planned volume
        assert _variable_steps(unit.struktur) <= 1, unit_id
        if unit.sport == "laufen":
            assert all(s.tempo is not None for s in unit.struktur if s.typ != "wiederholung"), (
                unit_id
            )


def test_plan_type_parameters_follow_the_decisions(kb: KnowledgeBase) -> None:
    params = kb.plan_types["ausdauer-laufen-pyramidal"].parameters
    assert params["verteilung"] == "pyramidal"
    assert params["verteilung_spitze"] == "polarisiert"
    assert params["detail_wochen"] == 2
    for split in params["verteilungen"].values():  # type: ignore[attr-defined]
        assert sum(split.values()) == pytest.approx(1.0)


def test_search_finds_entries_by_text(kb: KnowledgeBase) -> None:
    hits = kb.search("Warum nur 80 % locker")
    assert hits and hits[0].id == "lauf.intensitaet.z1-anteil"
    assert kb.entry("lauf.progression.einzellauf@1") is not None


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "training"
    shutil.copytree(KNOWLEDGE, target)
    return target


def test_broken_entry_disables_only_its_plan_types(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    file = root / "regeln" / "einheiten" / "lauf.einheit.schwelle.md"
    file.write_text(
        file.read_text(encoding="utf-8").replace("typ: einheit", "typ: freier_code"),
        encoding="utf-8",
    )

    kb = load_knowledge(root)

    assert "lauf.einheit.schwelle" not in kb.entries
    assert "ausdauer-laufen-pyramidal" not in kb.plan_types
    assert any("lauf.einheit.schwelle" in p for p in kb.unavailable["ausdauer-laufen-pyramidal"])


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ("quellen: [frandsen2025]", "quellen: [unbekannt2030]", "Quelle unbekannt2030"),
        ("## Wann nicht", "## Sonstiges", "Wann nicht"),
        ("faktor: 1.10", 'faktor: 1.10\n  ausdruck: "faktor * 2"', "Extra inputs"),
    ],
)
def test_invalid_entries_are_reported(
    tmp_path: Path, needle: str, replacement: str, message: str
) -> None:
    root = _copy(tmp_path)
    file = root / "regeln" / "progression" / "lauf.progression.einzellauf.md"
    file.write_text(
        file.read_text(encoding="utf-8").replace(needle, replacement, 1), encoding="utf-8"
    )

    kb = load_knowledge(root)

    assert any(message in e for e in kb.errors), kb.errors
    assert "lauf.progression.einzellauf" not in kb.entries
