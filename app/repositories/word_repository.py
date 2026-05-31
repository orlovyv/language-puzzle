"""SQL access for the ``words`` and ``user_words`` tables."""

from __future__ import annotations

from typing import Any

from app.core.database import query_all, query_one


# ---------------------------------------------------------------------------
# words
# ---------------------------------------------------------------------------
def find_word(conn, language: str, lemma: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from words where language=%s and lemma=%s", (language, lemma))


def find_word_by_id(conn, word_id: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from words where id=%s", (word_id,))


def insert_word(
    conn,
    word_id: str,
    language: str,
    lemma: str,
    part_of_speech: str,
    translation_ru: str,
    transcription: str,
    frequency_rank: int,
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into words (id, language, lemma, part_of_speech, translation_ru, transcription, frequency_rank)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning *
        """,
        (word_id, language, lemma, part_of_speech, translation_ru, transcription, frequency_rank),
    )


def update_word_translation(conn, word_id: str, translation_ru: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update words set translation_ru=%s where id=%s returning *",
        (translation_ru, word_id),
    )


def update_word_transcription(conn, word_id: str, transcription: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update words set transcription=%s where id=%s returning *",
        (transcription, word_id),
    )


def all_words(conn) -> list[dict[str, Any]]:
    return query_all(conn, "select * from words")


def words_with_unresolved_translation(conn) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select id, lemma from words where translation_ru = %s or translation_ru like %s or translation_ru ~ %s",
        ("перевод уточняется", "WordNet:%", "[A-Za-z]"),
    )


def words_missing_translation(conn) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select id, lemma from words where translation_ru=%s",
        ("перевод уточняется",),
    )


def words_pending_wordnet(conn) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select id, lemma, part_of_speech from words where translation_ru = %s or translation_ru like %s",
        ("перевод уточняется", "WordNet:%"),
    )


def words_missing_transcription(conn, language: str = "en") -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select id, lemma from words where language=%s and coalesce(transcription, '')=''",
        (language,),
    )


# ---------------------------------------------------------------------------
# user_words
# ---------------------------------------------------------------------------
def find_user_word(conn, user_id: str, word_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from user_words where user_id=%s and word_id=%s",
        (user_id, word_id),
    )


def insert_user_word(
    conn,
    knowledge_id: str,
    user_id: str,
    word_id: str,
    status: str,
    confidence: float,
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into user_words (id, user_id, word_id, status, confidence, last_seen_at)
        values (%s, %s, %s, %s, %s, now())
        returning *
        """,
        (knowledge_id, user_id, word_id, status, confidence),
    )


def user_words(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(conn, "select * from user_words where user_id=%s", (user_id,))


def update_user_word_status(
    conn,
    knowledge_id: str,
    user_id: str,
    status: str,
    confidence: float,
) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update user_words set status=%s, confidence=%s, last_reviewed_at=now() where id=%s and user_id=%s returning *",
        (status, confidence, knowledge_id, user_id),
    )


def find_user_word_with_word(conn, knowledge_id: str, user_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select uw.id as user_word_id, w.*
        from user_words uw
        join words w on w.id=uw.word_id
        where uw.id=%s and uw.user_id=%s
        """,
        (knowledge_id, user_id),
    )


def known_lemmas(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select w.lemma from user_words uw join words w on w.id=uw.word_id "
        "where uw.user_id=%s and uw.status in ('known', 'ignored')",
        (user_id,),
    )


def user_words_with_word_rows(conn, user_id: str) -> list[dict[str, Any]]:
    """Joined rows used to refresh Learn block units from current knowledge."""
    return query_all(
        conn,
        """
        select uw.id, uw.status, uw.confidence, w.id as word_id, w.lemma, w.translation_ru,
               w.transcription, w.part_of_speech, w.frequency_rank
        from user_words uw
        join words w on w.id=uw.word_id
        where uw.user_id=%s
        """,
        (user_id,),
    )


def user_words_with_word_json(conn, user_id: str, status: str | None) -> list[dict[str, Any]]:
    """Words page: user_words joined with the full word row as JSON."""
    params: list[Any] = [user_id]
    extra = ""
    if status:
        extra = " and uw.status=%s"
        params.append(status)
    return query_all(
        conn,
        "select uw.*, row_to_json(w.*) as word "
        "from user_words uw join words w on w.id=uw.word_id "
        f"where uw.user_id=%s{extra} and char_length(w.lemma) > 1 "
        "order by w.lemma",
        tuple(params),
    )
