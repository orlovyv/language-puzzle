"""SQL access for the ``documents`` table."""

from __future__ import annotations

from typing import Any

from app.core.database import execute, query_all, query_one


def insert_document(
    conn,
    document_id: str,
    user_id: str,
    title: str,
    doc_type: str,
    language: str,
    raw_text: str,
    clean_text: str,
) -> dict[str, Any]:
    return query_one(
        conn,
        "insert into documents (id, user_id, title, type, language, raw_text, clean_text) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning *",
        (document_id, user_id, title, doc_type, language, raw_text, clean_text),
    )


def find_document(conn, document_id: str, user_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from documents where id=%s and user_id=%s",
        (document_id, user_id),
    )


def user_documents(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select * from documents where user_id=%s order by created_at desc",
        (user_id,),
    )


def delete_document(conn, document_id: str, user_id: str) -> None:
    execute(conn, "delete from documents where id=%s and user_id=%s", (document_id, user_id))


def update_clean_text(conn, document_id: str, clean_text: str) -> None:
    execute(conn, "update documents set clean_text=%s where id=%s", (clean_text, document_id))


def find_document_with_analysis(conn, user_id: str, document_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select d.*, a.payload from documents d join analyses a on a.document_id=d.id "
        "where d.user_id=%s and d.id=%s limit 1",
        (user_id, document_id),
    )


def latest_document_with_analysis(conn, user_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select d.*, a.payload from documents d join analyses a on a.document_id=d.id "
        "where d.user_id=%s order by d.created_at desc limit 1",
        (user_id,),
    )
