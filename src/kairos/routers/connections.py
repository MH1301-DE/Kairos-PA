from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import encrypt, generate_dek, kek_from_settings, unwrap_dek, wrap_dek
from kairos.auth.deps import current_user
from kairos.config import settings
from kairos.connectors.garmin.client import (
    GarminClient,
    GarminConnectBackend,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)
from kairos.db.models import AppUser, Connection, UserSetting
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session

router = APIRouter(prefix="/api/connections", tags=["connections"])


class GarminConnectionRequest(BaseModel):
    email: str
    password: str
    mfa_token: str | None = None


@router.post("/garmin", status_code=201, response_model=None)
async def connect_garmin(
    req: GarminConnectionRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    client = GarminClient(GarminConnectBackend())
    try:
        # client.login() performs blocking HTTP calls to Garmin; keep it off the event loop
        tokens = await asyncio.to_thread(
            client.login, req.email, req.password, mfa_token=req.mfa_token
        )
    except NeedsMfaToken:
        return _mfa_required_response()
    except InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc
    except UpstreamUnavailable as exc:
        raise HTTPException(status_code=503, detail="garmin_unavailable") from exc

    await _store_connection(session, user_id, req.email, tokens.refresh_token)
    await session.commit()
    return {"status": "connected"}


def _mfa_required_response() -> JSONResponse:
    # decorator default status_code is 201; MFA branch needs 202, so bypass it explicitly
    return JSONResponse(status_code=202, content={"status": "mfa_required"})


async def _store_connection(
    session: AsyncSession, user_id: UUID, email: str, token_json: str
) -> None:
    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one()
    kek = kek_from_settings(settings.kairos_kek)
    dek = unwrap_dek(user_row.dek_wrapped, kek)  # type: ignore[arg-type]
    credentials_enc = encrypt(token_json.encode(), dek)

    # uq_connection includes external_account, so re-onboarding with another Garmin account
    # would insert a second active row and make the sync-side lookup ambiguous
    await session.execute(
        update(Connection)
        .where(
            Connection.user_id == user_id,
            Connection.connector == "garmin",
            # IS DISTINCT FROM, so legacy rows with a NULL external_account are caught too
            Connection.external_account.is_distinct_from(email),
        )
        .values(status="disabled")
    )

    stmt = (
        insert(Connection)
        .values(
            user_id=user_id,
            connector="garmin",
            external_account=email,
            status="active",
            credentials_enc=credentials_enc,
        )
        .on_conflict_do_update(
            constraint="uq_connection",
            set_={"status": "active", "credentials_enc": credentials_enc},
        )
    )
    await session.execute(stmt)


class LlmProviderConnectionRequest(BaseModel):
    model: str
    api_key: str


@router.post("/llm_provider", status_code=201)
async def connect_llm_provider(
    req: LlmProviderConnectionRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    await _store_llm_connection(session, user_id, req.model, req.api_key)
    await session.commit()
    return {"status": "connected"}


async def _store_llm_connection(
    session: AsyncSession, user_id: UUID, model: str, api_key: str
) -> None:
    user_row = (
        await session.execute(select(AppUser).where(AppUser.id == user_id))
    ).scalar_one()
    kek = kek_from_settings(settings.kairos_kek)
    # unlike Garmin/Google (always reached only after a DEK already exists from
    # login), a user could set an LLM key before ever connecting anything else
    if user_row.dek_wrapped is None:
        dek = generate_dek()
        user_row.dek_wrapped = wrap_dek(dek, kek)
    else:
        dek = unwrap_dek(user_row.dek_wrapped, kek)
    credentials_enc = encrypt(api_key.encode(), dek)

    # external_account doubles as the model name here (matches Garmin's use of
    # the field for the account email) -- re-entering a different model disables
    # the old row instead of leaving two "active" llm_provider connections
    await session.execute(
        update(Connection)
        .where(
            Connection.user_id == user_id,
            Connection.connector == "llm_provider",
            Connection.external_account.is_distinct_from(model),
        )
        .values(status="disabled")
    )
    stmt = (
        insert(Connection)
        .values(
            user_id=user_id,
            connector="llm_provider",
            external_account=model,
            status="active",
            credentials_enc=credentials_enc,
        )
        .on_conflict_do_update(
            constraint="uq_connection",
            set_={"status": "active", "credentials_enc": credentials_enc},
        )
    )
    await session.execute(stmt)

    # keep user_setting.llm_model in sync -- get_completion() reads it separately
    # from the connection row, the two must agree on which model the key is for
    setting_stmt = (
        insert(UserSetting)
        .values(user_id=user_id, llm_model=model)
        .on_conflict_do_update(index_elements=[UserSetting.user_id], set_={"llm_model": model})
    )
    await session.execute(setting_stmt)


@router.get("")
async def list_connections(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    rows = (
        await session.execute(select(Connection).where(Connection.user_id == user_id))
    ).scalars().all()
    return {
        "connections": [
            {
                "connector": c.connector,
                "status": c.status,
                "external_account": c.external_account,
                "connected_at": c.connected_at.isoformat(),
                "last_ok_at": c.last_ok_at.isoformat() if c.last_ok_at else None,
                "token_refreshed_at": c.token_refreshed_at.isoformat()
                if c.token_refreshed_at
                else None,
                "reauth_since": c.reauth_since.isoformat() if c.reauth_since else None,
            }
            for c in rows
        ]
    }
