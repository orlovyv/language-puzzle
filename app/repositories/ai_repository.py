"""SQL access for AI enrichment: persistent response cache and daily usage."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.core.database import query_one


# ---------------------------------------------------------------------------
# ai_cache
# ---------------------------------------------------------------------------
def get_cached(conn, cache_key: str) -> Any | None:
    row = query_one(conn, "select payload from ai_cache where cache_key=%s", (cache_key,))
    return row["payload"] if row else None


def put_cached(conn, cache_key: str, task: str, payload: Any) -> None:
    query_one(
        conn,
        """
        insert into ai_cache (cache_key, task, payload)
        values (%s, %s, %s)
        on conflict (cache_key) do update set payload=excluded.payload, created_at=now()
        returning cache_key
        """,
        (cache_key, task, json.dumps(payload)),
    )


# ---------------------------------------------------------------------------
# ai_usage
# ---------------------------------------------------------------------------
def usage_today(conn, user_id: str, usage_day: date) -> int:
    row = query_one(
        conn,
        "select count from ai_usage where user_id=%s and usage_day=%s",
        (user_id, usage_day),
    )
    return row["count"] if row else 0


def increment_usage(conn, user_id: str, usage_day: date) -> int:
    row = query_one(
        conn,
        """
        insert into ai_usage (user_id, usage_day, count)
        values (%s, %s, 1)
        on conflict (user_id, usage_day) do update set count=ai_usage.count + 1
        returning count
        """,
        (user_id, usage_day),
    )
    return row["count"] if row else 0
