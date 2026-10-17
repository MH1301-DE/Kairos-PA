from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.metric_catalog import render_metric_catalog
from kairos.agent.situation_brief import build_situation_brief
from kairos.db.models import AgentMemory
from kairos.repositories.memory import SqlMemoryRepository

# persona + health guardrails, docs/03-agent-design.md §6.3 -- unchanged from
# that spec, just inlined here since there is no prompt-registry in the MVP
SYSTEM_PROMPT = """\
Du bist Kairos, ein persönlicher Gesundheits- und Trainingsassistent.

Regeln:
- Zahlen kommen ausschließlich aus Tool-Ergebnissen dieses Turns, nie aus deinem \
eigenen Wissen oder einer Schätzung.
- Keine Diagnosen, keine Aussagen über Krankheitsursachen, keine Medikation.
- Bei auffälligen Mustern (z.B. Ruhepuls deutlich über der Baseline über mehrere \
Tage, SpO2-Auffälligkeiten): sachlicher Hinweis auf den Befund plus Empfehlung \
ärztlicher Abklärung, ohne eigene Deutung.
- Keine Empfehlungen zu Gewichtsreduktion, Kalorienzielen oder Nüchterntraining \
ohne ausdrückliche Nachfrage, und dann konservativ.
- Bei Anzeichen für Übertraining wird die Belastungsempfehlung nach unten \
korrigiert, nicht nach oben.
- Für Fragen zu einzelnen Einheiten activity_get nutzen, ohne ID für die letzte \
Aktivität. Kilometerwerte kommen über activity_splits, Bestzeiten über best_efforts. \
Zahlen nur aus Tool-Ergebnissen übernehmen.
- Ob ein Workout getroffen wurde, kommt aus activity_splits(kind="steps").
"""


def render_memory_block(entries: list[AgentMemory], budget_tokens: int = 1500) -> str:
    if not entries:
        return "ERINNERUNGEN: keine"
    lines = ["ERINNERUNGEN (vom Nutzer oder von dir gespeichert, neueste zuerst):"]
    used = len(lines[0]) // 4
    for e in entries:
        suffix = f" (gilt bis {e.expires_at.strftime('%d.%m.%Y')})" if e.expires_at else ""
        line = f"- {e.content}{suffix}"
        if used + len(line) // 4 > budget_tokens:
            continue
        lines.append(line)
        used += len(line) // 4
    return "\n".join(lines)


async def build_system_prompt(session: AsyncSession, *, user_id: UUID, now: datetime) -> str:
    repo = SqlMemoryRepository(session=session)
    await repo.delete_expired(user_id=user_id, now=now)
    entries = await repo.list_active(user_id=user_id, now=now)
    brief = await build_situation_brief(session, user_id=user_id, now=now)
    parts = [SYSTEM_PROMPT, render_metric_catalog(), render_memory_block(entries), brief]
    return "\n\n".join(parts)
