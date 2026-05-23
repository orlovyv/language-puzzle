from __future__ import annotations

from typing import TypedDict


class User(TypedDict, total=False):
    id: str
    email: str
    native_language: str
    target_language: str
    tts_enabled: bool
    tts_voice: str
    tts_rate: float
    tts_pitch: float
    tts_volume: float
