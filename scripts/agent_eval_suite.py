"""
Manuelles Eval-Skript: alle 15 Referenzfragen aus docs/00-vision-und-scope.md §5 plus
Fall 16 (Proposal-Dialog) (13 und 15 kamen mit Phase 5 Planung dazu, siehe
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

Fälle 17-21 und 26 (Aktivitäts-Lese-Tools, Spec 2026-10-07 §12.1) brauchen echte
Aktivitäten mit Splits, Schwimmen und Workout-Schritten und laufen deshalb gegen einen
bestehenden Nutzer (--user-id), ohne Seed. Schreibende Tools sind in diesem Modus
gesperrt, die Eval-Konversationen werden am Ende gelöscht. Zusätzlich prüft
numbers_match, ob die Kennzahlen aus der summary des erwarteten Tools wörtlich in der
Antwort stehen.

Verwendung:
    .venv/Scripts/python scripts/agent_eval_suite.py
    .venv/Scripts/python scripts/agent_eval_suite.py --cases 17,18,19,20,21,26 --user-id <uuid>

Voraussetzung: LLM_API_KEY in .env gesetzt (ein Key pro Deployment, siehe
Settings.llm_api_key) -- ohne den bricht der Lauf mit
NoLlmCredentialConfigured ab.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import StreamSet
from kairos.agent import tools as tools_module
from kairos.agent.dispatcher import Proposal, ToolCall, dispatch
from kairos.agent.events import AgentEvent
from kairos.agent.history import tool_result
from kairos.agent.orchestrator import stream_continuation, stream_turn
from kairos.config import settings
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.repositories.conversation import ConversationRepository
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_metric_daily_values,
    recompute_wellness_daily_stats,
)


@dataclass(frozen=True)
class NumberCheck:
    tool: str
    # each pattern has one group, matched against that tool's summary
    patterns: tuple[str, ...]
    # one of these words must appear in the reply
    note_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalCase:
    number: int
    question: str
    expected_tools: tuple[str, ...]
    numbers: NumberCheck | None = None


@dataclass
class EvalResult:
    case: EvalCase
    tools_called: list[str] = field(default_factory=list)
    reply: str | None = None
    proposal: str | None = None
    error: str | None = None
    seconds: float = 0.0
    ttft: float | None = None
    tool_summaries: dict[str, list[str]] = field(default_factory=dict)

    @property
    def tool_selection_ok(self) -> bool:
        return any(t in self.tools_called for t in self.case.expected_tools)

    def numbers_match(self) -> tuple[bool, list[str]]:
        check = self.case.numbers
        if check is None:
            return True, []
        problems: list[str] = []
        summaries = self.tool_summaries.get(check.tool, [])
        reply = self.reply or ""
        for pattern in check.patterns:
            token = next(
                (m.group(1) for text in reversed(summaries) if (m := re.search(pattern, text))),
                None,
            )
            if token is None:
                problems.append(f"Muster {pattern!r} nicht in {check.tool}-summary")
            elif not _token_in_reply(token, reply):
                problems.append(f"{token!r} fehlt in der Antwort")
        if check.note_any and not any(w.lower() in reply.lower() for w in check.note_any):
            problems.append(f"kein Hinweis ({' / '.join(check.note_any)})")
        return not problems, problems


def _token_in_reply(token: str, reply: str) -> bool:
    if token in reply:
        return True
    if m := re.fullmatch(r"(\d+)/(\d+)", token):
        return f"{m[1]} von {m[2]}" in reply
    if m := re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", token):
        short = f"{int(m[1])}.{int(m[2])}.{m[3]}"
        return short in reply or f"{m[1]}.{m[2]}." in reply
    return False


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

# spec 2026-10-07 §12.1; numbers come from the expected tool's summary (Q4: real data)
ACTIVITY_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        17, "Wie war mein letzter Lauf?", ("activity_get",),
        NumberCheck(
            "activity_get",
            (r"(\d+,\d{2}) km in", r"\(Ø (\d+:\d{2}) /km\)", r"Ø-HF (\d+)"),
        ),
    ),
    EvalCase(
        18, "Zeig mir die Kilometerzeiten meines letzten Laufs.", ("activity_splits",),
        NumberCheck(
            "activity_splits",
            (
                r"Schnellster km \d+ \((\d+:\d{2}) /km\)",
                r"langsamster km \d+ \((\d+:\d{2}) /km\)",
            ),
        ),
    ),
    EvalCase(
        19, "Was war meine beste 5-km-Zeit dieses Jahr?", ("best_efforts",),
        NumberCheck(
            "best_efforts",
            (r"5 km (\d+:\d{2}(?::\d{2})?) \(", r"5 km [\d:]+ \((\d{2}\.\d{2}\.\d{4})"),
        ),
    ),
    EvalCase(
        20, "Vergleich meinen Lauf von gestern mit dem letzten Tempolauf.",
        ("activity_analyze",),
        NumberCheck(
            "activity_analyze",
            (r"war (\d+:\d{2}) /km (?:schneller|langsamer)", r"bei (\d+) Schlägen"),
        ),
    ),
    EvalCase(
        21, "Wie lief meine letzte Schwimmeinheit?", ("activity_get",),
        NumberCheck(
            "activity_get",
            (r"\(Ø (\d+:\d{2}) /100 m\)",),
            note_any=("Handgelenk", "verlässlich", "ungenau", "eingeschränkt"),
        ),
    ),
    EvalCase(
        26, "Habe ich bei meiner letzten Schwelle die Intervalle getroffen?",
        ("activity_splits",),
        NumberCheck(
            "activity_splits",
            (
                r"Intervalle (\d+/\d+) im",
                r"Intervalle \d+/\d+ im Zielbereich \(Ø (\d+:\d{2}) /km\)",
            ),
        ),
    ),
)

_CREATE_EVENT_ATTR = "_create_calendar_event"  # patched in tools' namespace
FOLLOW_UP_QUESTION = "Danke, und wie erholt bin ich?"
PROPOSAL_CASE = EvalCase(
    16, "Trag mir morgen um 7 Uhr einen lockeren Lauf von 45 Minuten ein.",
    ("propose_calendar_event",),
)


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Eval User', :sub, 'Europe/Berlin', 'user')"
        ),
        {"id": str(user_id), "email": f"eval-{user_id}@test.local", "sub": f"eval-{user_id}"},
    )


_SEED_DAYS = 60


async def _seed_history(session: AsyncSession, user_id: UUID, today: date) -> None:
    uid = str(user_id)
    # inert connection row: tools check for an active garmin connection, nothing decrypts it here
    await session.execute(
        text(
            "INSERT INTO connection (id, user_id, connector, external_account, status, "
            "credentials_enc, config) "
            "VALUES (:id, :uid, 'garmin', 'eval', 'active', :cred, '{}'::jsonb)"
        ),
        {"id": str(uuid.uuid4()), "uid": uid, "cred": b"eval-dummy"},
    )
    activities: list[dict[str, object]] = []
    wellness_hr: list[dict[str, object]] = []
    wellness_hrv: list[dict[str, object]] = []
    sleeps: list[dict[str, object]] = []
    for days_ago in range(_SEED_DAYS, -1, -1):
        day = today - timedelta(days=days_ago)
        at = datetime(day.year, day.month, day.day, tzinfo=UTC)
        activities.append(
            {"uid": uid, "ext": f"eval-activity-{day.isoformat()}", "start_at": at.replace(hour=9)}
        )
        # hrv_baseline/resting_hr_trend read wellness_daily_stats (hrv_5min, hr), not activity data
        wellness_hrv.append({"uid": uid, "ts": at.replace(hour=3), "v": 55.0 + (days_ago * 7) % 11})
        for hour, bpm in ((3, 50.0 + days_ago % 4), (12, 70.0), (18, 82.0)):
            wellness_hr.append({"uid": uid, "ts": at.replace(hour=hour), "v": bpm})
        sleeps.append(
            {
                "uid": uid, "ext": f"eval-sleep-{day.isoformat()}",
                "start_at": at.replace(minute=30), "end_at": at.replace(hour=7, minute=30),
                "dur": 25200 + (days_ago % 3) * 900,
            }
        )
    await session.execute(
        text(
            "INSERT INTO activity (user_id, external_id, start_at) "
            "VALUES (:uid, :ext, :start_at)"
        ),
        activities,
    )
    ids = {
        row[0]: row[1]
        for row in (
            await session.execute(
                text("SELECT external_id, id FROM activity WHERE user_id = :uid"), {"uid": uid}
            )
        ).all()
    }
    for item in activities:
        start_at = item["start_at"]
        assert isinstance(start_at, datetime)
        # 5 minutes of HR data -> hr_bucket_seconds_daily / TRIMP
        await replace_streams(
            session,
            user_id=user_id,
            activity_id=ids[str(item["ext"])],
            streams=StreamSet(
                start_at=start_at,
                t_offset_s=list(range(300)),
                channels={"hr": [140.0] * 300},
                source="fit_zip",
            ),
            algo_version=STREAM_ALGO_VERSION,
        )
    for code, rows in (("hr", wellness_hr), ("hrv_5min", wellness_hrv)):
        await session.execute(
            text(
                "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
                "SELECT :uid, id, :ts, :v FROM metric_def WHERE code = '" + code + "'"
            ),
            rows,
        )
    await session.execute(
        text(
            "INSERT INTO sleep_session (user_id, external_id, start_at, end_at, duration_seconds) "
            "VALUES (:uid, :ext, :start_at, :end_at, :dur)"
        ),
        sleeps,
    )
    await session.commit()


async def seed_test_data(session: AsyncSession, user_id: UUID) -> None:
    install_rls_listener(session, user_id)
    await _insert_user(session, user_id)
    await session.execute(
        text(  # sex is required by the Banister TRIMP variant
            "INSERT INTO user_setting (user_id, hr_max_override, sex) VALUES (:uid, 190, 'male')"
        ),
        {"uid": str(user_id)},
    )
    today = date.today()
    await _seed_history(session, user_id, today)

    # variants read these aggregates, so they must be rebuilt after the raw rows exist
    start = today - timedelta(days=_SEED_DAYS)
    await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=start, end=today)
    await recompute_wellness_daily_stats(session, user_id=user_id, start=start, end=today)
    await session.commit()
    await recompute_metric_daily_values(session, user_id=user_id, start=start, end=today)
    await session.commit()

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


async def _drain(
    stream: AsyncIterator[AgentEvent], result: EvalResult, started: float
) -> dict[str, Any] | None:
    # returns the proposal event data (if any); reply keeps only the final round's text
    proposal: dict[str, Any] | None = None
    parts: list[str] = []
    async for event in stream:
        if event.type == "token":
            if result.ttft is None:
                result.ttft = time.monotonic() - started
            parts.append(event.data["text"])
        elif event.type == "tool_start":
            result.tools_called.append(event.data["name"])
            parts = []
        elif event.type == "tool_end":
            result.tool_summaries.setdefault(event.data["name"], []).append(
                str(event.data.get("summary") or "")
            )
        elif event.type == "proposal":
            proposal = event.data
            result.tools_called.append(event.data["tool_name"])
            result.proposal = event.data["summary"]
        elif event.type == "error":
            result.error = str(event.data.get("detail"))
    if parts:
        result.reply = "".join(parts)
    return proposal


async def run_eval_case(
    session: AsyncSession, user_id: UUID, conversation_id: UUID, case: EvalCase
) -> EvalResult:
    result = EvalResult(case=case)
    started = time.monotonic()
    try:
        await _drain(
            stream_turn(
                session, user_id=user_id, conversation_id=conversation_id,
                user_message=case.question,
            ),
            result, started,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 -- eval harness must not crash on one bad case
        await session.rollback()
        result.error = f"{type(exc).__name__}: {exc}"
    result.seconds = time.monotonic() - started
    return result


async def _fake_create_calendar_event(
    session: AsyncSession, user_id: UUID, req: Any
) -> dict[str, Any]:
    # same shape as routers.calendar._event_to_dict; no real Google write in the eval
    return {
        "id": str(uuid.uuid4()), "summary": req.summary, "description": req.description,
        "location": None, "start_at": req.start_at.isoformat(), "end_at": req.end_at.isoformat(),
        "all_day": False, "status": "confirmed", "source": "kairos",
    }


async def _confirm_proposal(
    session: AsyncSession, repo: ConversationRepository, *, user_id: UUID,
    conversation_id: UUID, tool_call_id: str,
) -> str | None:
    # mirrors the /confirm endpoint; returns an error text or None
    call = await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id=tool_call_id
    )
    if call is None:
        return "Tool-Call des Proposals nicht gefunden"
    original = getattr(tools_module, _CREATE_EVENT_ATTR)
    setattr(tools_module, _CREATE_EVENT_ATTR, _fake_create_calendar_event)
    try:
        executed = await dispatch(
            session, user_id=user_id,
            tool_call=ToolCall(
                name=call["name"], arguments=json.loads(call["arguments"] or "{}"),
                id=tool_call_id,
            ),
            pending_confirmation=True,
        )
    except Exception as exc:  # noqa: BLE001 -- the endpoint stores the failure as the result
        executed = tool_result(f"Fehler: {exc}")
    finally:
        setattr(tools_module, _CREATE_EVENT_ATTR, original)
    if isinstance(executed, Proposal):
        return "unerwartetes Proposal beim Bestätigen"
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="tool",
        content=json.dumps(executed, ensure_ascii=False), tool_call_id=tool_call_id,
    )
    await session.commit()
    return None


async def run_proposal_case(
    session: AsyncSession, user_id: UUID, conversation_id: UUID, case: EvalCase
) -> EvalResult:
    """Proposal, confirm, continuation and a follow-up turn in one conversation."""
    result = EvalResult(case=case)
    started = time.monotonic()
    repo = ConversationRepository(session=session)
    try:
        proposal = await _drain(
            stream_turn(
                session, user_id=user_id, conversation_id=conversation_id,
                user_message=case.question,
            ),
            result, started,
        )
        await session.commit()
        if proposal is None:
            result.error = result.error or "kein proposal-Event erhalten"
            return result
        confirm_error = await _confirm_proposal(
            session, repo, user_id=user_id, conversation_id=conversation_id,
            tool_call_id=proposal["tool_call_id"],
        )
        if confirm_error:
            result.error = confirm_error
            return result

        continuation = EvalResult(case=case)
        await _drain(
            stream_continuation(session, user_id=user_id, conversation_id=conversation_id),
            continuation, time.monotonic(),
        )
        await session.commit()
        if continuation.error or not continuation.reply:
            result.error = continuation.error or "leere Antwort nach Bestätigung"
            return result
        result.reply = continuation.reply

        # regression check for the history bug: the follow-up replays the whole proposal history
        follow_up = EvalResult(case=case)
        await _drain(
            stream_turn(
                session, user_id=user_id, conversation_id=conversation_id,
                user_message=FOLLOW_UP_QUESTION,
            ),
            follow_up, time.monotonic(),
        )
        await session.commit()
        result.tools_called.extend(follow_up.tools_called)
        if follow_up.error:
            result.error = f"Folgefrage: {follow_up.error}"
        elif "query_health" not in follow_up.tools_called:
            result.error = f"Folgefrage ohne query_health (Tools: {follow_up.tools_called or '-'})"
        else:
            result.reply = follow_up.reply
    except Exception as exc:  # noqa: BLE001 -- eval harness must not crash on one bad case
        await session.rollback()
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.seconds = time.monotonic() - started
    return result


async def _blocked_write(session: AsyncSession, **kwargs: Any) -> dict[str, Any]:
    del session, kwargs
    blocked: dict[str, Any] = tool_result("Eval-Modus: schreibende Tools sind gesperrt.")
    return blocked


def _block_write_tools() -> None:
    # real-user mode must not change data; read tools stay untouched
    for name, spec in list(tools_module.TOOLS_BY_NAME.items()):
        if spec.risk_class != "read":
            tools_module.TOOLS_BY_NAME[name] = replace(spec, handler=_blocked_write)


def _status(result: EvalResult) -> str:
    if result.error:
        return "FEHLER"
    if not result.tool_selection_ok:
        return "TOOL-MISMATCH"
    return "OK" if result.numbers_match()[0] else "ZAHLEN-MISMATCH"


def _print_result(result: EvalResult) -> None:
    ttft = f"{result.ttft:.1f}s" if result.ttft is not None else "-"
    print(
        f"    -> {_status(result)} in {result.seconds:.1f}s, TTFT {ttft} "
        f"(Tools: {result.tools_called or '-'})"
    )
    if result.error:
        print(f"       Fehler: {result.error[:300]}")
    for problem in result.numbers_match()[1]:
        print(f"       Zahlen: {problem}")
    if result.proposal:
        print(f"       Proposal: {result.proposal}")
    if result.reply:
        print("       Antwort: " + result.reply.replace("\n", " ")[:400])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent-Eval-Suite mit echten LLM-Calls")
    parser.add_argument("--cases", help="kommagetrennte Fallnummern, z.B. 17,18,19")
    parser.add_argument(
        "--user-id", type=UUID, help="bestehender Nutzer, nur für die Fälle 17-21 und 26"
    )
    return parser.parse_args()


def _select_cases(args: argparse.Namespace) -> tuple[EvalCase, ...]:
    pool = ACTIVITY_CASES if args.user_id else (*CASES, PROPOSAL_CASE)
    if not args.cases:
        return pool
    wanted = {int(n) for n in args.cases.split(",")}
    unknown = wanted - {c.number for c in pool}
    if unknown:
        mode = "mit --user-id nur 17-21, 26" if args.user_id else "ohne --user-id nur 1-16"
        sys.exit(f"Fälle {sorted(unknown)} nicht verfügbar ({mode}).")
    return tuple(c for c in pool if c.number in wanted)


async def main() -> None:
    args = _parse_args()
    print("Agent-Eval-Suite -- macht echte, kostenpflichtige LLM-Calls.")
    if not settings.llm_api_key:
        sys.exit("LLM_API_KEY ist in .env nicht gesetzt, Abbruch.")

    real_user: UUID | None = args.user_id
    user_id = real_user or uuid.uuid4()
    all_cases = _select_cases(args)
    if real_user:
        _block_write_tools()
    results: list[EvalResult] = []
    conversation_ids: list[UUID] = []
    async with async_session_factory() as session:
        try:
            if real_user:
                print(f"Nutzer {real_user}: echte Daten, ohne Seed, Schreib-Tools gesperrt.")
                install_rls_listener(session, real_user)
            else:
                print("Seede Testdatensatz (60 Tage Trainings-, Schlaf- und Wellnessdaten) ...")
                await seed_test_data(session, user_id)

            conv_repo = ConversationRepository(session=session)
            for i, case in enumerate(all_cases, start=1):
                # fresh conversation per case: measures tool selection, not history carry-over
                conversation = await conv_repo.create(user_id=user_id, title=f"Eval {case.number}")
                conversation_ids.append(conversation.id)
                await session.commit()
                print(f"[{case.number}] ({i}/{len(all_cases)}) {case.question}")
                runner = run_proposal_case if case is PROPOSAL_CASE else run_eval_case
                result = await runner(session, user_id, conversation.id, case)
                results.append(result)
                _print_result(result)
        finally:
            await session.rollback()
            if real_user:
                await session.execute(
                    text("DELETE FROM conversation WHERE id = ANY(:ids)"),
                    {"ids": conversation_ids},
                )
                print(f"{len(conversation_ids)} Eval-Konversationen entfernt.")
            else:
                # every user table cascades from app_user, so this removes all seeded eval data
                await session.execute(
                    text("DELETE FROM app_user WHERE id = :id"), {"id": str(user_id)}
                )
                print("Eval-Nutzer und Testdaten entfernt.")
            await session.commit()

    passed = sum(1 for r in results if r.tool_selection_ok and not r.error)
    print(f"\n{passed}/{len(results)} Fragen fehlerfrei mit erwartetem Tool (Tool-Accuracy).")
    checked = [r for r in results if r.case.numbers is not None]
    if checked:
        exact = sum(1 for r in checked if r.numbers_match()[0])
        print(f"{exact}/{len(checked)} Antworten mit exakten Zahlen (numbers_match).")
    ttfts = [r.ttft for r in results if r.ttft is not None]
    if ttfts:
        print(f"Median TTFT: {statistics.median(ttfts):.1f}s")
    if results:
        print(f"Median Gesamtzeit: {statistics.median(r.seconds for r in results):.1f}s")
    for r in results:
        if _status(r) == "OK":
            continue
        if r.error or not r.tool_selection_ok:
            reason = r.error or f"Tools aufgerufen: {r.tools_called or 'keine'}"
        else:
            reason = "; ".join(r.numbers_match()[1])
        print(f"  Frage {r.case.number}: {reason}")


if __name__ == "__main__":
    asyncio.run(main())
