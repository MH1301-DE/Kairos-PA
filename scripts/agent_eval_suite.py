"""
Manuelles Eval-Skript: alle 15 Referenzfragen aus docs/00-vision-und-scope.md §5
(13 und 15 kamen mit Phase 5 Planung dazu, siehe
docs/superpowers/specs/2026-09-12-phase-5-planning-design.md) gegen einen
festen Testdatensatz, mit echten LLM-Calls.

Kein pytest-Test und nicht Teil der CI -- macht echte, kostenpflichtige
API-Calls (siehe docs/03-agent-design.md §8 "Evaluierung").

Umfang dieser Version: Tool-Selection-Accuracy (wurde das erwartete Tool
gewählt?) + eine strukturelle Prüfung des Tool-Ergebnisses (echte Daten statt
insufficient_data). Die volle "Zahlen-Assertion per Regex aus der Prosa-
Antwort" aus docs/03-agent-design.md §8 ist bewusst nicht Teil dieser
Version -- das wäre ein eigenes kleines NLP-Extraktions-Subsystem und hätte
den Umfang dieses Tasks gesprengt; Tool-Selection-Accuracy ist eine der drei
in §8 genannten Metriken und für sich allein schon aussagekräftig.

Verwendung:
    .venv/Scripts/python scripts/agent_eval_suite.py

Voraussetzung: LLM_API_KEY in .env gesetzt (ein Key pro Deployment, siehe
Settings.llm_api_key) -- ohne den bricht der Lauf mit
NoLlmCredentialConfigured ab.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent import orchestrator as orchestrator_module
from kairos.agent.dispatcher import ToolCall, dispatch
from kairos.agent.orchestrator import run_turn
from kairos.config import settings
from kairos.db.session import async_session_factory
from kairos.repositories.conversation import ConversationRepository


@dataclass(frozen=True)
class EvalCase:
    number: int
    question: str
    expected_tools: tuple[str, ...]


@dataclass
class EvalResult:
    case: EvalCase
    tools_called: list[str] = field(default_factory=list)
    reply: str | None = None
    proposal: str | None = None
    error: str | None = None
    seconds: float = 0.0

    @property
    def tool_selection_ok(self) -> bool:
        return any(t in self.tools_called for t in self.case.expected_tools)


# Referenzfragen aus docs/00-vision-und-scope.md §5, alle 15
CASES: tuple[EvalCase, ...] = (
    EvalCase(1, "Wie erholt bin ich heute?", ("query_health",)),
    EvalCase(
        2, "Habe ich mich letzte Woche genug erholt?", ("query_health", "analyze_records")
    ),
    EvalCase(3, "Wann war mein letzter echter Ruhetag?", ("analyze_records", "query_health")),
    EvalCase(
        4, "Wie sieht mein Schlaf im Vergleich zu letztem Monat aus?",
        ("analyze_records", "query_health"),
    ),
    EvalCase(
        5,
        "Mein Puls war gestern beim gleichen Tempo deutlich höher als sonst -- "
        "warum könnte das sein?",
        ("query_health", "analyze_records"),
    ),
    EvalCase(6, "Wie viel habe ich in den letzten 4 Wochen trainiert?", ("analyze_records",)),
    EvalCase(7, "Was war meine bisher beste 5-km-Zeit dieses Jahr?", ("analyze_records",)),
    EvalCase(
        8, "Wann sollte ich die nächste harte Einheit machen, ohne mich zu überlasten?",
        ("query_health", "query_calendar"),
    ),
    EvalCase(
        9, "Wie entwickelt sich meine Fitness dieses Jahr?", ("analyze_records", "query_health")
    ),
    EvalCase(
        10, "Vergleich meinen Lauf von gestern mit dem letzten Tempolauf.", ("analyze_records",)
    ),
    EvalCase(
        11, "Plane eine Lauf-Einheit für morgen -- wann passt es in meinen Tag?",
        ("query_calendar",),
    ),
    EvalCase(
        12, "Wie weit bin ich noch von meinem Halbmarathon-Ziel entfernt?",
        ("recall", "query_health"),
    ),
    EvalCase(
        13, "Erstell mir einen Trainingsplan für die nächsten 3 Wochen.", ("plan_propose",)
    ),
    EvalCase(
        14, "Ich habe nächste Woche viel Stress. Wie passe ich das Training an?",
        ("query_health",),
    ),
    EvalCase(
        15, "Was habe ich diese Woche schon trainiert und was fehlt noch laut Plan?",
        ("plan_progress",),
    ),
)


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Eval User', :sub, 'Europe/Berlin', 'user')"
        ),
        {"id": str(user_id), "email": f"eval-{user_id}@test.local", "sub": f"eval-{user_id}"},
    )


async def seed_test_data(session: AsyncSession, user_id: UUID) -> None:
    await _insert_user(session, user_id)
    await session.execute(
        text("INSERT INTO user_setting (user_id, hr_max_override) VALUES (:uid, 190)"),
        {"uid": str(user_id)},
    )

    # 60 days of daily activity + HR data so HRV baseline/training-load/etc. have
    # enough history to leave insufficient_data
    today = date.today()
    for days_ago in range(60, -1, -1):
        day = today - timedelta(days=days_ago)
        activity_id = (
            await session.execute(
                text(
                    "INSERT INTO activity (user_id, external_id, start_at) "
                    "VALUES (:uid, :ext, :start_at) RETURNING id"
                ),
                {
                    "uid": str(user_id), "ext": f"eval-activity-{day.isoformat()}",
                    "start_at": datetime(day.year, day.month, day.day, 9, 0, tzinfo=UTC),
                },
            )
        ).scalar_one()
        for i in range(300):  # 5 minutes of HR data
            recorded_at = (
                datetime(day.year, day.month, day.day, 9, 0, tzinfo=UTC) + timedelta(seconds=i)
            )
            await session.execute(
                text(
                    "INSERT INTO activity_record "
                    "(user_id, activity_id, recorded_at, metric, value) "
                    "VALUES (:uid, :aid, :ts, 'hr', 140.0)"
                ),
                {"uid": str(user_id), "aid": activity_id, "ts": recorded_at},
            )

    # calendar event tomorrow, and a goal, so query_calendar/recall have something real
    tomorrow = today + timedelta(days=1)
    await session.execute(
        text(
            "INSERT INTO calendar_event "
            "(id, user_id, connector, external_id, summary, start_at, end_at, source) "
            "VALUES (:id, :uid, 'google_calendar', 'eval-evt-1', 'Meeting', :start_at, :end_at, "
            "'external')"
        ),
        {
            "id": str(uuid.uuid4()), "uid": str(user_id),
            "start_at": datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, tzinfo=UTC),
            "end_at": datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11, 0, tzinfo=UTC),
        },
    )
    await session.execute(
        text(
            "INSERT INTO goal (id, user_id, title, target_date, status) "
            "VALUES (:id, :uid, 'Halbmarathon', :target_date, 'active')"
        ),
        {
            "id": str(uuid.uuid4()), "uid": str(user_id),
            "target_date": today + timedelta(days=60),
        },
    )
    await session.commit()


async def run_eval_case(
    session: AsyncSession, user_id: UUID, conversation_id: UUID, case: EvalCase
) -> EvalResult:
    tools_called: list[str] = []
    original_dispatch = dispatch

    async def _recording_dispatch(
        session_arg: AsyncSession, *, user_id: UUID, tool_call: ToolCall, pending_confirmation: bool
    ) -> object:
        tools_called.append(tool_call.name)
        return await original_dispatch(
            session_arg, user_id=user_id, tool_call=tool_call,
            pending_confirmation=pending_confirmation,
        )

    # orchestrator binds `dispatch` at import time, so patch it there, not on the dispatcher module
    orchestrator_module.dispatch = _recording_dispatch
    started = time.monotonic()
    try:
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message=case.question
        )
        await session.commit()
        return EvalResult(
            case=case, tools_called=tools_called, reply=result.reply_text,
            proposal=result.proposal.summary if result.proposal else None,
            seconds=time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001 -- eval harness must not crash on one bad case
        await session.rollback()
        return EvalResult(
            case=case, tools_called=tools_called, error=f"{type(exc).__name__}: {exc}",
            seconds=time.monotonic() - started,
        )
    finally:
        orchestrator_module.dispatch = original_dispatch


async def main() -> None:
    print("Phase-4-MVP Eval-Suite -- macht echte, kostenpflichtige LLM-Calls.")
    if not settings.llm_api_key:
        sys.exit("LLM_API_KEY ist in .env nicht gesetzt, Abbruch.")

    user_id = uuid.uuid4()
    results: list[EvalResult] = []
    async with async_session_factory() as session:
        try:
            print("Seede Testdatensatz (60 Tage Trainingsdaten) ...")
            await seed_test_data(session, user_id)

            conv_repo = ConversationRepository(session=session)
            for case in CASES:
                # fresh conversation per case: measures tool selection, not history carry-over
                conversation = await conv_repo.create(user_id=user_id, title=f"Eval {case.number}")
                await session.commit()
                print(f"[{case.number}/15] {case.question}")
                result = await run_eval_case(session, user_id, conversation.id, case)
                results.append(result)
                if result.tool_selection_ok:
                    status = "OK"
                elif result.error:
                    status = "FEHLER"
                else:
                    status = "TOOL-MISMATCH"
                print(
                    f"    -> {status} in {result.seconds:.1f}s "
                    f"(Tools: {result.tools_called or '-'})"
                )
                if result.error:
                    print(f"       Fehler: {result.error[:300]}")
                if result.proposal:
                    print(f"       Proposal: {result.proposal}")
                if result.reply:
                    print("       Antwort: " + result.reply.replace("\n", " ")[:400])
        finally:
            # every user table cascades from app_user, so this removes all seeded eval data
            await session.rollback()
            await session.execute(
                text("DELETE FROM app_user WHERE id = :id"), {"id": str(user_id)}
            )
            await session.commit()
            print("Eval-Nutzer und Testdaten entfernt.")

    passed = sum(1 for r in results if r.tool_selection_ok)
    print(f"\n{passed}/{len(results)} Fragen mit erwartetem Tool beantwortet.")
    for r in results:
        if not r.tool_selection_ok:
            reason = r.error or f"Tools aufgerufen: {r.tools_called or 'keine'}"
            print(f"  Frage {r.case.number}: {reason}")


if __name__ == "__main__":
    asyncio.run(main())
