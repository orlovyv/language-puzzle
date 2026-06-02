"""Admin operations: safe user projections and moderation actions.

Reuses subscription_service (premium) and auth_service (password reset) so the
business rules stay in one place. Never exposes password_hash.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.repositories import admin_repository, payment_repository, user_repository
from app.services.auth_service import EmailDeliveryError, send_temporary_password_email
from app.services.billing import subscription_service
from app.utils.security import hash_password

_PUBLIC_FIELDS = (
    "id", "email", "plan", "premium_until", "is_blocked", "email_verified",
    "must_change_password", "created_at", "native_language", "target_language",
    "subscription_auto_renew",
)


def safe_user(user: dict[str, Any]) -> dict[str, Any]:
    """User row without secrets, plus derived is_premium/is_admin."""
    from app.services.auth_service import is_admin

    data = {key: user.get(key) for key in _PUBLIC_FIELDS if key in user}
    for key in ("premium_until", "created_at"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    data["is_premium"] = subscription_service.is_premium(user)
    data["is_admin"] = is_admin(user)
    # carry through list-view aggregates if present
    for extra in ("documents_count", "vocabulary_count"):
        if extra in user:
            data[extra] = user[extra]
    return data


def stats(conn) -> dict[str, Any]:
    return admin_repository.platform_stats(conn)


def list_users(conn, query: str | None, limit: int, offset: int) -> dict[str, Any]:
    rows = admin_repository.list_users(conn, query, limit, offset)
    return {
        "users": [safe_user(row) for row in rows],
        "total": admin_repository.count_users(conn, query),
        "limit": limit,
        "offset": offset,
    }


def user_detail(conn, user_id: str) -> dict[str, Any]:
    user = user_repository.find_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    return {
        "user": safe_user(user),
        "documents": admin_repository.user_documents(conn, user_id),
        "payments": payment_repository.user_payments(conn, user_id),
    }


def _require_user(conn, user_id: str) -> dict[str, Any]:
    user = user_repository.find_user_by_id(conn, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    return user


def set_subscription(conn, user_id: str, plan: str, premium_until: str | None) -> dict[str, Any]:
    user = _require_user(conn, user_id)
    if plan == "premium":
        until = None
        if premium_until:
            try:
                until = datetime.fromisoformat(premium_until)
            except ValueError:
                raise HTTPException(status_code=400, detail="Неверная дата premium_until.")
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        updated = user_repository.set_subscription(
            conn, user_id, plan="premium", premium_until=until, auto_renew=False
        )
    else:
        updated = user_repository.set_subscription(
            conn, user_id, plan="free", premium_until=None, auto_renew=False
        )
    return safe_user(updated)


def set_blocked(conn, admin_id: str, user_id: str, blocked: bool) -> dict[str, Any]:
    if blocked and user_id == admin_id:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать самого себя.")
    _require_user(conn, user_id)
    updated = user_repository.set_blocked(conn, user_id, blocked)
    if blocked:
        user_repository.delete_other_sessions(conn, user_id)  # kick active sessions
    return safe_user(updated)


def reset_password(conn, user_id: str) -> dict[str, Any]:
    user = _require_user(conn, user_id)
    temporary = secrets.token_urlsafe(9)
    # Send first; only rotate the password if delivery succeeded.
    try:
        send_temporary_password_email(user["email"], temporary)
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=502,
            detail="Не удалось отправить письмо пользователю.",
        ) from exc
    user_repository.update_password(conn, user_id, hash_password(temporary), must_change=True)
    user_repository.delete_other_sessions(conn, user_id)
    return {"ok": True}
