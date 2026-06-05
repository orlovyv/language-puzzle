"""Subscription billing endpoints (provider-agnostic).

Active provider is chosen by ``PAYMENT_PROVIDER`` (robokassa | yookassa).

Security model: a subscription is only ever activated from a verified
server-to-server callback, never from the client redirect.
  - Robokassa: the Result URL is verified by an MD5 signature (Password #2).
  - YooKassa:  the webhook payment is re-fetched and its status re-checked.
Both paths are idempotent on the stored payment status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Form, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import (
    DONATION_DEFAULT_RUB,
    DONATION_MAX_RUB,
    DONATION_MIN_RUB,
    DONATION_MODE,
    SUBSCRIPTION_PERIOD_DAYS,
    SUBSCRIPTION_PRICE_RUB,
)
from app.core.database import db
from app.repositories import payment_repository, user_repository
from app.schemas.user_schema import CheckoutPayload, DonationPayload
from app.services.auth_service import public_user, require_user
from app.services.billing import (
    provider,
    robokassa_client,
    subscription_service,
    yookassa_client,
)
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
            "donation_mode": DONATION_MODE,
            "donation_default_rub": DONATION_DEFAULT_RUB,
            "donation_min_rub": DONATION_MIN_RUB,
            "provider": provider.active_provider(),
            "available": provider.is_configured(),
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
        if not provider.is_configured():
            raise HTTPException(status_code=503, detail="Оплата временно недоступна.")
        description = f"Language Puzzle Premium ({SUBSCRIPTION_PERIOD_DAYS} дней)"

        if provider.active_provider() == "robokassa":
            invoice_id = robokassa_client.new_invoice_id()
            payment_repository.insert_payment(
                conn, token_id("pay"), user["id"], str(invoice_id),
                SUBSCRIPTION_PRICE_RUB, "RUB", "pending", SUBSCRIPTION_PERIOD_DAYS,
                provider="robokassa",
            )
            url = robokassa_client.build_payment_url(invoice_id, description)
            return {"confirmation_url": url, "payment_id": str(invoice_id)}

        # yookassa
        payment = yookassa_client.create_subscription_payment(user, description=description)
        payment_repository.insert_payment(
            conn, token_id("pay"), user["id"], payment["id"],
            payment["amount"], "RUB", payment["status"], SUBSCRIPTION_PERIOD_DAYS,
            provider="yookassa",
        )
        return {"confirmation_url": payment["confirmation_url"], "payment_id": payment["id"]}


@router.post("/api/billing/donate")
def billing_donate(
    payload: DonationPayload,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    """Create a one-off "support the developer" donation payment.

    Donations are recorded with ``period_days=0`` so the success callbacks know
    not to grant a subscription (AI is already free for everyone).
    """
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        if not provider.is_configured():
            raise HTTPException(status_code=503, detail="Оплата временно недоступна.")
        amount = round(float(payload.amount), 2)
        if amount < DONATION_MIN_RUB or amount > DONATION_MAX_RUB:
            raise HTTPException(
                status_code=400,
                detail=f"Сумма доната должна быть от {DONATION_MIN_RUB:g} до {DONATION_MAX_RUB:g} ₽.",
            )
        description = "Поддержка разработчика Language Puzzle"

        if provider.active_provider() == "robokassa":
            invoice_id = robokassa_client.new_invoice_id()
            payment_repository.insert_payment(
                conn, token_id("pay"), user["id"], str(invoice_id),
                amount, "RUB", "pending", 0, provider="robokassa",
            )
            url = robokassa_client.build_payment_url(invoice_id, description, amount=amount)
            return {"confirmation_url": url, "payment_id": str(invoice_id)}

        # yookassa
        payment = yookassa_client.create_donation_payment(user, amount, description=description)
        payment_repository.insert_payment(
            conn, token_id("pay"), user["id"], payment["id"],
            payment["amount"], "RUB", payment["status"], 0, provider="yookassa",
        )
        return {"confirmation_url": payment["confirmation_url"], "payment_id": payment["id"]}


@router.post("/api/billing/cancel")
def billing_cancel(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = subscription_service.cancel_subscription(conn, user)
        return {"status": subscription_service.status_for(updated or user)}


@router.post("/api/billing/robokassa-result")
async def robokassa_result(
    OutSum: str = Form(...),
    InvId: str = Form(...),
    SignatureValue: str = Form(...),
):
    """Robokassa Result URL. Verifies the MD5 signature, then grants premium.
    Must respond with ``OK{InvId}`` so Robokassa stops retrying."""
    if not robokassa_client.verify_result(OutSum, InvId, SignatureValue):
        raise HTTPException(status_code=400, detail="bad signature")

    with db() as conn:
        record = payment_repository.find_by_provider_id(conn, InvId)
        if not record:
            raise HTTPException(status_code=404, detail="unknown invoice")
        if record["status"] == "succeeded":
            return PlainTextResponse(f"OK{InvId}")  # idempotent

        user = user_repository.find_user_by_id(conn, record["user_id"])
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        payment_repository.update_status(conn, InvId, "succeeded")
        # period_days == 0 marks a donation — nothing to grant (AI is already free).
        if record["period_days"]:
            # Robokassa (simple flow) has no saved-method recurring => auto_renew off.
            subscription_service.activate_subscription(
                conn, user, period_days=record["period_days"], auto_renew=False
            )
    return PlainTextResponse(f"OK{InvId}")


@router.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """YooKassa notification. Only handled when YooKassa is the active provider."""
    if provider.active_provider() != "yookassa" or not yookassa_client.is_configured():
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
        record = payment_repository.find_by_provider_id(conn, payment_id)
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
        # period_days == 0 marks a donation — record it but grant no subscription.
        if period_days:
            subscription_service.activate_subscription(
                conn, user, period_days=period_days, payment_method_id=verified.get("payment_method_id")
            )
        return {"ok": True}
