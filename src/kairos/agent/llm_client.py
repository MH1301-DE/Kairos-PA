from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.config import settings
from kairos.repositories.user_setting import get_or_default_user_setting


class NoLlmCredentialConfigured(Exception):
    """settings.llm_api_key is unset -- no LLM_API_KEY in the deployment's .env."""


async def get_completion(
    session: AsyncSession,
    *,
    user_id: UUID,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> litellm.types.utils.ModelResponse:
    # one Kairos deployment = one LLM API key, shared across every user of this
    # instance -- not a per-user credential like Garmin/Google Calendar (see
    # Settings.llm_api_key). Each user can still pick their own model.
    if not settings.llm_api_key:
        raise NoLlmCredentialConfigured("LLM_API_KEY is not configured for this deployment")

    setting = await get_or_default_user_setting(session, user_id=user_id)

    # litellm.completion is a synchronous, blocking call -- keep it off the event
    # loop, same pattern as GarminConnectBackend's blocking calls elsewhere
    response = await asyncio.to_thread(
        litellm.completion,
        model=setting.llm_model,
        messages=messages,
        tools=tools,
        api_key=settings.llm_api_key,
        stream=False,
    )
    return response  # type: ignore[no-any-return]


async def stream_completion(
    session: AsyncSession,
    *,
    user_id: UUID,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[Any]:
    if not settings.llm_api_key:
        raise NoLlmCredentialConfigured("LLM_API_KEY is not configured for this deployment")

    setting = await get_or_default_user_setting(session, user_id=user_id)
    stream: Any = await litellm.acompletion(
        model=setting.llm_model,
        messages=messages,
        tools=tools,
        api_key=settings.llm_api_key,
        stream=True,
    )
    async for chunk in stream:
        yield chunk
