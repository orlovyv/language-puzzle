"""Subscription billing endpoints (YooKassa).

Security model: a subscription is only ever activated from the verified
``payment.succeeded`` webhook (never from the client redirect). The webhook
verifies the payment by re-fetching it from YooKassa and is idempotent on the
stored payment status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException, Request

from app.config import SUBSCRIPTION_PERIOD_DAYS, SUBSCRIPTION_PRICE_RUB
from app.core.database import db
from app.repositories import payment_repository, user_repository
from app.schemas.user_schema import CheckoutPayload
from app.services.auth_service import public_user, require_user
from app.services.billing import subscription_service, yookassa_client
from app.utils.security import token_id

router = APIRouter()


@router.get("/api/billing/status")
def billing_status(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        return {
            "status": subscription_service.status_for(user),
            "price_rub": SUBSCRIPTION_PRICE_RUB,
            "period_days": SUBSCRIPTION_PERIOD_DAYS,
            "available": yookassa_client.is_configured(),
            "payments": payment_repository.user_payments(conn, user["id"]),
        }


@router.post("/api/billing/checkout")
def billing_checkout(
    payload: CheckoutPayload | None = None,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        if not yookassa_client.is_configured():
            raise HTTPException(status_code=503, detail="Оплата временно недоступна.")
        payment = yookassa_client.create_subscription_payment(
            user, description=f"Language Puzzle Premium ({SUBSCRIPTION_PERIOD_DAYS} дней)"
        )
        payment_repository.insert_payment(
            conn,
            token_id("pay"),
            user["id"],
            payment["id"],
            payment["amount"],
            "RUB",
            payment["status"],
            SUBSCRIPTION_PERIOD_DAYS,
        )
        return {"confirmation_url": payment["confirmation_url"], "payment_id": payment["id"]}


@router.post("/api/billing/cancel")
def billing_cancel(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = subscription_service.cancel_subscription(conn, user)
        return {"status": subscription_service.status_for(updated or user)}


@router.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """YooKassa notification. No session; authenticity comes from re-fetching the
    payment from YooKassa and verifying its real status before granting premium."""
    if not yookassa_client.is_configured():
        raise HTTPException(status_code=503, detail="Billing not configured")
    body: dict[str, Any] = await request.json()
    event = body.get("event")
    obj = body.get("object") or {}
    payment_id = obj.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="No payment id")

    if event != "payment.succeeded":
        return {"ok": True, "ignored": event}

    # Re-fetch the payment from YooKassa — never trust the webhook body alone.
    verified = yookassa_client.get_payment(payment_id)
    if verified["status"] != "succeeded" or not verified["paid"]:
        return {"ok": True, "ignored": "not paid"}

    with db() as conn:
        record = payment_repository.find_by_yookassa_id(conn, payment_id)
        # Idempotency: if we already processed this payment, do nothing.
        if record and record["status"] == "succeeded":
            return {"ok": True, "idempotent": True}

        user_id = (verified.get("metadata") or {}).get("user_id") or (record or {}).get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="No user for payment")
        user = user_repository.find_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        period_days = record["period_days"] if record else SUBSCRIPTION_PERIOD_DAYS
        if record:
            payment_repository.update_status(conn, payment_id, "succeeded")
        subscription_service.activate_subscription(
            conn, user, period_days=period_days, payment_method_id=verified.get("payment_method_id")
        )
        return {"ok": True}
