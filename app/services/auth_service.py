from __future__ import annotations

from app.utils.security import hash_password


def password_matches(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash
