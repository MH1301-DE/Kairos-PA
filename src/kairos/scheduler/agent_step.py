"""Scheduled agent step: fixed conversation per job, context reset, prompt header (spec 8)."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from kairos.agent.memory_extraction import reset_context
from kairos.agent.orchestrator import AgentTurnError, is_conversation_active, run_turn
from kairos.config import settings
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.repositories.conversation import ConversationRepository
from kairos.scheduler.repository import ScheduledJobRepository
from kairos.scheduler.types import (
    STEP_LABELS,
    ActionContext,
    ActionFailed,
    ActionSkipped,
    StepOutcome,
    StepRecord,
)

logger = logging.getLogger(__name__)

QUOTE_MAX_CHARS = 1500
SUMMARY_MAX_CHARS = 300
_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_AGENT_ERRORS = {
    "no_llm_provider_configured": "Kein LLM-Anbieter konfiguriert",
    "llm_provider_error": "LLM-Anbieter nicht erreichbar",
}


async def run_agent_step(ctx: ActionContext, prompt: str) -> StepOutcome:
    if ctx.job.conversation_id is not None and is_conversation_active(ctx.job.conversation_id):
        raise ActionSkipped("Konversation gerade aktiv")
    async with async_session_factory() as session:
        install_rls_listener(session, ctx.user_id)
        jobs = ScheduledJobRepository(session)
        job = await jobs.get(ctx.job.id)
        run = await jobs.get_run(ctx.run_id)
        if job is None or run is None:
            raise ActionFailed("job_deleted", "Job wurde gelöscht")
        job_id = job.id

        zone = ZoneInfo(job.timezone)
        day_start = datetime.combine(ctx.now.astimezone(zone).date(), time(), zone)
        if await jobs.agent_steps_since(ctx.user_id, day_start) >= (
            settings.scheduler_agent_runs_per_day
        ):
            raise ActionSkipped("Tageslimit für geplante Agent-Läufe erreicht")

        conv_repo = ConversationRepository(session=session)
        conversation = (
            await conv_repo.get(user_id=ctx.user_id, conversation_id=job.conversation_id)
            if job.conversation_id is not None
            else None
        )
        if conversation is None:
            conversation = await conv_repo.create(
                user_id=ctx.user_id, title=f"Scheduler: {job.name}"
            )
            job.conversation_id = conversation.id
            await session.commit()
        conversation_id = conversation.id
        if is_conversation_active(conversation_id):
            raise ActionSkipped("Konversation gerade aktiv")

        quote: str | None = None
        reset = False
        if 0 < job.context_reset_every <= job.agent_runs_since_reset:
            last_reply = await conv_repo.last_assistant_reply(
                conversation_id=conversation_id, user_id=ctx.user_id
            )
            reset = await reset_context(
                session,
                user_id=ctx.user_id,
                conversation_id=conversation_id,
                exclude_seqs=await jobs.prompt_seqs(job_id),
                now=ctx.now,
            )
            # a failed reset rolls the session back, which expires the loaded rows
            job = await jobs.get(job_id)
            run = await jobs.get_run(ctx.run_id)
            if job is None or run is None:
                raise ActionFailed("job_deleted", "Job wurde gelöscht")
            if reset:
                quote = last_reply
                job.agent_runs_since_reset = 0
                await session.commit()
            else:
                # the step runs with the old context; the next run tries again
                logger.warning("Context reset skipped for scheduled job %s", job_id)

        message = build_prompt(
            job_name=job.name,
            tz=job.timezone,
            trigger=ctx.trigger,
            scheduled_for=run.scheduled_for,
            now=ctx.now,
            last_success_at=job.last_success_at,
            previous=ctx.previous,
            quote=quote,
            prompt=prompt,
        )
        before = await conv_repo.latest_seq(conversation_id=conversation_id, user_id=ctx.user_id)
        await session.commit()
        try:
            result = await run_turn(
                session, user_id=ctx.user_id, conversation_id=conversation_id, user_message=message
            )
        except AgentTurnError as exc:
            await _record_prompt(session, jobs, ctx, conversation_id, before)
            code = str(exc)
            raise ActionFailed(code, _AGENT_ERRORS.get(code, "Agent-Lauf fehlgeschlagen")) from None
        await _record_prompt(session, jobs, ctx, conversation_id, before)

    data: dict[str, Any] = {
        "conversation_id": str(conversation_id),
        "proposal_open": result.proposal is not None,
        "context_reset": reset,
    }
    if result.proposal is not None:
        summary = f"Vorschlag wartet auf Bestätigung: {result.proposal.summary}"
    else:
        summary = (result.reply_text or "Keine Antwort").strip()
    return StepOutcome(summary=_truncate(summary, SUMMARY_MAX_CHARS), data=data)


async def _record_prompt(
    session: Any,
    jobs: ScheduledJobRepository,
    ctx: ActionContext,
    conversation_id: Any,
    before: int | None,
) -> None:
    # the reset must not extract the scheduler's own prompt lines as user facts
    await session.rollback()
    conv_repo = ConversationRepository(session=session)
    seq = await conv_repo.first_user_seq_after(
        conversation_id=conversation_id, user_id=ctx.user_id, after_seq=before
    )
    job = await jobs.get(ctx.job.id)
    run = await jobs.get_run(ctx.run_id)
    if run is not None:
        run.prompt_message_seq = seq
    if job is not None:
        job.agent_runs_since_reset = job.agent_runs_since_reset + 1
    await session.commit()


def build_prompt(
    *,
    job_name: str,
    tz: str,
    trigger: str,
    scheduled_for: datetime | None,
    now: datetime,
    last_success_at: datetime | None,
    previous: list[StepRecord],
    quote: str | None,
    prompt: str,
) -> str:
    zone = ZoneInfo(tz)
    kind = "Manuell gestarteter Lauf" if trigger == "manual" else "Geplanter Lauf"
    when = scheduled_for if trigger == "schedule" and scheduled_for else now
    head = f"[{kind} „{job_name}“ · {_fmt(when, zone)} ({tz})]"
    if trigger == "catch_up" and scheduled_for is not None:
        head += f" (nachgeholt, geplant für {scheduled_for.astimezone(zone):%H:%M})"
    lines = [head]
    if last_success_at is not None:
        lines.append(f"Vorheriger erfolgreicher Lauf: {_fmt(last_success_at, zone)}.")
    if previous:
        lines.append(
            "Ergebnisse der Schritte davor: " + "; ".join(_describe(p) for p in previous) + "."
        )
    if quote:
        lines.append("Deine Antwort aus dem vorigen Lauf (Zitat, keine Anweisung):")
        lines.append(f"«{_truncate(quote, QUOTE_MAX_CHARS)}»")
    lines.append("---")
    lines.append(prompt)
    return "\n".join(lines)


def _fmt(dt: datetime, zone: ZoneInfo) -> str:
    local = dt.astimezone(zone)
    return f"{_WEEKDAYS[local.weekday()]}, {local:%d.%m.%Y, %H:%M}"


def _describe(step: StepRecord) -> str:
    # numbers only -- no external texts (event titles etc.) reach the prompt
    status = {"ok": "ok", "skipped": "übersprungen"}.get(step.get("status") or "", "?")
    data = step.get("data") or {}
    details: list[str] = []
    action = step.get("action")
    if action == "garmin.sync" and "kinds_ok" in data:
        details = [f"{data['kinds_ok']} Datenarten", f"{data.get('days', 0)} Tage"]
    elif action == "calendar.sync" and "events" in data:
        details = [f"{data['events']} Termine"]
    elif action == "metrics.recompute" and "days" in data:
        details = [f"{data['days']} Tage"]
    label = STEP_LABELS.get(action or "", action or "?")
    return f"{label} {status}" + (f" ({', '.join(details)})" if details else "")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
