"""Application bootstrap: ensure the database exists, run migrations, seed the
demo account and import/backfill reference data."""

from __future__ import annotations

import tarfile
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from app.config import (
    DATABASE_URL,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    MUSE_DICTIONARY,
    USE_WORDNET_FALLBACK,
    WORDNET_ARCHIVE,
)
from app.core.database import db, open_pool
from app.core.migrations import run_migrations
from app.repositories import lexicon_repository, user_repository, word_repository
from app.services import analysis, translation
from app.utils.security import hash_password


def ensure_database_exists() -> None:
    parts = urlsplit(DATABASE_URL)
    db_name = parts.path.lstrip("/") or "language_puzzle"
    if not db_name or db_name == "postgres":
        return
    maintenance_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=2):
            return
    except psycopg.OperationalError as exc:
        if "does not exist" not in str(exc):
            return
    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1 from pg_database where datname=%s", (db_name,))
            if not cur.fetchone():
                cur.execute(sql.SQL("create database {}").format(sql.Identifier(db_name)))


def seed_demo_user() -> None:
    with db() as conn:
        user_repository.upsert_demo_user(conn, "u_demo", DEMO_EMAIL, hash_password(DEMO_PASSWORD))


def import_muse_if_needed() -> None:
    if not MUSE_DICTIONARY.exists():
        return
    with db() as conn:
        if lexicon_repository.muse_count(conn) > 0:
            translation.update_words_from_muse(conn)
            analysis.refresh_all_analysis_payloads(conn)
            return
        rows: list[tuple[str, str, int]] = []
        seen: set[tuple[str, str]] = set()
        with MUSE_DICTIONARY.open("r", encoding="utf-8") as file:
            for rank, line in enumerate(file, start=1):
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                source, target = parts[0].lower(), parts[1].lower()
                key = (source, target)
                if key in seen:
                    continue
                seen.add(key)
                rows.append((source, target, rank))
        lexicon_repository.bulk_insert_muse(conn, rows)
        translation.update_words_from_muse(conn)
        analysis.refresh_all_analysis_payloads(conn)


def import_wordnet_if_needed() -> None:
    if not WORDNET_ARCHIVE.exists():
        return
    with db() as conn:
        existing = lexicon_repository.wordnet_stats(conn)
        needs_import = not existing or existing["count"] == 0
        needs_rank_update = bool(
            existing and existing["count"] > 0 and (existing["min_rank"] is None or existing["min_rank"] >= 9999)
        )
        entries: list[tuple] = []
        with tarfile.open(WORDNET_ARCHIVE, "r:gz") as archive:
            sense_ranks = translation.load_wordnet_sense_ranks(archive)
            if needs_import:
                for pos_name in ("noun", "verb", "adj", "adv"):
                    member = archive.getmember(f"dict/data.{pos_name}")
                    extracted = archive.extractfile(member)
                    if not extracted:
                        continue
                    for raw in extracted:
                        line = raw.decode("utf-8", errors="replace").strip("\n")
                        source_offset = line.split(maxsplit=1)[0] if line and line[0].isdigit() else ""
                        for lemma, pos, definition, synonyms in translation.parse_wordnet_data_line(line, pos_name):
                            entries.append(
                                (lemma, pos, definition, synonyms, source_offset, sense_ranks.get((lemma, pos, source_offset), 9999))
                            )
                lexicon_repository.bulk_insert_wordnet(conn, entries)
            elif needs_rank_update:
                rank_rows = [(rank, lemma, pos, offset) for (lemma, pos, offset), rank in sense_ranks.items()]
                lexicon_repository.bulk_update_wordnet_ranks(conn, rank_rows)
        for word in word_repository.words_pending_wordnet(conn):
            lexical_value = translation.wordnet_definition(conn, word["lemma"], word["part_of_speech"])
            if lexical_value:
                word_repository.update_word_translation(conn, word["id"], lexical_value)


def backfill_unresolved_translations() -> None:
    with db() as conn:
        unresolved = word_repository.words_missing_translation(conn)
        if not unresolved:
            return
        updated = 0
        for row in unresolved:
            value = translation.resolve_lexical_translation(conn, row["lemma"], fallback="")
            if value:
                word_repository.update_word_translation(conn, row["id"], value)
                updated += 1
        if updated:
            analysis.refresh_all_analysis_payloads(conn)


def backfill_word_transcriptions() -> None:
    with db() as conn:
        rows = word_repository.words_missing_transcription(conn, "en")
        if not rows:
            return
        updated = 0
        for row in rows:
            transcription = translation.word_transcription(row["lemma"])
            if transcription:
                word_repository.update_word_transcription(conn, row["id"], transcription)
                updated += 1
        if updated:
            analysis.refresh_all_analysis_payloads(conn)


def startup() -> None:
    ensure_database_exists()
    open_pool()
    run_migrations()
    seed_demo_user()
    import_muse_if_needed()
    if USE_WORDNET_FALLBACK:
        import_wordnet_if_needed()
    backfill_unresolved_translations()
    backfill_word_transcriptions()
    _expire_overdue_subscriptions()


def _expire_overdue_subscriptions() -> None:
    from app.services.billing.subscription_service import expire_overdue

    with db() as conn:
        expire_overdue(conn)
