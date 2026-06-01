"""Subscription business logic: premium status, activation, cancellation.

Pure DB operations (no YooKassa dependency) so it is unit-testable and reusable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import SUBSCRIPTION_PERIOD_DAYS
from app.repositories import user_repository


def is_premium(user: dict[str, Any] | None) -> bool:
    if not user or user.get("plan") != "premium":
        return False
    until = user.get("premium_until")
    if until is None:
        return True
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until >= datetime.now(timezone.utc)


def _extend_from(user: dict[str, Any], period_days: int) -> datetime:
    """New premium_until: extend from current expiry if still active, else from now."""
    now = datetime.now(timezone.utc)
    current = user.get("premium_until")
    if isinstance(current, str):
        try:
            current = datetime.fromisoformat(current)
        except ValueError:
            current = None
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = current if (current and current > now) else now
    return base + timedelta(days=period_days)


def activate_subscription(
    conn,
    user: dict[str, Any],
    period_days: int | None = None,
    payment_method_id: str | None = None,
    auto_renew: bool = True,
) -> dict[str, Any] | None:
    period = period_days or SUBSCRIPTION_PERIOD_DAYS
    premium_until = _extend_from(user, period)
    return user_repository.set_subscription(
        conn,
        user["id"],
        plan="premium",
        premium_until=premium_until,
        auto_renew=auto_renew,
        payment_method_id=payment_method_id,
    )


def cancel_subscription(conn, user: dict[str, Any]) -> dict[str, Any] | None:
    """Disable auto-renew; keep premium access until premium_until lapses."""
    return user_repository.set_auto_renew(conn, user["id"], False)


def expire_overdue(conn) -> int:
    return user_repository.expire_overdue_subscriptions(conn)


def status_for(user: dict[str, Any]) -> dict[str, Any]:
    until = user.get("premium_until")
    return {
        "plan": user.get("plan", "free"),
        "is_premium": is_premium(user),
        "premium_until": str(until) if until else None,
        "auto_renew": bool(user.get("subscription_auto_renew", False)),
    }
