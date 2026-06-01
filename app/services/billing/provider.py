"""Active payment provider selection.

Exposes the configured provider name and whether it is usable, so routes and the
status endpoint stay provider-agnostic.
"""

from __future__ import annotations

from app.config import PAYMENT_PROVIDER
from app.services.billing import robokassa_client, yookassa_client


def active_provider() -> str:
    return PAYMENT_PROVIDER if PAYMENT_PROVIDER in {"robokassa", "yookassa"} else "robokassa"


def is_configured() -> bool:
    provider = active_provider()
    if provider == "yookassa":
        return yookassa_client.is_configured()
    return robokassa_client.is_configured()
