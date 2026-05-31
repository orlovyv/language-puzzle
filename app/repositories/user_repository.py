"""SQL access for users, sessions and email verification codes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.database import execute, query_one


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
def find_user_by_email(conn, email: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from users where email=%s", (email,))


def find_user_by_id(conn, user_id: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from users where id=%s", (user_id,))


def find_user_by_credentials(conn, email: str, password_hash: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from users where email=%s and password_hash=%s",
        (email, password_hash),
    )


def find_user_by_session(conn, token: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select u.* from users u
        join sessions s on s.user_id = u.id
        where s.token = %s
        """,
        (token,),
    )


def create_user(
    conn,
    user_id: str,
    email: str,
    password_hash: str,
    native_language: str,
    target_language: str,
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into users
            (id, email, password_hash, native_language, target_language, email_verified)
        values (%s, %s, %s, %s, %s, true)
        returning *
        """,
        (user_id, email, password_hash, native_language, target_language),
    )


def upsert_demo_user(conn, user_id: str, email: str, password_hash: str) -> None:
    execute(
        conn,
        """
        insert into users (id, email, password_hash, native_language, target_language, email_verified)
        values (%s, %s, %s, 'ru', 'en', true)
        on conflict (id) do update set
            email=excluded.email,
            password_hash=excluded.password_hash,
            email_verified=true
        """,
        (user_id, email, password_hash),
    )


def update_user_settings(
    conn,
    user_id: str,
    native_language: str,
    target_language: str,
    tts_enabled: bool,
    tts_voice: str,
    tts_rate: float,
    tts_pitch: float,
    tts_volume: float,
) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        update users set
            native_language=%s,
            target_language=%s,
            tts_enabled=%s,
            tts_voice=%s,
            tts_rate=%s,
            tts_pitch=%s,
            tts_volume=%s
        where id=%s
        returning *
        """,
        (native_language, target_language, tts_enabled, tts_voice, tts_rate, tts_pitch, tts_volume, user_id),
    )


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
def create_session(conn, token: str, user_id: str) -> None:
    query_one(
        conn,
        "insert into sessions (token, user_id) values (%s, %s) returning token",
        (token, user_id),
    )


def delete_session(conn, token: str) -> None:
    execute(conn, "delete from sessions where token=%s", (token,))


# ---------------------------------------------------------------------------
# email_verification_codes
# ---------------------------------------------------------------------------
def upsert_verification_code(
    conn,
    email: str,
    password_hash: str,
    native_language: str,
    target_language: str,
    code_hash: str,
    expires_at: datetime,
) -> None:
    query_one(
        conn,
        """
        insert into email_verification_codes
            (email, password_hash, native_language, target_language, code_hash, expires_at)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (email) do update set
            password_hash=excluded.password_hash,
            native_language=excluded.native_language,
            target_language=excluded.target_language,
            code_hash=excluded.code_hash,
            attempts=0,
            expires_at=excluded.expires_at,
            created_at=now()
        returning email
        """,
        (email, password_hash, native_language, target_language, code_hash, expires_at),
    )


def find_verification_code(conn, email: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from email_verification_codes where email=%s", (email,))


def delete_verification_code(conn, email: str) -> None:
    execute(conn, "delete from email_verification_codes where email=%s", (email,))


def increment_verification_attempts(conn, email: str) -> None:
    execute(
        conn,
        "update email_verification_codes set attempts=attempts+1 where email=%s",
        (email,),
    )
