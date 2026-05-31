"""SQL access for the ``phrases`` and ``user_phrases`` tables."""

from __future__ import annotations

from typing import Any

from app.core.database import query_all, query_one


# ---------------------------------------------------------------------------
# phrases
# ---------------------------------------------------------------------------
def find_phrase(conn, language: str, base_form: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from phrases where language=%s and base_form=%s",
        (language, base_form),
    )


def insert_phrase(
    conn,
    phrase_id: str,
    language: str,
    phrase: str,
    base_form: str,
    phrase_type: str,
    translation_ru: str,
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into phrases (id, language, phrase, base_form, type, translation_ru)
        values (%s, %s, %s, %s, %s, %s)
        returning *
        """,
        (phrase_id, language, phrase, base_form, phrase_type, translation_ru),
    )


def update_phrase_translation(conn, phrase_id: str, translation_ru: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update phrases set translation_ru=%s where id=%s returning *",
        (translation_ru, phrase_id),
    )


# ---------------------------------------------------------------------------
# user_phrases
# ---------------------------------------------------------------------------
def find_user_phrase(conn, user_id: str, phrase_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from user_phrases where user_id=%s and phrase_id=%s",
        (user_id, phrase_id),
    )


def user_phrases(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(conn, "select * from user_phrases where user_id=%s", (user_id,))


def insert_user_phrase(conn, knowledge_id: str, user_id: str, phrase_id: str) -> dict[str, Any]:
    return query_one(
        conn,
        "insert into user_phrases (id, user_id, phrase_id, status, confidence) "
        "values (%s, %s, %s, 'unknown', 0.1) returning *",
        (knowledge_id, user_id, phrase_id),
    )


def update_user_phrase_status(
    conn,
    knowledge_id: str,
    user_id: str,
    status: str,
    confidence: float,
) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update user_phrases set status=%s, confidence=%s where id=%s and user_id=%s returning *",
        (status, confidence, knowledge_id, user_id),
    )


def find_user_phrase_with_phrase(conn, knowledge_id: str, user_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select up.id as user_phrase_id, p.*
        from user_phrases up
        join phrases p on p.id=up.phrase_id
        where up.id=%s and up.user_id=%s
        """,
        (knowledge_id, user_id),
    )


def known_phrase_base_forms(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select p.base_form from user_phrases up join phrases p on p.id=up.phrase_id "
        "where up.user_id=%s and up.status in ('known', 'ignored')",
        (user_id,),
    )


def user_phrases_with_phrase_rows(conn, user_id: str) -> list[dict[str, Any]]:
    """Joined rows used to refresh Learn block units from current knowledge."""
    return query_all(
        conn,
        """
        select up.id, up.status, up.confidence, p.id as phrase_id, p.base_form,
               p.phrase, p.translation_ru, p.type
        from user_phrases up
        join phrases p on p.id=up.phrase_id
        where up.user_id=%s
        """,
        (user_id,),
    )


def user_phrases_with_phrase_json(conn, user_id: str, status: str | None) -> list[dict[str, Any]]:
    params: list[Any] = [user_id]
    extra = ""
    if status:
        extra = " and up.status=%s"
        params.append(status)
    return query_all(
        conn,
        "select up.*, row_to_json(p.*) as phrase from user_phrases up "
        f"join phrases p on p.id=up.phrase_id where up.user_id=%s{extra} order by p.base_form",
        tuple(params),
    )
