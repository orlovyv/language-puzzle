from __future__ import annotations

from typing import Any


def normalize_user_settings(user: dict[str, Any]) -> dict[str, Any]:
    return {
        **user,
        "tts_enabled": bool(user.get("tts_enabled", True)),
    }
