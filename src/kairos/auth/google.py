import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from kairos.auth.crypto import encrypt, generate_dek, kek_from_settings, unwrap_dek, wrap_dek
from kairos.auth.session import create_session, delete_session, get_redis
from kairos.config import settings
from kairos.db.models import AppUser, Connection
from kairos.db.session import async_session_factory

router = APIRouter(prefix="/auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile https://www.googleapis.com/auth/calendar"


@router.get("/login")
async def login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    await get_redis().set(f"oauth_state:{state}", "1", ex=600)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": SCOPES,
        "response_type": "code",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"google_error:{error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing_code")
    valid = await get_redis().getdel(f"oauth_state:{state}")
    if not valid:
        raise HTTPException(status_code=400, detail="invalid_state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    token_resp.raise_for_status()
    tokens = token_resp.json()

    async with httpx.AsyncClient() as client:
        info_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    info_resp.raise_for_status()
    info = info_resp.json()

    google_sub: str = info["sub"]
    email: str = info["email"]
    name: str = info.get("name", email)

    async with async_session_factory() as db:
        result = await db.execute(select(AppUser).where(AppUser.google_sub == google_sub))
        user = result.scalar_one_or_none()

        if user is None:
            kek = kek_from_settings(settings.kairos_kek)
            dek = generate_dek()
            user = AppUser(
                email=email,
                display_name=name,
                google_sub=google_sub,
                dek_wrapped=wrap_dek(dek, kek),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        # Google only returns refresh_token on first consent, but login() forces prompt=consent
        refresh_token = tokens.get("refresh_token")
        if refresh_token:
            kek = kek_from_settings(settings.kairos_kek)
            if user.dek_wrapped is None:
                dek = generate_dek()
                user.dek_wrapped = wrap_dek(dek, kek)
            else:
                dek = unwrap_dek(user.dek_wrapped, kek)
            credentials_enc = encrypt(refresh_token.encode(), dek)
            # every login re-consents (prompt=consent), so this must upsert, not insert —
            # a plain insert would raise IntegrityError on uq_connection for a returning user
            stmt = (
                insert(Connection)
                .values(
                    user_id=user.id,
                    connector="google_calendar",
                    external_account=email,
                    status="active",
                    credentials_enc=credentials_enc,
                )
                .on_conflict_do_update(
                    constraint="uq_connection",
                    set_={"status": "active", "credentials_enc": credentials_enc},
                )
            )
            await db.execute(stmt)
            await db.commit()

    session_id = await create_session(user.id, email)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response


@router.post("/logout")
async def logout(session_id: str | None = Cookie(default=None)) -> RedirectResponse:
    if session_id:
        await delete_session(session_id)
    # nav posts a plain HTML form, so the browser follows this response — must land on a page
    response = RedirectResponse(url="/", status_code=302)
    # attributes must mirror the set_cookie() in callback() or browsers keep the cookie
    response.delete_cookie(
        "session_id",
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
    )
    return response
