"""Loads and validates ``knowledge/training/`` (coach spec 3.5).

Invalid entries are logged and make the plan types that use them unavailable, they never
stop the API (S7); the CI test ``tests/test_knowledge_base.py`` catches them earlier.
"""

from __future__ import annotations

import functools
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from kairos.coach.rules import Einheit, EntryHead, Phase, PlanTypeHead, Test, Zonen

logger = logging.getLogger(__name__)

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
REQUIRED_SECTIONS = ("Warum", "Wann nicht")
USER_SECTION = "Für den Nutzer"
_STOPWORDS = frozenset(
    [
        "warum",
        "wieso",
        "weshalb",
        "was",
        "wie",
        "wann",
        "wo",
        "nur",
        "und",
        "oder",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "ist",
        "sind",
        "mein",
        "meine",
        "mir",
        "mich",
        "ich",
        "du",
        "dein",
        "bei",
        "mit",
        "für",
        "von",
        "zu",
        "im",
        "in",
        "am",
        "an",
        "auf",
        "aus",
        "nicht",
    ]
)


@dataclass(frozen=True)
class Entry:
    head: EntryHead
    sections: dict[str, str]
    path: str

    @property
    def id(self) -> str:
        return self.head.id

    @property
    def ref(self) -> str:
        return f"{self.head.id}@{self.head.version}"

    @property
    def user_text(self) -> str:
        return self.sections.get(USER_SECTION, self.head.titel)


@dataclass(frozen=True)
class PlanType:
    head: PlanTypeHead
    entries: dict[str, Entry]

    @property
    def id(self) -> str:
        return self.head.id

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.head.parameter)

    def rule_entries(self) -> list[Entry]:
        return [self.entries[r] for r in self.head.regeln]

    def units(self) -> dict[str, Entry]:
        return {u: self.entries[u] for u in self.head.einheiten}

    def phases(self) -> Phase:
        regel = self.entries[self.head.phasen].head.regel
        assert isinstance(regel, Phase)
        return regel


@dataclass
class KnowledgeBase:
    entries: dict[str, Entry] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_types: dict[str, PlanType] = field(default_factory=dict)
    unavailable: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def entry(self, ref: str) -> Entry | None:
        return self.entries.get(ref.split("@", 1)[0])

    def search(self, query: str, sport: str | None = None, limit: int = 5) -> list[Entry]:
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 1 and w not in _STOPWORDS}
        scored: list[tuple[int, int, int, str, Entry]] = []
        for entry in self.entries.values():
            if sport and sport not in entry.head.sportarten and "alle" not in entry.head.sportarten:
                continue
            title = f"{entry.id} {entry.head.titel}".lower()
            text = " ".join([title, *entry.sections.values()]).lower()
            hits = {w for w in words if w in text}
            if hits:
                in_title = sum(1 for w in hits if w in title)
                scored.append(
                    (len(hits), in_title, sum(text.count(w) for w in hits), entry.id, entry)
                )
        # most distinct query words first, then title matches, then frequency
        scored.sort(key=lambda s: (-s[0], -s[1], -s[2], s[3]))
        return [s[4] for s in scored[:limit]]


def default_dir() -> Path:
    configured = os.environ.get("COACH_KNOWLEDGE_DIR")
    if configured:
        return Path(configured)
    # repo checkout (dev, tests) or the image's WORKDIR, both run from the project root
    for candidate in (
        Path.cwd() / "knowledge" / "training",
        Path(__file__).resolve().parents[3] / "knowledge" / "training",
    ):
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "knowledge" / "training"


def load_knowledge(path: Path) -> KnowledgeBase:
    kb = KnowledgeBase()
    sources_file = path / "quellen.yaml"
    if sources_file.is_file():
        kb.sources = yaml.safe_load(sources_file.read_text(encoding="utf-8")) or {}
    else:
        kb.errors.append("quellen.yaml fehlt")

    for file in sorted((path / "regeln").rglob("*.md")):
        rel = file.relative_to(path).as_posix()
        try:
            entry = _parse_entry(file, rel)
        except (ValueError, ValidationError, yaml.YAMLError) as exc:
            kb.errors.append(f"{rel}: {_short(exc)}")
            continue
        problems = _entry_problems(entry, kb)
        if problems:
            kb.errors.extend(f"{rel}: {p}" for p in problems)
            continue
        kb.entries[entry.id] = entry

    for file in sorted((path / "plantypen").glob("*.yaml")):
        rel = file.relative_to(path).as_posix()
        try:
            head = PlanTypeHead.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as exc:
            kb.errors.append(f"{rel}: {_short(exc)}")
            continue
        problems = list(dict.fromkeys(_plan_type_problems(head, kb)))
        if problems:
            kb.unavailable[head.id] = problems
            kb.errors.extend(f"{rel}: {p}" for p in problems)
            continue
        refs = {*head.regeln, head.phasen, *head.zonen, *head.tests, *head.einheiten}
        kb.plan_types[head.id] = PlanType(head, {r: kb.entries[r] for r in refs})

    for error in kb.errors:
        logger.warning("Knowledge base: %s", error)
    return kb


@functools.cache
def get_knowledge() -> KnowledgeBase:
    return load_knowledge(default_dir())


def _parse_entry(file: Path, rel: str) -> Entry:
    text = file.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError("YAML-Kopf zwischen --- fehlt")
    head = EntryHead.model_validate(yaml.safe_load(match.group(1)))
    body = match.group(2)
    parts = _SECTION.split(body)
    sections = {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return Entry(head=head, sections=sections, path=rel)


def _entry_problems(entry: Entry, kb: KnowledgeBase) -> list[str]:
    problems = [f"Abschnitt „{s}“ fehlt" for s in REQUIRED_SECTIONS if not entry.sections.get(s)]
    problems += [
        f"Quelle {q} fehlt in quellen.yaml" for q in entry.head.quellen if q not in kb.sources
    ]
    if entry.id in kb.entries:
        problems.append(f"id {entry.id} doppelt")
    return problems


def _plan_type_problems(head: PlanTypeHead, kb: KnowledgeBase) -> list[str]:
    problems: list[str] = []
    expected: list[tuple[list[str], type[Any] | None]] = [
        (head.regeln, None),
        ([head.phasen], Phase),
        (head.zonen, Zonen),
        (head.tests, Test),
        (head.einheiten, Einheit),
    ]
    for refs, kind in expected:
        for ref in refs:
            entry = kb.entries.get(ref)
            if entry is None:
                problems.append(f"Referenz {ref} nicht auflösbar")
            elif kind is not None and not isinstance(entry.head.regel, kind):
                problems.append(f"Referenz {ref} ist kein {kind.__name__}-Eintrag")
    phases = kb.entries.get(head.phasen)
    if phases is not None and isinstance(phases.head.regel, Phase):
        for phase in phases.head.regel.phasen:
            problems += [
                f"Phase {phase.art}: Einheit {u} nicht im Plantyp"
                for u in phase.qualitaet
                if u not in head.einheiten
            ]
    return problems


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
        )
    return str(exc).splitlines()[0][:200]
