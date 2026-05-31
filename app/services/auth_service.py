"""Authentication: sessions, the public user projection, email verification and
the register / verify / login flows. Cookie handling stays in the routes."""

from __future__ import annotations

import hashlib
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from fastapi import HTTPException

from app.config import (
    APP_SECRET,
    EMAIL_VERIFICATION_ENABLED,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USERNAME,
)
from app.repositories import user_repository
from app.utils.security import hash_password, token_id

VERIFICATION_CODE_TTL_MINUTES = 15
VERIFICATION_MAX_ATTEMPTS = 5
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(normalize_email(value)))


def verification_code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{APP_SECRET}:{normalize_email(email)}:{code}".encode()).hexdigest()


def send_verification_email(email: str, code: str) -> None:
    subject = "Language Puzzle verification code"
    body = (
        "Код подтверждения Language Puzzle: "
        f"{code}\n\nОн действует {VERIFICATION_CODE_TTL_MINUTES} минут."
    )
    if not SMTP_HOST:
        print(f"[Language Puzzle] Verification code for {email}: {code}")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = email
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    # Imported here to avoid a circular import (billing -> auth_service).
    from app.services.billing.subscription_service import is_premium

    premium_until = user.get("premium_until")
    return {
        "id": user["id"],
        "email": user["email"],
        "native_language": user["native_language"],
        "target_language": user["target_language"],
        "tts_enabled": bool(user.get("tts_enabled", True)),
        "tts_voice": user.get("tts_voice") or "",
        "tts_rate": float(user.get("tts_rate") or 1),
        "tts_pitch": float(user.get("tts_pitch") or 1),
        "tts_volume": float(user.get("tts_volume") or 1),
        "plan": user.get("plan", "free"),
        "premium_until": str(premium_until) if premium_until else None,
        "is_premium": is_premium(user),
        "created_at": str(user["created_at"]),
    }


def _token_from(lp_session: str | None, authorization: str | None) -> str | None:
    if lp_session:
        return lp_session
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.replace("Bearer ", "")
    return None


def current_user(conn, lp_session: str | None, authorization: str | None) -> dict[str, Any] | None:
    token = _token_from(lp_session, authorization)
    if not token:
        return None
    return user_repository.find_user_by_session(conn, token)


def require_user(conn, lp_session: str | None, authorization: str | None) -> dict[str, Any]:
    user = current_user(conn, lp_session, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Нужно войти.")
    return user


def require_premium(conn, lp_session: str | None, authorization: str | None) -> dict[str, Any]:
    from app.services.billing.subscription_service import is_premium

    user = require_user(conn, lp_session, authorization)
    if not is_premium(user):
        raise HTTPException(status_code=403, detail="Доступно по подписке.")
    return user


# ---------------------------------------------------------------------------
# flows
# ---------------------------------------------------------------------------
def _start_session(conn, user: dict[str, Any]) -> str:
    token = token_id("s")
    user_repository.create_session(conn, token, user["id"])
    return token


def register_user(conn, payload) -> dict[str, Any]:
    email = normalize_email(payload.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Укажите корректный email.")
    if len(payload.password or "") < 4:
        raise HTTPException(status_code=400, detail="Пароль должен быть не короче 4 символов.")
    if user_repository.find_user_by_email(conn, email):
        raise HTTPException(status_code=409, detail="Пользователь уже существует.")

    native_language = payload.native_language or "ru"
    target_language = payload.target_language or "en"

    if not EMAIL_VERIFICATION_ENABLED:
        user = user_repository.create_user(
            conn, token_id("u"), email, hash_password(payload.password), native_language, target_language
        )
        return {"user": user, "token": _start_session(conn, user)}

    code = f"{secrets.randbelow(1_000_000):06d}"
    user_repository.upsert_verification_code(
        conn,
        email,
        hash_password(payload.password),
        native_language,
        target_language,
        verification_code_hash(email, code),
        datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES),
    )
    send_verification_email(email, code)
    return {"requires_verification": True, "email": email}


def verify_registration(conn, payload) -> dict[str, Any]:
    email = normalize_email(payload.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Укажите корректный email.")
    code = re.sub(r"\D", "", payload.code or "")
    pending = user_repository.find_verification_code(conn, email)
    if not pending:
        raise HTTPException(status_code=404, detail="Код не найден. Запросите регистрацию ещё раз.")
    if pending["expires_at"] < datetime.now(timezone.utc):
        user_repository.delete_verification_code(conn, email)
        raise HTTPException(status_code=410, detail="Код устарел. Запросите новый код.")
    if pending["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Слишком много попыток. Запросите новый код.")
    if verification_code_hash(email, code) != pending["code_hash"]:
        user_repository.increment_verification_attempts(conn, email)
        raise HTTPException(status_code=400, detail="Неверный код подтверждения.")
    if user_repository.find_user_by_email(conn, email):
        user_repository.delete_verification_code(conn, email)
        raise HTTPException(status_code=409, detail="Пользователь уже существует.")
    user = user_repository.create_user(
        conn,
        token_id("u"),
        email,
        pending["password_hash"],
        pending["native_language"],
        pending["target_language"],
    )
    user_repository.delete_verification_code(conn, email)
    return {"user": user, "token": _start_session(conn, user)}


def login_user(conn, payload) -> dict[str, Any]:
    email = normalize_email(payload.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Укажите корректный email.")
    user = user_repository.find_user_by_credentials(conn, email, hash_password(payload.password))
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль.")
    if not user.get("email_verified", True):
        raise HTTPException(status_code=403, detail="Подтвердите email перед входом.")
    return {"user": user, "token": _start_session(conn, user)}


def logout_session(conn, lp_session: str | None) -> None:
    if lp_session:
        user_repository.delete_session(conn, lp_session)
