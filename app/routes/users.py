"""User settings endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header

from app.core.database import db
from app.repositories import user_repository
from app.services.auth_service import public_user, require_user
from app.utils.parsing import clamp_float, parse_bool

router = APIRouter()


@router.patch("/api/settings")
def settings(payload: dict[str, str], lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = user_repository.update_user_settings(
            conn,
            user["id"],
            payload.get("native_language", user["native_language"]),
            payload.get("target_language", user["target_language"]),
            parse_bool(payload.get("tts_enabled"), bool(user.get("tts_enabled", True))),
            payload.get("tts_voice") or user.get("tts_voice") or "",
            clamp_float(payload.get("tts_rate"), float(user.get("tts_rate") or 1), 0.5, 2.0),
            clamp_float(payload.get("tts_pitch"), float(user.get("tts_pitch") or 1), 0.5, 2.0),
            clamp_float(payload.get("tts_volume"), float(user.get("tts_volume") or 1), 0.0, 1.0),
        )
        return {"user": public_user(updated)}
