"""SQL access for the ``analyses`` and ``reviews`` tables."""

from __future__ import annotations

import json
from typing import Any

from app.core.database import query_all, query_one


def find_analysis_payload(conn, document_id: str) -> dict[str, Any] | None:
    row = query_one(conn, "select payload from analyses where document_id=%s", (document_id,))
    return row["payload"] if row else None


def find_user_analysis_payload(conn, user_id: str, document_id: str) -> dict[str, Any] | None:
    row = query_one(
        conn,
        "select payload from analyses where document_id=%s and user_id=%s",
        (document_id, user_id),
    )
    return row["payload"] if row else None


def user_analysis_payloads(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select payload from analyses where user_id=%s order by created_at desc",
        (user_id,),
    )


def all_analyses_with_user(conn) -> list[dict[str, Any]]:
    return query_all(conn, "select a.payload, u.* from analyses a join users u on u.id = a.user_id")


def upsert_analysis(conn, payload: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into analyses (id, document_id, user_id, total_words, unique_words, known_words,
                                  unknown_words, ignored_words, coverage_percent, unique_coverage_percent,
                                  projected_coverage_percent, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (document_id) do update set
                total_words=excluded.total_words,
                unique_words=excluded.unique_words,
                known_words=excluded.known_words,
                unknown_words=excluded.unknown_words,
                ignored_words=excluded.ignored_words,
                coverage_percent=excluded.coverage_percent,
                unique_coverage_percent=excluded.unique_coverage_percent,
                projected_coverage_percent=excluded.projected_coverage_percent,
                payload=excluded.payload,
                created_at=now()
            """,
            (
                payload["id"],
                payload["document_id"],
                payload["user_id"],
                payload["total_words"],
                payload["unique_words"],
                payload["known_words"],
                payload["unknown_words"],
                payload["ignored_words"],
                payload["coverage_percent"],
                payload["unique_coverage_percent"],
                payload["projected_coverage_percent"],
                json.dumps(payload),
            ),
        )


def update_analysis_payload(conn, payload: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update analyses set
                known_words=%s,
                unknown_words=%s,
                ignored_words=%s,
                coverage_percent=%s,
                unique_coverage_percent=%s,
                projected_coverage_percent=%s,
                payload=%s,
                created_at=now()
            where document_id=%s
            """,
            (
                payload["known_words"],
                payload["unknown_words"],
                payload["ignored_words"],
                payload["coverage_percent"],
                payload["unique_coverage_percent"],
                payload["projected_coverage_percent"],
                json.dumps(payload),
                payload["document_id"],
            ),
        )


def insert_review(conn, review_id: str, user_id: str, word_id: str, grade: int) -> None:
    query_one(
        conn,
        "insert into reviews (id, user_id, word_id, grade) values (%s, %s, %s, %s) returning id",
        (review_id, user_id, word_id, grade),
    )
