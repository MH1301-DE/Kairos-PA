from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import encrypt, kek_from_settings, unwrap_dek
from kairos.auth.deps import current_user
from kairos.config import settings
from kairos.connectors.garmin.client import (
    GarminClient,
    GarminConnectBackend,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)
from kairos.db.models import AppUser, Connection
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

    # Once any Garmin account has ever been connected for this Kairos user, switching
    # to a different one is permanently refused -- health data (activity, wellness_*)
    # is keyed only by user_id, not by which Garmin external_account produced it, so a
    # switch would silently blend a different person's physiological history into this
    # user's metrics with no way to separate it afterward. Checked before touching
    # Garmin at all, so a doomed request never spends any of the rate-limited login
    # budget on Garmin's API.
    existing_accounts = (
        await session.execute(
            select(Connection.external_account).where(
                Connection.user_id == user_id, Connection.connector == "garmin"
            )
        )
    ).scalars().all()
    await session.rollback()
    if existing_accounts and any(
        a is None or a.lower() != req.email.lower() for a in existing_accounts
    ):
        raise HTTPException(
            status_code=409, detail="different_garmin_account_already_connected"
        )

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

    # connect_garmin already refuses a different external_account before this is ever
    # called (see the check there), so this is always either a first-time connect or a
    # reconnect of the same account -- a plain upsert, no "disable the other account"
    # step needed.
    now = datetime.now(UTC)
    stmt = (
        insert(Connection)
        .values(
            user_id=user_id,
            connector="garmin",
            external_account=email,
            status="active",
            credentials_enc=credentials_enc,
            last_ok_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_connection",
            # clears reauth_required/last_error left over from a previous session
            # expiry -- this is exactly the "successful re-login" moment that
            # reauth_since's column comment says clears it
            set_={
                "status": "active",
                "credentials_enc": credentials_enc,
                "reauth_since": None,
                "last_error": None,
                "last_ok_at": now,
            },
        )
    )
    await session.execute(stmt)


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
