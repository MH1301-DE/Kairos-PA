from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from kairos.agent.prompt import SYSTEM_PROMPT, render_memory_block
from kairos.db.models import AgentMemory


def _entry(content: str, expires_at: datetime | None = None) -> AgentMemory:
    return AgentMemory(
        id=uuid4(), user_id=uuid4(), content=content, source="agent", expires_at=expires_at
    )


def test_memory_block_lists_entries_with_expiry_and_respects_budget() -> None:
    entries = [
        _entry("Ziel: Halbmarathon"),
        _entry("Viel Stress", datetime(2026, 10, 11, 23, 59, 59, tzinfo=UTC)),
    ]
    block = render_memory_block(entries)
    assert block.startswith("ERINNERUNGEN")
    assert "- Ziel: Halbmarathon" in block
    assert "- Viel Stress (gilt bis 11.10.2026)" in block
    many = [_entry("x" * 400) for _ in range(50)]
    assert len(render_memory_block(many, budget_tokens=300)) // 4 <= 300


def test_empty_memory_block() -> None:
    assert render_memory_block([]) == "ERINNERUNGEN: keine"


def test_oversized_newer_entry_does_not_hide_older_ones() -> None:
    block = render_memory_block([_entry("x" * 8000), _entry("Ziel: Halbmarathon")],
                                budget_tokens=300)
    assert "- Ziel: Halbmarathon" in block
    assert "x" * 100 not in block


def test_system_prompt_names_the_activity_read_tools() -> None:
    # spec G.5, first two points
    flat = " ".join(SYSTEM_PROMPT.split())
    assert (
        "Für Fragen zu einzelnen Einheiten activity_get nutzen, ohne ID für die letzte "
        "Aktivität. Kilometerwerte kommen über activity_splits, Bestzeiten über best_efforts."
    ) in flat
    assert 'Ob ein Workout getroffen wurde, kommt aus activity_splits(kind="steps").' in flat
    # eval 20: without this the model compared two activity_get results by hand
    assert 'activity_analyze(operation="compare")' in flat
