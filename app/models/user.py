"""Domain models for users.

DB rows flow through the app as plain dicts; these pydantic models document and
validate the public-facing shapes (and can be used with ``model_validate`` on a
row dict).
"""

from __future__ import annotations

from pydantic import BaseModel


class PublicUser(BaseModel):
    """The user shape returned by the API (no password hash / verification data)."""

    id: str
    email: str
    native_language: str
    target_language: str
    tts_enabled: bool = True
    tts_voice: str = ""
    tts_rate: float = 1.0
    tts_pitch: float = 1.0
    tts_volume: float = 1.0
    plan: str = "free"
    premium_until: str | None = None
    is_premium: bool = False
    must_change_password: bool = False
    is_admin: bool = False
    created_at: str
