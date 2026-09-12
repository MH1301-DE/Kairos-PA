from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import decrypt, kek_from_settings, unwrap_dek
from kairos.config import settings
from kairos.db.models import AppUser, Connection
from kairos.repositories.user_setting import get_or_default_user_setting


class NoLlmCredentialConfigured(Exception):
    """No connection row with connector='llm_provider' exists for this user yet."""


async def get_completion(
    session: AsyncSession,
    *,
    user_id: UUID,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> litellm.types.utils.ModelResponse:
    setting = await get_or_default_user_setting(session, user_id=user_id)
    api_key = await _load_llm_api_key(session, user_id=user_id)

    # litellm.completion is a synchronous, blocking call -- keep it off the event
    # loop, same pattern as GarminConnectBackend's blocking calls elsewhere
    response = await asyncio.to_thread(
        litellm.completion,
        model=setting.llm_model,
        messages=messages,
        tools=tools,
        api_key=api_key,
        stream=False,
    )
    return response  # type: ignore[no-any-return]


async def _load_llm_api_key(session: AsyncSession, *, user_id: UUID) -> str:
    # first() not scalar_one_or_none(): pre-existing duplicate rows must not raise
    # here, mirrors the same reasoning in routers/sync.py's _build_garmin_client
    conn_row = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.connector == "llm_provider",
                Connection.status.in_(["active", "reauth_required"]),
            ).order_by(Connection.connected_at.desc(), Connection.id.desc())
        )
    ).scalars().first()
    if conn_row is None or conn_row.credentials_enc is None:
        raise NoLlmCredentialConfigured(f"No llm_provider connection for user {user_id}")

    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    if user_row is None or user_row.dek_wrapped is None:
        raise NoLlmCredentialConfigured(f"User {user_id} has no wrapped DEK")

    kek = kek_from_settings(settings.kairos_kek)
    dek = unwrap_dek(user_row.dek_wrapped, kek)
    return decrypt(conn_row.credentials_enc, dek).decode()
