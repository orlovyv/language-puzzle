"""YooKassa API wrapper.

Degrades gracefully when the SDK is missing or keys are unset: ``is_configured``
returns False and the billing routes report 503 instead of crashing the app.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.config import (
    SUBSCRIPTION_PRICE_RUB,
    SUBSCRIPTION_RETURN_URL,
    YOOKASSA_SECRET_KEY,
    YOOKASSA_SHOP_ID,
)

try:
    from yookassa import Configuration, Payment
except ImportError:  # pragma: no cover
    Configuration = None
    Payment = None

_configured = False


def is_configured() -> bool:
    return bool(Payment and YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)


def _ensure_configured() -> None:
    global _configured
    if not is_configured():
        raise RuntimeError("YooKassa is not configured (SDK or keys missing)")
    if not _configured:
        Configuration.account_id = YOOKASSA_SHOP_ID
        Configuration.secret_key = YOOKASSA_SECRET_KEY
        _configured = True


def create_subscription_payment(user: dict[str, Any], description: str) -> dict[str, Any]:
    """Create a payment with a saved method for recurring charges.

    Returns {"id", "confirmation_url", "status", "amount"}.
    """
    _ensure_configured()
    payment = Payment.create(
        {
            "amount": {"value": f"{SUBSCRIPTION_PRICE_RUB:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": SUBSCRIPTION_RETURN_URL},
            "capture": True,
            "save_payment_method": True,
            "description": description,
            "metadata": {"user_id": user["id"]},
        },
        str(uuid.uuid4()),  # idempotency key
    )
    return {
        "id": payment.id,
        "confirmation_url": getattr(payment.confirmation, "confirmation_url", None),
        "status": payment.status,
        "amount": float(payment.amount.value),
    }


def create_donation_payment(user: dict[str, Any], amount: float, description: str) -> dict[str, Any]:
    """Create a one-off donation payment (no saved method, no recurring).

    Returns {"id", "confirmation_url", "status", "amount"}.
    """
    _ensure_configured()
    payment = Payment.create(
        {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": SUBSCRIPTION_RETURN_URL},
            "capture": True,
            "description": description,
            "metadata": {"user_id": user["id"], "kind": "donation"},
        },
        str(uuid.uuid4()),  # idempotency key
    )
    return {
        "id": payment.id,
        "confirmation_url": getattr(payment.confirmation, "confirmation_url", None),
        "status": payment.status,
        "amount": float(payment.amount.value),
    }


def get_payment(payment_id: str) -> dict[str, Any]:
    _ensure_configured()
    payment = Payment.find_one(payment_id)
    return {
        "id": payment.id,
        "status": payment.status,
        "paid": bool(getattr(payment, "paid", False)),
        "amount": float(payment.amount.value),
        "payment_method_id": getattr(getattr(payment, "payment_method", None), "id", None),
        "metadata": dict(getattr(payment, "metadata", {}) or {}),
    }
