"""Robokassa payment integration.

Robokassa needs no API call to create a payment: we build a signed redirect URL
and the user pays on Robokassa's side. The server is notified via the Result URL,
whose authenticity is verified with an MD5 signature using Password #2.

Signatures (MD5, uppercase hex compared case-insensitively):
  - redirect:  md5("login:OutSum:InvId:Password1")
  - result cb: md5("OutSum:InvId:Password2")

Degrades gracefully: ``is_configured`` is False when login/passwords are unset,
so the billing routes return 503 instead of crashing.
"""

from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlencode

from app.config import (
    ROBOKASSA_BASE_URL,
    ROBOKASSA_IS_TEST,
    ROBOKASSA_MERCHANT_LOGIN,
    ROBOKASSA_PASSWORD1,
    ROBOKASSA_PASSWORD2,
    SUBSCRIPTION_PRICE_RUB,
)


def is_configured() -> bool:
    return bool(ROBOKASSA_MERCHANT_LOGIN and ROBOKASSA_PASSWORD1 and ROBOKASSA_PASSWORD2)


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def new_invoice_id() -> int:
    """Robokassa InvId must be a positive 32-bit integer, unique per merchant."""
    return secrets.randbelow(2_000_000_000) + 1


def format_amount(amount: float) -> str:
    return f"{amount:.2f}"


def build_payment_url(invoice_id: int, description: str, amount: float | None = None) -> str:
    if not is_configured():
        raise RuntimeError("Robokassa is not configured (login/passwords missing)")
    out_sum = format_amount(SUBSCRIPTION_PRICE_RUB if amount is None else amount)
    signature = _md5(f"{ROBOKASSA_MERCHANT_LOGIN}:{out_sum}:{invoice_id}:{ROBOKASSA_PASSWORD1}")
    params = {
        "MerchantLogin": ROBOKASSA_MERCHANT_LOGIN,
        "OutSum": out_sum,
        "InvId": invoice_id,
        "Description": description,
        "SignatureValue": signature,
    }
    if ROBOKASSA_IS_TEST:
        params["IsTest"] = 1
    return f"{ROBOKASSA_BASE_URL}?{urlencode(params)}"


def verify_result(out_sum: str, invoice_id: str, signature: str) -> bool:
    """Verify a Result-URL callback signature: md5(OutSum:InvId:Password2)."""
    if not is_configured() or not signature:
        return False
    expected = _md5(f"{out_sum}:{invoice_id}:{ROBOKASSA_PASSWORD2}")
    return expected.lower() == signature.lower()
