"""SQL access for reference lexicons: MUSE translations, WordNet entries,
the phrase dictionary and system term lists."""

from __future__ import annotations

from typing import Any

from app.core.database import query_all, query_one


# ---------------------------------------------------------------------------
# system_terms
# ---------------------------------------------------------------------------
def terms_of_type(conn, term_type: str) -> set[str]:
    return {
        row["term"]
        for row in query_all(
            conn,
            "select term from system_terms where term_type=%s",
            (term_type,),
        )
    }


# ---------------------------------------------------------------------------
# muse_translations
# ---------------------------------------------------------------------------
def muse_count(conn) -> int:
    row = query_one(conn, "select count(*)::int as count from muse_translations")
    return row["count"] if row else 0


def bulk_insert_muse(conn, rows: list[tuple[str, str, int]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into muse_translations (source, target, rank)
            values (%s, %s, %s)
            on conflict (source, target) do update set rank=least(muse_translations.rank, excluded.rank)
            """,
            rows,
        )


def muse_targets(conn, source: str, limit: int) -> list[dict[str, Any]]:
    return query_all(
        conn,
        """
        select target
        from muse_translations
        where source=%s
        order by rank
        limit %s
        """,
        (source, limit),
    )


# ---------------------------------------------------------------------------
# wordnet_entries
# ---------------------------------------------------------------------------
def wordnet_stats(conn) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select count(*)::int as count, min(sense_rank)::int as min_rank from wordnet_entries",
    )


def bulk_insert_wordnet(conn, entries: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into wordnet_entries (lemma, pos, definition, synonyms, source_offset, sense_rank)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (lemma, pos, source_offset) do update set sense_rank=excluded.sense_rank
            """,
            entries,
        )


def bulk_update_wordnet_ranks(conn, rank_rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "update wordnet_entries set sense_rank=%s where lemma=%s and pos=%s and source_offset=%s",
            rank_rows,
        )


def wordnet_entry(conn, lemma: str, pos: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select definition, synonyms
        from wordnet_entries
        where lemma=%s and pos=%s
        order by sense_rank, id
        limit 1
        """,
        (lemma, pos),
    )


def wordnet_entry_any_pos(conn, lemma: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select definition, synonyms
        from wordnet_entries
        where lemma=%s
        order by sense_rank, id
        limit 1
        """,
        (lemma,),
    )


# ---------------------------------------------------------------------------
# phrase_dictionary
# ---------------------------------------------------------------------------
def phrase_dictionary(conn, language: str = "en") -> list[dict[str, Any]]:
    return query_all(
        conn,
        """
        select base_form, type, translation_ru
        from phrase_dictionary
        where language=%s
        order by length(base_form) desc, base_form
        """,
        (language,),
    )


def phrase_translation_by_type(conn, language: str, base_form: str, phrase_type: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select translation_ru
        from phrase_dictionary
        where language=%s and base_form=%s and type=%s
        limit 1
        """,
        (language, base_form, phrase_type),
    )


def phrase_translation_any_type(conn, language: str, base_form: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        """
        select translation_ru
        from phrase_dictionary
        where language=%s and base_form=%s
        order by case when type='phrasal_verb' then 0 else 1 end, type
        limit 1
        """,
        (language, base_form),
    )
