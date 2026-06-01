"""Cloudflare Turnstile ("я не робот") verification.

Synchronous (see memory "db-stays-sync"). When ``USE_TURNSTILE`` is off or the
secret key is missing, verification is skipped (returns True) so local dev and
tests work without external services.
"""

from __future__ import annotations

import requests

from app.config import TURNSTILE_SECRET_KEY, USE_TURNSTILE

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def is_enabled() -> bool:
    return bool(USE_TURNSTILE and TURNSTILE_SECRET_KEY)


def verify_turnstile(token: str | None, remote_ip: str | None = None) -> bool:
    if not is_enabled():
        return True
    if not token:
        return False
    try:
        data = {"secret": TURNSTILE_SECRET_KEY, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        response = requests.post(_VERIFY_URL, data=data, timeout=10)
        response.raise_for_status()
        return bool(response.json().get("success"))
    except Exception:
        return False
