"""Authentication and session endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, Request, Response

from app.config import DONATION_MODE, TURNSTILE_SITE_KEY
from app.core.database import db
from app.schemas.user_schema import (
    AuthPayload,
    PasswordChangePayload,
    PasswordResetRequestPayload,
    VerifyRegistrationPayload,
)
from app.services.auth_service import (
    change_password,
    login_user,
    logout_session,
    public_user,
    register_user,
    request_password_reset,
    require_user,
    verify_registration,
)
from app.services.captcha import is_enabled as is_turnstile_enabled

router = APIRouter()

_SESSION_COOKIE = "lp_session"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="lax")


@router.post("/api/register")
def register(payload: AuthPayload, request: Request, response: Response):
    with db() as conn:
        result = register_user(conn, payload, remote_ip=request.client.host if request.client else None)
    if result.get("requires_verification"):
        response.delete_cookie(_SESSION_COOKIE)
        return {"requires_verification": True, "email": result["email"]}
    _set_session_cookie(response, result["token"])
    return {"user": public_user(result["user"])}


@router.post("/api/register/verify")
def verify_register(payload: VerifyRegistrationPayload, response: Response):
    with db() as conn:
        result = verify_registration(conn, payload)
    _set_session_cookie(response, result["token"])
    return {"user": public_user(result["user"])}


@router.post("/api/login")
def login(payload: AuthPayload, response: Response):
    with db() as conn:
        result = login_user(conn, payload)
    _set_session_cookie(response, result["token"])
    return {"user": public_user(result["user"])}


@router.post("/api/logout")
def logout(response: Response, lp_session: str | None = Cookie(default=None)):
    with db() as conn:
        logout_session(conn, lp_session)
    response.delete_cookie(_SESSION_COOKIE)
    return {"ok": True}


@router.get("/api/me")
def me(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        return {"user": public_user(require_user(conn, lp_session, authorization))}


@router.get("/api/config")
def public_config():
    """Public client config (safe to expose): captcha site key, billing mode."""
    return {
        "turnstile_enabled": is_turnstile_enabled(),
        "turnstile_site_key": TURNSTILE_SITE_KEY,
        "donation_mode": DONATION_MODE,
    }


@router.post("/api/password/reset-request")
def password_reset_request(payload: PasswordResetRequestPayload):
    with db() as conn:
        return request_password_reset(conn, payload)


@router.post("/api/password/change")
def password_change(
    payload: PasswordChangePayload,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        result = change_password(
            conn, user, payload.current_password, payload.new_password, keep_token=lp_session
        )
        return {"user": public_user(result["user"])}
