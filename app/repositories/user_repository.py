from __future__ import annotations

from typing import Any


def find_user_by_email(conn, email: str) -> dict[str, Any] | None:
    from app.routes.api import query_one

    return query_one(conn, "select * from users where email=%s", (email,))


def find_user_by_id(conn, user_id: str) -> dict[str, Any] | None:
    from app.routes.api import query_one

    return query_one(conn, "select * from users where id=%s", (user_id,))
