"""Read-only aggregate queries for the admin panel."""

from __future__ import annotations

from typing import Any

from app.core.database import query_all, query_one


def platform_stats(conn) -> dict[str, Any]:
    return query_one(
        conn,
        """
        select
            (select count(*) from users)::int as users_total,
            (select count(*) from users where plan='premium'
                and (premium_until is null or premium_until >= now()))::int as premium_active,
            (select count(*) from users where is_blocked)::int as blocked,
            (select count(*) from documents)::int as documents_total,
            (select count(*) from user_words where status='learning')::int as learning_words,
            (select count(*) from user_words where status='known')::int as known_words,
            (select count(*) from payments where status='succeeded')::int as payments_succeeded,
            (select coalesce(sum(amount), 0) from payments where status='succeeded')::float as revenue_rub
        """,
    )


def list_users(conn, query: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    where = ""
    params: list[Any] = []
    if query:
        where = "where u.email ilike %s"
        params.append(f"%{query}%")
    params.extend([limit, offset])
    return query_all(
        conn,
        f"""
        select u.id, u.email, u.plan, u.premium_until, u.is_blocked,
               u.email_verified, u.must_change_password, u.created_at,
               (select count(*) from documents d where d.user_id=u.id)::int as documents_count,
               (select count(*) from user_words uw where uw.user_id=u.id)::int as vocabulary_count
        from users u
        {where}
        order by u.created_at desc
        limit %s offset %s
        """,
        tuple(params),
    )


def count_users(conn, query: str | None) -> int:
    if query:
        row = query_one(conn, "select count(*)::int as c from users where email ilike %s", (f"%{query}%",))
    else:
        row = query_one(conn, "select count(*)::int as c from users")
    return row["c"] if row else 0


def user_documents(conn, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return query_all(
        conn,
        """
        select id, title, type, language, created_at
        from documents where user_id=%s
        order by created_at desc limit %s
        """,
        (user_id, limit),
    )
