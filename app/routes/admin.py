"""Admin panel endpoints. Every route is gated by require_admin (403 otherwise)."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header

from app.core.database import db
from app.schemas.user_schema import AdminBlockPayload, AdminSubscriptionPayload
from app.services import admin_service
from app.services.auth_service import require_admin
from app.services.llm.enrichment import ai_healthcheck

router = APIRouter()


@router.get("/api/admin/stats")
def admin_stats(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        require_admin(conn, lp_session, authorization)
        return {"stats": admin_service.stats(conn)}


@router.get("/api/admin/ai-health")
def admin_ai_health(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        admin = require_admin(conn, lp_session, authorization)
        return {"health": ai_healthcheck(conn, admin)}


@router.get("/api/admin/users")
def admin_users(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        require_admin(conn, lp_session, authorization)
        limit = max(1, min(200, limit))
        offset = max(0, offset)
        return admin_service.list_users(conn, (q or "").strip() or None, limit, offset)


@router.get("/api/admin/users/{user_id}")
def admin_user_detail(user_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        require_admin(conn, lp_session, authorization)
        return admin_service.user_detail(conn, user_id)


@router.patch("/api/admin/users/{user_id}/subscription")
def admin_set_subscription(
    user_id: str,
    payload: AdminSubscriptionPayload,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        require_admin(conn, lp_session, authorization)
        return {"user": admin_service.set_subscription(conn, user_id, payload.plan, payload.premium_until)}


@router.patch("/api/admin/users/{user_id}/block")
def admin_set_blocked(
    user_id: str,
    payload: AdminBlockPayload,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        admin = require_admin(conn, lp_session, authorization)
        return {"user": admin_service.set_blocked(conn, admin["id"], user_id, payload.blocked)}


@router.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        require_admin(conn, lp_session, authorization)
        return admin_service.reset_password(conn, user_id)
