import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from kairos.auth.crypto import generate_dek, kek_from_settings, wrap_dek
from kairos.auth.session import create_session, delete_session, get_redis
from kairos.config import settings
from kairos.db.models import AppUser
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
        "redirect_uri": f"https://{settings.domain}/auth/callback",
        "scope": SCOPES,
        "response_type": "code",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str, state: str) -> JSONResponse:
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
                "redirect_uri": f"https://{settings.domain}/auth/callback",
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

    session_id = await create_session(user.id, email)
    response = JSONResponse({"ok": True, "email": email})
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
async def logout(session_id: str | None = None) -> JSONResponse:
    if session_id:
        await delete_session(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie("session_id")
    return response
