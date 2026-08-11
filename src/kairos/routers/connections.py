from __future__ import annotations

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
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict | JSONResponse:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    client = GarminClient(GarminConnectBackend())
    try:
        tokens = client.login(req.email, req.password, mfa_token=req.mfa_token)
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


@router.get("")
async def list_connections(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    rows = (
        await session.execute(select(Connection).where(Connection.user_id == user_id))
    ).scalars().all()
    return {
        "connections": [
            {"connector": c.connector, "status": c.status, "external_account": c.external_account}
            for c in rows
        ]
    }
