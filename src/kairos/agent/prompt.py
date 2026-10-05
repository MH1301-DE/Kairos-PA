from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.metric_catalog import render_metric_catalog
from kairos.agent.situation_brief import build_situation_brief

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
"""


async def build_system_prompt(session: AsyncSession, *, user_id: UUID, now: datetime) -> str:
    brief = await build_situation_brief(session, user_id=user_id, now=now)
    return "\n\n".join([SYSTEM_PROMPT, render_metric_catalog(), brief])
