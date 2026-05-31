"""Authentication and session endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, Response

from app.core.database import db
from app.schemas.user_schema import AuthPayload, VerifyRegistrationPayload
from app.services.auth_service import (
    login_user,
    logout_session,
    public_user,
    register_user,
    require_user,
    verify_registration,
)

router = APIRouter()

_SESSION_COOKIE = "lp_session"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="lax")


@router.post("/api/register")
def register(payload: AuthPayload, response: Response):
    with db() as conn:
        result = register_user(conn, payload)
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
