from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import io
import json
import os
import re
import secrets
import smtplib
import tarfile
from email.message import EmailMessage
from functools import lru_cache
from threading import Lock, Thread
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from spacy.matcher import PhraseMatcher
try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    from wordfreq import top_n_list, zipf_frequency
except ImportError:  # pragma: no cover
    top_n_list = None
    zipf_frequency = None
try:
    from googletrans import Translator as GoogleTranslator
except ImportError:  # pragma: no cover
    GoogleTranslator = None
try:
    import eng_to_ipa as eng_to_ipa_lib
except ImportError:  # pragma: no cover
    eng_to_ipa_lib = None

try:
    import spacy
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("spaCy is required. Install requirements.txt first.") from exc


from app.config import (
    APP_SECRET,
    DATABASE_URL,
    EMAIL_VERIFICATION_ENABLED,
    GOOGLETRANS_SOURCE_LANG,
    GOOGLETRANS_TARGET_LANG,
    MUSE_DICTIONARY,
    PUBLIC_DIR,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
    USE_GOOGLETRANS_FALLBACK,
    USE_IPA_TRANSCRIPTION,
    USE_WORDNET_FALLBACK,
    WORDNET_ARCHIVE,
)
from app.schemas.user_schema import (
    AnalyzePayload,
    AuthPayload,
    DocumentPayload,
    KnowledgeAnalyzePayload,
    KnowledgeBridgePayload,
    KnowledgeGoalPayload,
    LearnBlockPayload,
    LearnBlockUpdatePayload,
    LearnMergePayload,
    ReviewPayload,
    StatusPayload,
    TranslationPayload,
    VerifyRegistrationPayload,
)
from app.utils.security import hash_password, run_coroutine_from_sync, token_id

_GOOGLE_TRANSLATE_LOCK = Lock()
_GOOGLETRANS_CACHE: dict[str, str | None] = {}
_ANKI_EXAMPLE_TRANSLATION_CACHE: dict[str, str | None] = {}

SUPPORTED_DOCUMENT_TYPES = {"text", "srt", "book_chapter", "article"}
MAX_RAW_TEXT_LINES = 2000
_IPA_LOCK = Lock()
_IPA_CACHE: dict[str, str] = {}

router = APIRouter()
VERIFICATION_CODE_TTL_MINUTES = 15
VERIFICATION_MAX_ATTEMPTS = 5
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

try:
    NLP = spacy.load("en_core_web_lg")
except OSError as exc:  # pragma: no cover
    raise RuntimeError("spaCy model en_core_web_lg is not installed.") from exc

KG_MIN_ZIPF = 3.0
KG_MAX_ZIPF = 5.35
KG_MAX_FREQUENCY_WORDS = 20000
KG_MAX_CANDIDATES = 2600


@contextmanager
def db():
    try:
        with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
            yield conn
            conn.commit()
    except psycopg.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PostgreSQL недоступен. Проверь DATABASE_URL. Деталь: {str(exc).splitlines()[0]}",
        ) from exc


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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row: tuple, columns: list[str]) -> dict[str, Any]:
    return dict(zip(columns, row))


def query_one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        return row_to_dict(row, [desc.name for desc in cur.description])


def query_all(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [desc.name for desc in cur.description]
        return [row_to_dict(row, cols) for row in rows]


def system_terms(conn, term_type: str) -> set[str]:
    return {
        row["term"]
        for row in query_all(
            conn,
            "select term from system_terms where term_type=%s",
            (term_type,),
        )
    }


def known_seed_terms(conn) -> set[str]:
    return system_terms(conn, "known_seed")


def context_topic_stopwords(conn) -> set[str]:
    return known_seed_terms(conn) | system_terms(conn, "context_topic_stopword")


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


def phrase_translation_lookup(conn, language: str = "en") -> dict[tuple[str, str], str]:
    return {
        (row["base_form"], row["type"]): row["translation_ru"]
        for row in phrase_dictionary(conn, language)
    }


def phrase_dictionary_translation(
    conn,
    phrase: str,
    phrase_type: str | None = None,
    language: str = "en",
) -> str | None:
    text = kg_normalize_phrase(phrase)
    if not text:
        return None
    if phrase_type:
        row = query_one(
            conn,
            """
            select translation_ru
            from phrase_dictionary
            where language=%s and base_form=%s and type=%s
            limit 1
            """,
            (language, text, phrase_type),
        )
        if row and has_resolved_translation(row["translation_ru"]):
            return row["translation_ru"]

    row = query_one(
        conn,
        """
        select translation_ru
        from phrase_dictionary
        where language=%s and base_form=%s
        order by case when type='phrasal_verb' then 0 else 1 end, type
        limit 1
        """,
        (language, text),
    )
    if row and has_resolved_translation(row["translation_ru"]):
        return row["translation_ru"]
    return None


def init_db() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists users (
                    id text primary key,
                    email text unique not null,
                    password_hash text not null,
                    native_language text not null default 'ru',
                    target_language text not null default 'en',
                    email_verified boolean not null default true,
                    tts_enabled boolean not null default true,
                    tts_voice text not null default '',
                    tts_rate real not null default 1,
                    tts_pitch real not null default 1,
                    tts_volume real not null default 1,
                    created_at timestamptz not null default now()
                );
                alter table users add column if not exists tts_enabled boolean not null default true;
                alter table users add column if not exists email_verified boolean not null default true;
                alter table users add column if not exists tts_voice text not null default '';
                alter table users add column if not exists tts_rate real not null default 1;
                alter table users add column if not exists tts_pitch real not null default 1;
                alter table users add column if not exists tts_volume real not null default 1;
                create table if not exists sessions (
                    token text primary key,
                    user_id text not null references users(id) on delete cascade,
                    created_at timestamptz not null default now()
                );
                create table if not exists email_verification_codes (
                    email text primary key,
                    password_hash text not null,
                    native_language text not null default 'ru',
                    target_language text not null default 'en',
                    code_hash text not null,
                    attempts integer not null default 0,
                    expires_at timestamptz not null,
                    created_at timestamptz not null default now()
                );
                create table if not exists documents (
                    id text primary key,
                    user_id text not null references users(id) on delete cascade,
                    title text not null,
                    type text not null,
                    language text not null,
                    raw_text text not null,
                    clean_text text not null,
                    created_at timestamptz not null default now()
                );
                create table if not exists words (
                    id text primary key,
                    language text not null,
                    lemma text not null,
                    part_of_speech text not null,
                    translation_ru text not null,
                    transcription text not null default '',
                    frequency_rank integer not null,
                    unique(language, lemma)
                );
                alter table words add column if not exists transcription text not null default '';
                create table if not exists user_words (
                    id text primary key,
                    user_id text not null references users(id) on delete cascade,
                    word_id text not null references words(id) on delete cascade,
                    status text not null,
                    confidence real not null,
                    last_seen_at timestamptz,
                    last_reviewed_at timestamptz,
                    unique(user_id, word_id)
                );
                create table if not exists phrases (
                    id text primary key,
                    language text not null,
                    phrase text not null,
                    base_form text not null,
                    type text not null,
                    translation_ru text not null,
                    unique(language, base_form)
                );
                create table if not exists user_phrases (
                    id text primary key,
                    user_id text not null references users(id) on delete cascade,
                    phrase_id text not null references phrases(id) on delete cascade,
                    status text not null,
                    confidence real not null,
                    unique(user_id, phrase_id)
                );
                create table if not exists analyses (
                    id text primary key,
                    document_id text not null references documents(id) on delete cascade,
                    user_id text not null references users(id) on delete cascade,
                    total_words integer not null,
                    unique_words integer not null,
                    known_words integer not null,
                    unknown_words integer not null,
                    ignored_words integer not null,
                    coverage_percent integer not null,
                    unique_coverage_percent integer not null,
                    projected_coverage_percent integer not null,
                    payload jsonb not null,
                    created_at timestamptz not null default now(),
                    unique(document_id)
                );
                create table if not exists reviews (
                    id text primary key,
                    user_id text not null references users(id) on delete cascade,
                    word_id text not null references words(id) on delete cascade,
                    grade integer not null,
                    created_at timestamptz not null default now()
                );
                create table if not exists learn_blocks (
                    id text primary key,
                    user_id text not null references users(id) on delete cascade,
                    title text not null,
                    frequency_filter text not null default 'all',
                    payload jsonb not null,
                    created_at timestamptz not null default now()
                );
                alter table learn_blocks add column if not exists frequency_filter text not null default 'all';
                create index if not exists idx_learn_blocks_user_created on learn_blocks(user_id, created_at, id);
                create table if not exists wordnet_entries (
                    id bigserial primary key,
                    lemma text not null,
                    pos text not null,
                    definition text not null,
                    synonyms text[] not null default '{}',
                    source_offset text not null,
                    sense_rank integer not null default 9999,
                    created_at timestamptz not null default now(),
                    unique(lemma, pos, source_offset)
                );
                alter table wordnet_entries add column if not exists sense_rank integer not null default 9999;
                create index if not exists idx_wordnet_entries_lemma on wordnet_entries(lemma);
                create index if not exists idx_wordnet_entries_lemma_pos on wordnet_entries(lemma, pos);
                create table if not exists muse_translations (
                    id bigserial primary key,
                    source text not null,
                    target text not null,
                    rank integer not null,
                    created_at timestamptz not null default now(),
                    unique(source, target)
                );
                create index if not exists idx_muse_translations_source_rank on muse_translations(source, rank);
                create table if not exists phrase_dictionary (
                    id bigserial primary key,
                    language text not null default 'en',
                    base_form text not null,
                    type text not null,
                    translation_ru text not null default 'перевод уточняется',
                    source text not null default 'manual',
                    created_at timestamptz not null default now(),
                    unique(language, base_form, type)
                );
                create index if not exists idx_phrase_dictionary_language_type on phrase_dictionary(language, type);
                create table if not exists system_terms (
                    id bigserial primary key,
                    term_type text not null,
                    term text not null,
                    source text not null default 'system',
                    created_at timestamptz not null default now(),
                    unique(term_type, term)
                );
                create index if not exists idx_system_terms_type on system_terms(term_type);
                """
            )
            cur.execute(
                """
                insert into system_terms (term_type, term) values
                    ('known_seed', 'the'),
                    ('known_seed', 'be'),
                    ('known_seed', 'to'),
                    ('known_seed', 'of'),
                    ('known_seed', 'and'),
                    ('known_seed', 'a'),
                    ('known_seed', 'in'),
                    ('known_seed', 'that'),
                    ('known_seed', 'have'),
                    ('known_seed', 'i'),
                    ('known_seed', 'me'),
                    ('known_seed', 'it'),
                    ('known_seed', 'for'),
                    ('known_seed', 'not'),
                    ('known_seed', 'on'),
                    ('known_seed', 'with'),
                    ('known_seed', 'he'),
                    ('known_seed', 'as'),
                    ('known_seed', 'you'),
                    ('known_seed', 'do'),
                    ('known_seed', 'at'),
                    ('context_topic_stopword', 'say'),
                    ('context_topic_stopword', 'tell'),
                    ('context_topic_stopword', 'get'),
                    ('context_topic_stopword', 'go'),
                    ('context_topic_stopword', 'come'),
                    ('context_topic_stopword', 'make'),
                    ('context_topic_stopword', 'take'),
                    ('context_topic_stopword', 'give'),
                    ('context_topic_stopword', 'see'),
                    ('context_topic_stopword', 'know'),
                    ('context_topic_stopword', 'think'),
                    ('context_topic_stopword', 'want'),
                    ('context_topic_stopword', 'need'),
                    ('context_topic_stopword', 'try'),
                    ('context_topic_stopword', 'thing'),
                    ('context_topic_stopword', 'something'),
                    ('context_topic_stopword', 'nothing'),
                    ('context_topic_stopword', 'one'),
                    ('context_topic_stopword', 'all'),
                    ('context_topic_stopword', 'this'),
                    ('context_topic_stopword', 'that'),
                    ('context_topic_stopword', 'there'),
                    ('context_topic_stopword', 'here'),
                    ('kg_blocked_entity_label', 'PERSON'),
                    ('kg_blocked_entity_label', 'GPE'),
                    ('kg_blocked_entity_label', 'LOC'),
                    ('kg_blocked_entity_label', 'NORP'),
                    ('kg_blocked_entity_label', 'ORG'),
                    ('kg_blocked_entity_label', 'FAC'),
                    ('kg_blocked_single_word', 'west'),
                    ('kg_blocked_single_word', 'east'),
                    ('kg_blocked_single_word', 'north'),
                    ('kg_blocked_single_word', 'south'),
                    ('kg_blocked_single_word', 'french'),
                    ('kg_blocked_single_word', 'german'),
                    ('kg_blocked_single_word', 'russian'),
                    ('kg_blocked_single_word', 'spanish'),
                    ('kg_blocked_single_word', 'italian'),
                    ('kg_blocked_single_word', 'usa'),
                    ('kg_blocked_single_word', 'uk'),
                    ('kg_blocked_single_word', 'europe'),
                    ('kg_blocked_single_word', 'asia')
                on conflict (term_type, term) do nothing
                """
            )
            cur.execute(
                """
                insert into users (id, email, password_hash, native_language, target_language, email_verified)
                values (%s, %s, %s, 'ru', 'en', true)
                on conflict (id) do update set
                    email=excluded.email,
                    password_hash=excluded.password_hash,
                    email_verified=true
                """,
                ("u_demo", "demo@local.ru", hash_password("123")),
            )


def startup() -> None:
    ensure_database_exists()
    init_db()
    import_muse_if_needed()
    if USE_WORDNET_FALLBACK:
        import_wordnet_if_needed()
    backfill_unresolved_translations()
    backfill_word_transcriptions()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "native_language": user["native_language"],
        "target_language": user["target_language"],
        "tts_enabled": bool(user.get("tts_enabled", True)),
        "tts_voice": user.get("tts_voice") or "",
        "tts_rate": float(user.get("tts_rate") or 1),
        "tts_pitch": float(user.get("tts_pitch") or 1),
        "tts_volume": float(user.get("tts_volume") or 1),
        "created_at": str(user["created_at"]),
    }


def current_user(conn, lp_session: str | None, authorization: str | None) -> dict[str, Any] | None:
    token = lp_session or (authorization.replace("Bearer ", "") if authorization and authorization.lower().startswith("bearer ") else None)
    if not token:
        return None
    return query_one(
        conn,
        """
        select u.* from users u
        join sessions s on s.user_id = u.id
        where s.token = %s
        """,
        (token,),
    )


def require_user(conn, lp_session: str | None, authorization: str | None) -> dict[str, Any]:
    user = current_user(conn, lp_session, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Нужно войти.")
    return user


def count_text_lines(value: str) -> int:
    return len(re.split(r"\r\n|\r|\n", value)) if value else 0


def looks_like_binary_text(value: str) -> bool:
    if "\x00" in value:
        return True
    if not value:
        return False
    suspicious = sum(1 for char in value if ord(char) < 32 and char not in "\t\n\r")
    return suspicious / len(value) > 0.05


def validate_document_payload(payload: DocumentPayload) -> None:
    if payload.type not in SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип документа.")
    if looks_like_binary_text(payload.raw_text):
        raise HTTPException(status_code=400, detail="Похоже, это бинарный файл. Загрузите текстовый .txt или .srt.")
    lines = count_text_lines(payload.raw_text)
    if lines > MAX_RAW_TEXT_LINES:
        raise HTTPException(status_code=400, detail=f"Текст слишком длинный: {lines} строк. Максимум {MAX_RAW_TEXT_LINES} строк.")


def clean_text(raw: str, doc_type: str = "text") -> str:
    text = (raw or "").replace("\r", "\n")
    subtitle_like = bool(
        re.search(
            r"\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b",
            text,
        )
    )
    if doc_type == "srt" or subtitle_like:
        text = re.sub(
            r"\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b",
            " ",
            text,
        )
        lines = []
        for line in text.split("\n"):
            value = line.strip()
            if re.fullmatch(r"\d+", value):
                continue
            if re.search(r"\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b", value):
                continue
            lines.append(line)
        text = "\n".join(lines)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"\bAII\b", "All", text)
    text = re.sub(r"\bI'II\b", "I'll", text)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_lemma(token) -> str:
    text = token.text.lower()
    if text == "aii":
        return "all"
    if text == "i'ii":
        return "i'll"
    lemma = token.lemma_.lower() if token.lemma_ and token.lemma_ != "-PRON-" else text
    if lemma == "aii":
        lemma = "all"
    if lemma == "i'ii":
        lemma = "i'll"
    return lemma


def is_short_word(value: str | None) -> bool:
    letters_only = re.sub(r"[^a-z]", "", str(value or "").lower())
    return len(letters_only) <= 1


def normalize_transcription(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or "*" in text:
        return ""
    return text[:120]


def word_transcription(lemma: str) -> str:
    key = (lemma or "").strip().lower()
    if not key or not USE_IPA_TRANSCRIPTION or eng_to_ipa_lib is None:
        return ""
    cached = _IPA_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with _IPA_LOCK:
            raw = eng_to_ipa_lib.convert(key)
        value = normalize_transcription(raw)
    except Exception:
        value = ""
    _IPA_CACHE[key] = value
    return value


def rank_for(lemma: str) -> int:
    common = ["be", "have", "do", "say", "go", "get", "make", "know", "think", "take", "see", "come", "want", "look", "use", "find", "give", "tell", "work", "call"]
    return common.index(lemma) + 1 if lemma in common else min(9000, 600 + len(lemma) * 137)


def confidence_for(status: str) -> float:
    return {"unknown": 0.1, "seen": 0.35, "learning": 0.6, "known": 0.95, "ignored": 1}.get(status, 0.1)


def clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def parse_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(normalize_email(value)))


def verification_code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{APP_SECRET}:{normalize_email(email)}:{code}".encode()).hexdigest()


def send_verification_email(email: str, code: str) -> None:
    subject = "Language Puzzle verification code"
    body = (
        "Код подтверждения Language Puzzle: "
        f"{code}\n\nОн действует {VERIFICATION_CODE_TTL_MINUTES} минут."
    )
    if not SMTP_HOST:
        print(f"[Language Puzzle] Verification code for {email}: {code}")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = email
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def import_muse_if_needed() -> None:
    if not MUSE_DICTIONARY.exists():
        return
    with db() as conn:
        existing = query_one(conn, "select count(*)::int as count from muse_translations")
        if existing and existing["count"] > 0:
            update_words_from_muse(conn)
            refresh_all_analysis_payloads(conn)
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
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into muse_translations (source, target, rank)
                values (%s, %s, %s)
                on conflict (source, target) do update set rank=least(muse_translations.rank, excluded.rank)
                """,
                rows,
            )
        update_words_from_muse(conn)
        refresh_all_analysis_payloads(conn)


def muse_translation(conn, lemma: str, limit: int = 3) -> str | None:
    rows = query_all(
        conn,
        """
        select target
        from muse_translations
        where source=%s
        order by rank
        limit %s
        """,
        (lemma.lower().replace(" ", "_"), limit),
    )
    translations = []
    fallback = []
    for row in rows:
        value = row["target"].replace("_", " ")
        if value not in fallback:
            fallback.append(value)
        if re.search(r"[а-яёА-ЯЁ]", value) and value not in translations:
            translations.append(value)
    if not translations:
        translations = fallback
    return ", ".join(translations) if translations else None


def run_googletrans_translate(text: str):
    if GoogleTranslator is None:
        return None

    async def _translate():
        client = GoogleTranslator(service_urls=["translate.googleapis.com"])
        return await client.translate(text, src=GOOGLETRANS_SOURCE_LANG, dest=GOOGLETRANS_TARGET_LANG)

    return run_coroutine_from_sync(_translate)


def googletrans_translation(lemma: str) -> str | None:
    key = (lemma or "").strip().lower()
    if not key:
        return None
    if key in _GOOGLETRANS_CACHE:
        return _GOOGLETRANS_CACHE[key]
    if not USE_GOOGLETRANS_FALLBACK:
        _GOOGLETRANS_CACHE[key] = None
        return None
    try:
        with _GOOGLE_TRANSLATE_LOCK:
            translated = run_googletrans_translate(key)
        value = re.sub(r"\s+", " ", str(getattr(translated, "text", "") or "")).strip()
        if value and value.lower() != key:
            _GOOGLETRANS_CACHE[key] = value[:500]
            return _GOOGLETRANS_CACHE[key]
    except Exception:
        pass
    _GOOGLETRANS_CACHE[key] = None
    return None


def resolve_lexical_translation(
    conn,
    lemma: str,
    fallback: str = "перевод уточняется",
    allow_googletrans: bool = False,
) -> str:
    return (
        muse_translation(conn, lemma)
        or (googletrans_translation(lemma) if allow_googletrans else None)
        or fallback
    )


def has_resolved_translation(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "перевод уточняется")


def clean_client_translation(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not has_resolved_translation(text):
        return ""
    return text[:500]


def load_word_translation_on_demand(
    conn,
    user: dict[str, Any],
    knowledge_id: str,
    translation_ru: str | None = None,
) -> dict[str, Any]:
    row = query_one(
        conn,
        """
        select uw.id as user_word_id, w.*
        from user_words uw
        join words w on w.id=uw.word_id
        where uw.id=%s and uw.user_id=%s
        """,
        (knowledge_id, user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Слово не найдено.")
    if has_resolved_translation(row.get("translation_ru")):
        return row

    translation = clean_client_translation(translation_ru)
    if translation:
        row = query_one(
            conn,
            "update words set translation_ru=%s where id=%s returning *",
            (translation, row["id"]),
        )
        rerun_user_analyses(conn, user)
        return {**row, "user_word_id": knowledge_id}

    return row


def load_phrase_translation_on_demand(
    conn,
    user: dict[str, Any],
    knowledge_id: str,
    translation_ru: str | None = None,
) -> dict[str, Any]:
    row = query_one(
        conn,
        """
        select up.id as user_phrase_id, p.*
        from user_phrases up
        join phrases p on p.id=up.phrase_id
        where up.id=%s and up.user_id=%s
        """,
        (knowledge_id, user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Фраза не найдена.")
    if has_resolved_translation(row.get("translation_ru")):
        return row

    phrase = row.get("base_form") or row.get("phrase")
    translation = phrase_dictionary_translation(
        conn,
        phrase,
        phrase_type=row.get("type"),
        language=row.get("language") or user.get("target_language") or "en",
    )
    if not translation:
        translation = clean_client_translation(translation_ru)
    if translation:
        row = query_one(
            conn,
            "update phrases set translation_ru=%s where id=%s returning *",
            (translation, row["id"]),
        )
        rerun_user_analyses(conn, user)
        return {**row, "user_phrase_id": knowledge_id}

    return row


def update_words_from_muse(conn) -> None:
    unresolved = query_all(
        conn,
        "select id, lemma from words where translation_ru = %s or translation_ru like %s or translation_ru ~ %s",
        ("перевод уточняется", "WordNet:%", "[A-Za-z]"),
    )
    with conn.cursor() as cur:
        for word in unresolved:
            value = resolve_lexical_translation(conn, word["lemma"], fallback="")
            if value:
                cur.execute("update words set translation_ru=%s where id=%s", (value, word["id"]))


def refresh_all_analysis_payloads(conn) -> None:
    rows = query_all(conn, "select a.payload, u.* from analyses a join users u on u.id = a.user_id")
    for row in rows:
        payload = row.pop("payload")
        payload = refresh_analysis_payload(conn, row, payload, preserve_important=True)
        save_analysis_payload(conn, payload)


def backfill_unresolved_translations() -> None:
    with db() as conn:
        unresolved = query_all(conn, "select id, lemma from words where translation_ru=%s", ("перевод уточняется",))
        if not unresolved:
            return
        updated = 0
        with conn.cursor() as cur:
            for row in unresolved:
                value = resolve_lexical_translation(conn, row["lemma"], fallback="")
                if value:
                    cur.execute("update words set translation_ru=%s where id=%s", (value, row["id"]))
                    updated += 1
        if updated:
            refresh_all_analysis_payloads(conn)


def backfill_word_transcriptions() -> None:
    with db() as conn:
        rows = query_all(
            conn,
            "select id, lemma from words where language=%s and coalesce(transcription, '')=''",
            ("en",),
        )
        if not rows:
            return
        updated = 0
        with conn.cursor() as cur:
            for row in rows:
                transcription = word_transcription(row["lemma"])
                if transcription:
                    cur.execute("update words set transcription=%s where id=%s", (transcription, row["id"]))
                    updated += 1
        if updated:
            refresh_all_analysis_payloads(conn)


def wordnet_lemma(value: str) -> str:
    return value.lower().replace(" ", "_")


def wordnet_pos(pos: str | None) -> str | None:
    value = (pos or "").lower()
    return {
        "noun": "n",
        "propn": "n",
        "verb": "v",
        "aux": "v",
        "adj": "a",
        "adjective": "a",
        "adv": "r",
        "adverb": "r",
        "n": "n",
        "v": "v",
        "a": "a",
        "s": "a",
        "r": "r",
    }.get(value)


def parse_wordnet_data_line(line: str, pos_name: str) -> list[tuple[str, str, str, list[str]]]:
    if not line or line.startswith("  "):
        return []
    body, _, gloss = line.partition("|")
    parts = body.split()
    if len(parts) < 5 or not parts[0].isdigit():
        return []
    offset = parts[0]
    ss_type = parts[2]
    pos = {"n": "n", "v": "v", "a": "a", "s": "a", "r": "r"}.get(ss_type, wordnet_pos(pos_name) or pos_name[0])
    try:
        word_count = int(parts[3], 16)
    except ValueError:
        return []
    synonyms = []
    index = 4
    for _ in range(word_count):
        if index >= len(parts):
            break
        synonyms.append(parts[index].replace("_", " ").lower())
        index += 2
    if not synonyms:
        return []
    definition = gloss.split(";")[0].strip()
    if not definition:
        return []
    return [(lemma, pos, definition, synonyms) for lemma in synonyms]


def load_wordnet_sense_ranks(archive: tarfile.TarFile) -> dict[tuple[str, str, str], int]:
    ranks: dict[tuple[str, str, str], int] = {}
    for pos_name, pos in (("noun", "n"), ("verb", "v"), ("adj", "a"), ("adv", "r")):
        try:
            member = archive.getmember(f"dict/index.{pos_name}")
        except KeyError:
            continue
        extracted = archive.extractfile(member)
        if not extracted:
            continue
        for raw in extracted:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(" "):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            lemma = parts[0].replace("_", " ").lower()
            try:
                synset_count = int(parts[2])
                pointer_count = int(parts[3])
            except ValueError:
                continue
            offsets_start = 4 + pointer_count + 2
            offsets = parts[offsets_start:offsets_start + synset_count]
            for index, offset in enumerate(offsets):
                ranks[(lemma, pos, offset)] = index
    return ranks


def import_wordnet_if_needed() -> None:
    if not WORDNET_ARCHIVE.exists():
        return
    with db() as conn:
        existing = query_one(conn, "select count(*)::int as count, min(sense_rank)::int as min_rank from wordnet_entries")
        needs_import = not existing or existing["count"] == 0
        needs_rank_update = bool(existing and existing["count"] > 0 and (existing["min_rank"] is None or existing["min_rank"] >= 9999))
        entries: list[tuple[str, str, str, list[str], str]] = []
        with tarfile.open(WORDNET_ARCHIVE, "r:gz") as archive:
            sense_ranks = load_wordnet_sense_ranks(archive)
            if needs_import:
                for pos_name in ("noun", "verb", "adj", "adv"):
                    member = archive.getmember(f"dict/data.{pos_name}")
                    extracted = archive.extractfile(member)
                    if not extracted:
                        continue
                    for raw in extracted:
                        line = raw.decode("utf-8", errors="replace").strip("\n")
                        source_offset = line.split(maxsplit=1)[0] if line and line[0].isdigit() else ""
                        for lemma, pos, definition, synonyms in parse_wordnet_data_line(line, pos_name):
                            entries.append((lemma, pos, definition, synonyms, source_offset, sense_ranks.get((lemma, pos, source_offset), 9999)))
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        insert into wordnet_entries (lemma, pos, definition, synonyms, source_offset, sense_rank)
                        values (%s, %s, %s, %s, %s, %s)
                        on conflict (lemma, pos, source_offset) do update set sense_rank=excluded.sense_rank
                        """,
                        entries,
                    )
            elif needs_rank_update:
                rank_rows = [(rank, lemma, pos, offset) for (lemma, pos, offset), rank in sense_ranks.items()]
                with conn.cursor() as cur:
                    cur.executemany(
                        "update wordnet_entries set sense_rank=%s where lemma=%s and pos=%s and source_offset=%s",
                        rank_rows,
                    )
        unresolved = query_all(
            conn,
            "select id, lemma, part_of_speech from words where translation_ru = %s or translation_ru like %s",
            ("перевод уточняется", "WordNet:%"),
        )
        with conn.cursor() as cur:
            for word in unresolved:
                lexical_value = wordnet_definition(conn, word["lemma"], word["part_of_speech"])
                if lexical_value:
                    cur.execute("update words set translation_ru=%s where id=%s", (lexical_value, word["id"]))


def wordnet_definition(conn, lemma: str, pos: str | None) -> str | None:
    wn_pos = wordnet_pos(pos)
    normalized = wordnet_lemma(lemma)
    if wn_pos:
        entry = query_one(
            conn,
            """
            select definition, synonyms
            from wordnet_entries
            where lemma=%s and pos=%s
            order by sense_rank, id
            limit 1
            """,
            (normalized, wn_pos),
        )
        if entry:
            return format_wordnet_entry(entry)
    entry = query_one(
        conn,
        """
        select definition, synonyms
        from wordnet_entries
        where lemma=%s
        order by sense_rank, id
        limit 1
        """,
        (normalized,),
    )
    return format_wordnet_entry(entry) if entry else None


def format_wordnet_entry(entry: dict[str, Any]) -> str:
    synonyms = [item for item in (entry.get("synonyms") or []) if item]
    suffix = f"; syn: {', '.join(synonyms[:5])}" if len(synonyms) > 1 else ""
    return f"WordNet: {entry['definition']}{suffix}"[:500]


def priority_for(count: int, rank: int, status: str, lemma: str) -> float:
    if status == "ignored":
        return -1
    usefulness = max(0, 1000 - rank) / 80
    noise = 100 if len(lemma) <= 1 else 0
    return count * 10 + usefulness - noise


def grammar_patterns(sentences: list[str]) -> list[dict[str, Any]]:
    rules = {
        "past_simple": ("Past Simple", re.compile(r"\b\w+ed\b|\b(went|saw|made|knew|thought|took|gave|found|came|got|told|said|felt|left|did|had|was|were)\b", re.I)),
        "present_perfect": ("Present Perfect", re.compile(r"\b(has|have)\s+\w+(ed|en|ne|wn|ght|d|t)\b", re.I)),
        "future_will": ("Future with will", re.compile(r"\bwill\s+\w+\b", re.I)),
        "going_to_future": ("be going to", re.compile(r"\b(am|is|are|was|were)\s+going\s+to\b", re.I)),
        "used_to": ("used to", re.compile(r"\bused\s+to\b", re.I)),
        "modal_verb": ("Modal verbs", re.compile(r"\b(can|could|should|must|may|might|would)\b", re.I)),
        "present_continuous": ("Present Continuous", re.compile(r"\b(am|is|are)\s+\w+ing\b", re.I)),
        "past_continuous": ("Past Continuous", re.compile(r"\b(was|were)\s+\w+ing\b", re.I)),
        "questions": ("Questions", re.compile(r"\?$")),
        "negatives": ("Negatives", re.compile(r"\b(not|n't|never|no)\b", re.I)),
    }
    found: dict[str, dict[str, Any]] = {}
    for sentence in sentences:
        for code, (name, regex) in rules.items():
            if regex.search(sentence):
                found.setdefault(code, {"code": code, "name": name, "count": 0, "example": sentence})
                found[code]["count"] += 1
    return list(found.values())


def detect_phrases(conn, doc, language: str = "en") -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    dictionary = phrase_dictionary(conn, language)
    translations = {
        (row["base_form"], row["type"]): row["translation_ru"]
        for row in dictionary
    }

    def add_hit(start: int, end: int, phrase: str, base_form: str, phrase_type: str, translation: str) -> None:
        if start >= end:
            return
        key = (start, end, base_form)
        if key in seen:
            return
        seen.add(key)
        hits.append(
            {
                "phrase": phrase,
                "base_form": base_form,
                "type": phrase_type,
                "translation_ru": translation,
                "start": start,
                "end": end,
            }
        )

    dictionary_matcher = PhraseMatcher(NLP.vocab, attr="LOWER")
    fixed_rows = [row for row in dictionary if row["type"] != "phrasal_verb"]
    if fixed_rows:
        dictionary_matcher.add(
            "DICTIONARY_PHRASE",
            [NLP.make_doc(row["base_form"]) for row in fixed_rows],
        )
        fixed_by_text = {row["base_form"]: row for row in fixed_rows}
        for _match_id, start, end in dictionary_matcher(doc):
            span = doc[start:end]
            base_form = span.text.lower()
            row = fixed_by_text.get(base_form)
            if row:
                add_hit(span.start_char, span.end_char, span.text, base_form, row["type"], row["translation_ru"])

    phrasal_translations = {
        tuple(base_form.split()): translation
        for (base_form, phrase_type), translation in translations.items()
        if phrase_type == "phrasal_verb" and len(base_form.split()) == 2
    }

    for token in doc:
        if not token.is_alpha or token.pos_ not in {"VERB", "AUX"}:
            continue
        verb = normalize_lemma(token)
        particles = [
            child for child in token.children
            if child.dep_ == "prt" and (verb, child.text.lower()) in phrasal_translations
        ]
        for particle in particles:
            start_token = min(token, particle, key=lambda item: item.i)
            end_token = max(token, particle, key=lambda item: item.i)
            if end_token.i - start_token.i > 5:
                continue
            span = doc[start_token.i:end_token.i + 1]
            base_form = f"{verb} {particle.text.lower()}"
            add_hit(span.start_char, span.end_char, span.text, base_form, "phrasal_verb", phrasal_translations[tuple(base_form.split())])

    tokens = [token for token in doc if token.is_alpha]
    for left, right in zip(tokens, tokens[1:]):
        key = (normalize_lemma(left), right.text.lower())
        if key in phrasal_translations:
            add_hit(
                left.idx,
                right.idx + len(right.text),
                f"{left.text} {right.text}",
                f"{key[0]} {key[1]}",
                "phrasal_verb",
                phrasal_translations[key],
            )

    hits.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    filtered: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for hit in hits:
        if any(not (hit["end"] <= start or hit["start"] >= end) for start, end in occupied):
            continue
        filtered.append(hit)
        occupied.append((hit["start"], hit["end"]))
    return filtered


def ensure_word(
    conn,
    user_id: str,
    language: str,
    lemma: str,
    pos: str,
    known_seeds: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    word = query_one(conn, "select * from words where language=%s and lemma=%s", (language, lemma))
    if not word:
        word_id = token_id("w")
        lexical_value = resolve_lexical_translation(conn, lemma)
        transcription = word_transcription(lemma) if language == "en" else ""
        query_one(
            conn,
            """
            insert into words (id, language, lemma, part_of_speech, translation_ru, transcription, frequency_rank)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (word_id, language, lemma, pos, lexical_value, transcription, rank_for(lemma)),
        )
        word = query_one(conn, "select * from words where id=%s", (word_id,))
    elif word["translation_ru"] == "перевод уточняется":
        lexical_value = resolve_lexical_translation(conn, lemma, fallback="")
        if not lexical_value and USE_WORDNET_FALLBACK:
            lexical_value = wordnet_definition(conn, lemma, word.get("part_of_speech") or pos) or ""
        if lexical_value:
            word = query_one(conn, "update words set translation_ru=%s where id=%s returning *", (lexical_value, word["id"]))
    if language == "en" and not (word.get("transcription") or "").strip():
        transcription = word_transcription(lemma)
        if transcription:
            word = query_one(conn, "update words set transcription=%s where id=%s returning *", (transcription, word["id"]))
    knowledge = query_one(conn, "select * from user_words where user_id=%s and word_id=%s", (user_id, word["id"]))
    if not knowledge:
        seed_terms = known_seeds if known_seeds is not None else known_seed_terms(conn)
        status = "known" if lemma in seed_terms else "unknown"
        knowledge_id = token_id("uw")
        knowledge = query_one(
            conn,
            """
            insert into user_words (id, user_id, word_id, status, confidence, last_seen_at)
            values (%s, %s, %s, %s, %s, now())
            returning *
            """,
            (knowledge_id, user_id, word["id"], status, confidence_for(status)),
        )
    return word, knowledge


def ensure_phrase(conn, user_id: str, language: str, hit: dict[str, Any]) -> dict[str, Any]:
    phrase = query_one(conn, "select * from phrases where language=%s and base_form=%s", (language, hit["base_form"]))
    if not phrase:
        phrase_id = token_id("p")
        phrase = query_one(
            conn,
            """
            insert into phrases (id, language, phrase, base_form, type, translation_ru)
            values (%s, %s, %s, %s, %s, %s)
            returning *
            """,
            (phrase_id, language, hit["phrase"], hit["base_form"], hit["type"], hit["translation_ru"]),
        )
    elif (
        not has_resolved_translation(phrase.get("translation_ru"))
        and has_resolved_translation(hit.get("translation_ru"))
    ):
        phrase = query_one(
            conn,
            "update phrases set translation_ru=%s where id=%s returning *",
            (hit["translation_ru"], phrase["id"]),
        )
    knowledge = query_one(conn, "select * from user_phrases where user_id=%s and phrase_id=%s", (user_id, phrase["id"]))
    if not knowledge:
        knowledge = query_one(
            conn,
            "insert into user_phrases (id, user_id, phrase_id, status, confidence) values (%s, %s, %s, 'unknown', 0.1) returning *",
            (token_id("up"), user_id, phrase["id"]),
        )
    return {**hit, "phrase_id": phrase["id"], "user_phrase_id": knowledge["id"], "status": knowledge["status"]}


def analyze_document(conn, user: dict[str, Any], document: dict[str, Any], refresh_important: bool = False, preserve_ids: list[str] | None = None) -> dict[str, Any]:
    clean = clean_text(document["raw_text"], document["type"])
    doc = NLP(clean, disable=["ner"])
    phrase_hits = [ensure_phrase(conn, user["id"], document["language"], hit) for hit in detect_phrases(conn, doc, document["language"])]
    phrase_spans = sorted((int(hit["start"]), int(hit["end"])) for hit in phrase_hits)

    def token_inside_current_phrase(token, phrase_index: int) -> bool:
        if phrase_index >= len(phrase_spans):
            return False
        token_start = token.idx
        token_end = token.idx + len(token.text)
        span_start, span_end = phrase_spans[phrase_index]
        return token_start < span_end and token_end > span_start

    token_rows = []
    phrase_index = 0
    for token in doc:
        if not token.is_alpha:
            continue
        if re.search(r"\d$", clean[max(0, token.idx - 1):token.idx]):
            continue
        while phrase_index < len(phrase_spans) and phrase_spans[phrase_index][1] <= token.idx:
            phrase_index += 1
        if token_inside_current_phrase(token, phrase_index):
            continue
        token_rows.append(token)

    counts: dict[str, int] = {}
    forms: dict[str, dict[str, int]] = {}
    examples: dict[str, str] = {}
    pos: dict[str, str] = {}
    known_seeds = known_seed_terms(conn)
    short_known_tokens = 0

    for token in token_rows:
        lemma = normalize_lemma(token)
        if is_short_word(lemma):
            short_known_tokens += 1
            continue
        counts[lemma] = counts.get(lemma, 0) + 1
        forms.setdefault(lemma, {})
        forms[lemma][token.text.lower()] = forms[lemma].get(token.text.lower(), 0) + 1
        examples.setdefault(lemma, token.sent.text.strip() if token.sent else "")
        pos.setdefault(lemma, token.pos_.lower() or "word")

    word_stats = []
    for lemma, count in counts.items():
        word, knowledge = ensure_word(
            conn,
            user["id"],
            document["language"],
            lemma,
            pos.get(lemma, "word"),
            known_seeds=known_seeds,
        )
        status = knowledge["status"]
        word_stats.append(
            {
                "word_id": word["id"],
                "user_word_id": knowledge["id"],
                "lemma": lemma,
                "part_of_speech": word["part_of_speech"],
                "translation_ru": word["translation_ru"],
                "transcription": word.get("transcription", ""),
                "frequency_rank": word["frequency_rank"],
                "count": count,
                "forms": [{"form": form, "count": value} for form, value in forms[lemma].items()],
                "example": examples.get(lemma, ""),
                "status": status,
                "priority": priority_for(count, word["frequency_rank"], status, lemma),
            }
        )
    word_stats.sort(key=lambda item: (-item["priority"], -item["count"], item["lemma"]))

    known = {"known", "ignored"}
    total_words = len(token_rows)
    known_tokens = short_known_tokens + sum(word["count"] for word in word_stats if word["status"] in known)
    known_unique = sum(1 for word in word_stats if word["status"] in known)
    unique_words = len(word_stats)
    learning_candidates = [word for word in word_stats if word["status"] not in {"known", "ignored"}]
    all_candidates = [word for word in word_stats if word["status"] != "ignored"]
    if preserve_ids is not None:
        important_words = [word for word_id in preserve_ids for word in word_stats if word["word_id"] == word_id]
    else:
        important_words = (learning_candidates if refresh_important else all_candidates)[:25]
    projected = min(98, round(((known_tokens + sum(word["count"] for word in learning_candidates[:25])) / max(total_words, 1)) * 100))
    payload = {
        "id": token_id("ta"),
        "document_id": document["id"],
        "user_id": user["id"],
        "total_words": total_words,
        "unique_words": unique_words,
        "known_words": known_unique,
        "unknown_words": sum(1 for word in word_stats if word["status"] not in known),
        "ignored_words": sum(1 for word in word_stats if word["status"] == "ignored"),
        "coverage_percent": round((known_tokens / total_words) * 100) if total_words else 0,
        "unique_coverage_percent": round((known_unique / unique_words) * 100) if unique_words else 0,
        "projected_coverage_percent": projected,
        "important_words": important_words,
        "learning_words": learning_candidates[:25],
        "words": word_stats,
        "phrases": phrase_hits,
        "created_at": now(),
    }
    with conn.cursor() as cur:
        cur.execute("update documents set clean_text=%s where id=%s", (clean, document["id"]))
        cur.execute(
            """
            insert into analyses (id, document_id, user_id, total_words, unique_words, known_words, unknown_words, ignored_words,
                                  coverage_percent, unique_coverage_percent, projected_coverage_percent, payload)
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
                document["id"],
                user["id"],
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
    return payload


def get_analysis(conn, document_id: str) -> dict[str, Any] | None:
    row = query_one(conn, "select payload from analyses where document_id=%s", (document_id,))
    return row["payload"] if row else None


def get_user_analysis(conn, user_id: str, document_id: str) -> dict[str, Any] | None:
    row = query_one(
        conn,
        "select payload from analyses where document_id=%s and user_id=%s",
        (document_id, user_id),
    )
    return row["payload"] if row else None


def refresh_analysis_payload(conn, user: dict[str, Any], payload: dict[str, Any], preserve_important: bool = True) -> dict[str, Any]:
    word_statuses = {
        row["word_id"]: row
        for row in query_all(conn, "select * from user_words where user_id=%s", (user["id"],))
    }
    word_rows = {
        row["id"]: row
        for row in query_all(conn, "select * from words")
    }
    phrase_statuses = {
        row["phrase_id"]: row
        for row in query_all(conn, "select * from user_phrases where user_id=%s", (user["id"],))
    }

    for word in payload.get("words", []):
        stored_word = word_rows.get(word.get("word_id"))
        if stored_word:
            word["part_of_speech"] = stored_word["part_of_speech"]
            word["translation_ru"] = stored_word["translation_ru"]
            word["transcription"] = stored_word.get("transcription", "")
            word["frequency_rank"] = stored_word["frequency_rank"]
        knowledge = word_statuses.get(word.get("word_id"))
        if knowledge:
            word["user_word_id"] = knowledge["id"]
            word["status"] = knowledge["status"]

    for phrase in payload.get("phrases", []):
        knowledge = phrase_statuses.get(phrase.get("phrase_id"))
        if knowledge:
            phrase["user_phrase_id"] = knowledge["id"]
            phrase["status"] = knowledge["status"]

    words = [word for word in payload.get("words", []) if not is_short_word(word.get("lemma"))]
    payload["words"] = words
    words_by_id = {word.get("word_id"): word for word in words}
    known = {"known", "ignored"}
    total_words = int(payload.get("total_words") or sum(int(word.get("count", 0)) for word in words))
    unique_words = len(words)
    known_tokens = sum(int(word.get("count", 0)) for word in words if word.get("status") in known)
    known_unique = sum(1 for word in words if word.get("status") in known)
    ignored_words = sum(1 for word in words if word.get("status") == "ignored")
    unknown_words = sum(1 for word in words if word.get("status") not in known)
    learning_candidates = [word for word in words if word.get("status") not in {"known", "ignored"}]
    learning_candidates.sort(key=lambda item: (-float(item.get("priority", 0)), -int(item.get("count", 0)), item.get("lemma", "")))

    if preserve_important:
        important_words = [
            words_by_id[word.get("word_id")]
            for word in payload.get("important_words", [])
            if word.get("word_id") in words_by_id
        ]
    else:
        important_words = learning_candidates[:25]

    projected = min(98, round(((known_tokens + sum(int(word.get("count", 0)) for word in learning_candidates[:25])) / max(total_words, 1)) * 100))
    payload.update(
        {
            "known_words": known_unique,
            "unknown_words": unknown_words,
            "ignored_words": ignored_words,
            "coverage_percent": round((known_tokens / total_words) * 100) if total_words else 0,
            "unique_coverage_percent": round((known_unique / unique_words) * 100) if unique_words else 0,
            "projected_coverage_percent": projected,
            "important_words": important_words,
            "learning_words": learning_candidates[:25],
            "created_at": now(),
        }
    )
    return payload


def save_analysis_payload(conn, payload: dict[str, Any]) -> None:
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


def make_phrase_hit(base_form: str, phrase_type: str, translation: str) -> dict[str, Any]:
    return {
        "start": 0,
        "end": len(base_form),
        "phrase": base_form,
        "base_form": base_form,
        "type": phrase_type,
        "translation_ru": translation,
    }


def context_unit_status(units: list[dict[str, Any]]) -> dict[str, int]:
    known = sum(1 for item in units if item.get("status") in {"known", "ignored"})
    unknown = sum(1 for item in units if item.get("status") not in {"known", "ignored"})
    return {
        "known_count": known,
        "unknown_count": unknown,
        "coverage_percent": round((known / max(len(units), 1)) * 100) if units else 0,
    }


def unit_score(unit: dict[str, Any]) -> float:
    try:
        priority = float(unit.get("score") or 0)
    except (TypeError, ValueError):
        priority = 0
    try:
        count = float(unit.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    return priority + count * 12


def context_payload(
    context_id: str,
    title: str,
    description: str,
    category: str,
    difficulty: str,
    units: list[dict[str, Any]],
    document_id: str | None = None,
    bridges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stats = context_unit_status(units)
    recommended = sorted(
        [unit for unit in units if unit.get("status") not in {"known", "ignored"}],
        key=lambda item: -unit_score(item),
    )
    return {
        "id": context_id,
        "title": title,
        "description": description,
        "category": category,
        "difficulty": difficulty,
        **stats,
        "phrases_count": len([unit for unit in units if unit.get("kind") == "phrase"]),
        "units": units,
        "recommended_words": [unit for unit in recommended if unit.get("kind") == "word"][:10],
        "recommended_phrases": [unit for unit in recommended if unit.get("kind") == "phrase"][:3],
        "reviews": sorted([unit for unit in units if unit.get("status") == "learning"], key=lambda item: item.get("text", ""))[:5],
        "groups": group_units_for_graph(units),
        "bridges": bridges or [],
        "document_id": document_id,
    }


def topic_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:48] or token_id("topic")


def topic_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:1].upper() + text[1:] if text else "Topic"


def document_units_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    seen_words: set[str] = set()
    words = sorted(
        [word for word in payload.get("words", []) if word.get("status") != "ignored"],
        key=lambda item: (-int(item.get("count") or 0), -float(item.get("priority") or 0), item.get("lemma", "")),
    )
    for word in words:
        lemma = word.get("lemma")
        if not lemma or is_short_word(lemma) or lemma in seen_words:
            continue
        seen_words.add(lemma)
        units.append({
            "id": word["word_id"],
            "knowledge_id": word["user_word_id"],
            "kind": "word",
            "text": lemma,
            "translation_ru": word.get("translation_ru", ""),
            "transcription": word.get("transcription", ""),
            "part_of_speech": word.get("part_of_speech", "word"),
            "status": word.get("status", "unknown"),
            "example": word.get("example", ""),
            "relation": pos_to_relation(word.get("part_of_speech", "")),
            "score": word.get("priority", 0),
            "count": int(word.get("count") or 1),
            "frequency_rank": word.get("frequency_rank", 999999),
        })

    seen_phrases: set[str] = set()
    for phrase in payload.get("phrases", []):
        phrase_key = phrase.get("phrase_id") or phrase.get("base_form") or phrase.get("phrase")
        if not phrase_key or phrase.get("status") == "ignored" or phrase_key in seen_phrases:
            continue
        seen_phrases.add(phrase_key)
        units.append({
            "id": phrase["phrase_id"],
            "knowledge_id": phrase["user_phrase_id"],
            "kind": "phrase",
            "text": phrase.get("base_form") or phrase.get("phrase"),
            "base_form": phrase.get("base_form") or phrase.get("phrase"),
            "translation_ru": phrase.get("translation_ru", ""),
            "status": phrase.get("status", "unknown"),
            "example": "",
            "relation": "phrase",
            "score": 70,
            "count": 1,
        })
    return units


def kg_wordfreq(value: str) -> float:
    if zipf_frequency is None:
        return 4.0
    return float(zipf_frequency(value, "en"))


def kg_frequency_to_score(zipf: float) -> float:
    if zipf < KG_MIN_ZIPF:
        return 0.0
    if zipf > KG_MAX_ZIPF:
        return max(0.0, 1.0 - (zipf - KG_MAX_ZIPF) * 0.25)
    return (zipf - KG_MIN_ZIPF) / (KG_MAX_ZIPF - KG_MIN_ZIPF)


def kg_normalize_phrase(value: str) -> str:
    value = re.sub(r"[^A-Za-z\s'-]", " ", (value or "").lower())
    return re.sub(r"\s+", " ", value).strip()


def kg_is_candidate_text(word: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z'-]{2,}", word.lower())) and "'" not in word and "-" not in word


@lru_cache(maxsize=1)
def kg_candidate_pool() -> tuple[dict[str, Any], ...]:
    if top_n_list is None or np is None:
        return tuple()
    words = top_n_list("en", KG_MAX_FREQUENCY_WORDS)
    filtered = [
        word.lower()
        for word in words
        if kg_is_candidate_text(word) and KG_MIN_ZIPF <= kg_wordfreq(word) <= KG_MAX_ZIPF
    ]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in NLP.pipe(filtered, batch_size=512):
        if not doc or len(doc) != 1:
            continue
        token = doc[0]
        lemma = normalize_lemma(token)
        if (
            token.is_stop
            or token.pos_ not in {"NOUN", "VERB", "ADJ", "ADV"}
            or not lemma
            or lemma in seen
            or not token.has_vector
            or token.vector_norm == 0
        ):
            continue
        seen.add(lemma)
        candidates.append({
            "word": lemma,
            "pos": token.pos_.lower(),
            "frequency": kg_wordfreq(lemma),
            "vector": token.vector.copy(),
            "vector_norm": float(token.vector_norm),
            "ent_type": token.ent_type_,
        })
        if len(candidates) >= KG_MAX_CANDIDATES:
            break
    return tuple(candidates)


def kg_title_topic(topic: str) -> str:
    small = {"and", "at", "in", "of", "the", "to", "for"}
    return " ".join(part if part in small else part.capitalize() for part in kg_normalize_phrase(topic).split()) or "Everyday English"


def kg_infer_topic_label(raw_input: str) -> str:
    doc = NLP((raw_input or "everyday English")[:100_000])
    chunks = [kg_normalize_phrase(" ".join(normalize_lemma(token) for token in chunk if token.is_alpha and not token.is_stop)) for chunk in doc.noun_chunks]
    chunks = [chunk for chunk in chunks if len(chunk) >= 3]
    if chunks:
        return chunks[0]
    keywords = [
        normalize_lemma(token)
        for token in doc
        if token.is_alpha and not token.is_stop and token.pos_ in {"NOUN", "PROPN", "VERB", "ADJ"}
    ]
    return " ".join(dict.fromkeys(keywords).keys())[:80] or "everyday English"


def kg_rank_related_words(
    raw_input: str,
    excluded_words: set[str] | None = None,
    blocked_single_words: set[str] | None = None,
    blocked_entity_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = {str(word).strip().lower() for word in (excluded_words or set())}
    blocked_single_words = {str(word).strip().lower() for word in (blocked_single_words or set())}
    blocked_entity_labels = {str(label).strip().upper() for label in (blocked_entity_labels or set())}
    doc = NLP((raw_input or "everyday English")[:100_000])
    input_lemmas = {
        normalize_lemma(token)
        for token in doc
        if token.is_alpha and not token.is_stop and token.pos_ in {"NOUN", "PROPN", "VERB", "ADJ", "ADV"}
    }
    if np is None:
        return [
            {"word": lemma, "pos": "noun", "score": 1.0, "frequency": kg_wordfreq(lemma), "semantic": 1.0, "usefulness": 1.0}
            for lemma in sorted(input_lemmas - excluded)[:25]
        ]

    topic_vector = doc.vector
    topic_norm = float(np.linalg.norm(topic_vector))
    if topic_norm == 0:
        vectors = [candidate["vector"] for candidate in kg_candidate_pool() if candidate["word"] in input_lemmas]
        topic_vector = np.mean(vectors, axis=0) if vectors else np.zeros((NLP.vocab.vectors_length,), dtype="float32")
        topic_norm = float(np.linalg.norm(topic_vector))

    ranked: list[dict[str, Any]] = []
    for candidate in kg_candidate_pool():
        word = candidate["word"]
        if word in excluded or word in blocked_single_words:
            continue
        if str(candidate.get("ent_type") or "").upper() in blocked_entity_labels:
            continue
        if word in input_lemmas:
            semantic = 1.0
        elif topic_norm > 0:
            semantic = float(np.dot(topic_vector, candidate["vector"]) / (topic_norm * candidate["vector_norm"]))
            semantic = max(0.0, min(1.0, semantic))
        else:
            semantic = 0.0
        if semantic < 0.24:
            continue
        frequency = float(candidate["frequency"])
        usefulness = (1.0 if 4 <= len(word) <= 10 else 0.72) * (1.0 if candidate["pos"] in {"noun", "verb"} else 0.86)
        rare_penalty = max(0.0, 3.15 - frequency) * 0.18
        too_common_penalty = max(0.0, frequency - 5.05) * 0.12
        score = semantic * 0.62 + kg_frequency_to_score(frequency) * 0.28 + usefulness * 0.10 - rare_penalty - too_common_penalty
        ranked.append({"word": word, "pos": candidate["pos"], "score": score, "frequency": frequency, "semantic": semantic, "usefulness": usefulness})

    if not ranked:
        return [
            {"word": lemma, "pos": "noun", "score": 1.0, "frequency": kg_wordfreq(lemma), "semantic": 1.0, "usefulness": 1.0}
            for lemma in sorted(input_lemmas - excluded)[:25]
        ]

    best: dict[str, dict[str, Any]] = {}
    for item in ranked:
        current = best.get(item["word"])
        if not current or item["score"] > current["score"]:
            best[item["word"]] = item
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)


def kg_build_collocations(raw_input: str, ranked: list[dict[str, Any]]) -> list[str]:
    ranked_words = {item["word"] for item in ranked[:40]}
    doc = NLP((raw_input or "")[:100_000])
    phrases: list[str] = []
    for chunk in doc.noun_chunks:
        phrase = kg_normalize_phrase(" ".join(normalize_lemma(token) for token in chunk if token.is_alpha and not token.is_stop))
        parts = phrase.split()
        if 2 <= len(parts) <= 4 and any(part in ranked_words for part in parts) and kg_wordfreq(phrase) >= 3.1:
            phrases.append(phrase)
    for token in doc:
        head = token.head
        if token.dep_ in {"amod", "compound"} and head.pos_ in {"NOUN", "PROPN"}:
            phrase = kg_normalize_phrase(f"{normalize_lemma(token)} {normalize_lemma(head)}")
            if kg_wordfreq(phrase) >= 3.1:
                phrases.append(phrase)
        if token.dep_ in {"dobj", "obj", "pobj"} and head.pos_ == "VERB":
            phrase = kg_normalize_phrase(f"{normalize_lemma(head)} {normalize_lemma(token)}")
            if kg_wordfreq(phrase) >= 3.1:
                phrases.append(phrase)
    result = []
    seen = set()
    for phrase in phrases:
        if phrase and phrase not in seen:
            seen.add(phrase)
            result.append(phrase)
    return result[:8]


def kg_build_phrasal_verbs(conn, ranked: list[dict[str, Any]], language: str = "en") -> list[str]:
    ranked_scores = {item["word"]: float(item.get("score") or 0) for item in ranked}
    candidates = []
    for row in phrase_dictionary(conn, language):
        if row["type"] != "phrasal_verb":
            continue
        parts = row["base_form"].split()
        if not parts:
            continue
        score = ranked_scores.get(parts[0], 0.0) + kg_wordfreq(row["base_form"]) * 0.01
        if score > 0:
            candidates.append((score, row["base_form"]))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [phrase for _score, phrase in candidates[:8]]


def kg_build_bridge_topics(topic: str, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topic_terms = set(kg_normalize_phrase(topic).split())
    seeds = [
        item
        for item in ranked[:36]
        if item["word"] not in topic_terms and item["pos"] in {"noun", "verb", "adj"}
    ]
    bridges = []
    used = set()
    for index, seed in enumerate(seeds[:12]):
        title = kg_title_topic(f"{seed['word']} situations" if seed["pos"] != "adj" else f"{seed['word']} context")
        key = title.lower()
        if key in used:
            continue
        used.add(key)
        bridges.append({
            "bridge_topic": title,
            "reason": "",
            "starter_words": [],
        })
        if len(bridges) >= 6:
            break
    return bridges


def kg_unit_from_word(conn, user: dict[str, Any], item: dict[str, Any], example: str = "") -> dict[str, Any]:
    word, knowledge = ensure_word(conn, user["id"], user.get("target_language") or "en", item["word"], item.get("pos") or "word")
    return {
        "id": word["id"],
        "knowledge_id": knowledge["id"],
        "kind": "word",
        "text": word["lemma"],
        "translation_ru": word["translation_ru"],
        "transcription": word.get("transcription", ""),
        "part_of_speech": word["part_of_speech"],
        "status": knowledge["status"],
        "confidence": knowledge["confidence"],
        "example": example,
        "relation": pos_to_relation(word["part_of_speech"]),
        "score": round(float(item.get("score") or 0) * 100, 2),
        "count": 1,
        "frequency_rank": word["frequency_rank"],
    }


def kg_unit_from_phrase(conn, user: dict[str, Any], phrase: str, phrase_type: str, score: float, example: str = "") -> dict[str, Any] | None:
    text = kg_normalize_phrase(phrase)
    if not text or len(text.split()) < 2:
        return None
    translation = (
        phrase_dictionary_translation(
            conn,
            text,
            phrase_type=phrase_type,
            language=user.get("target_language") or "en",
        )
        or resolve_lexical_translation(conn, text, fallback="перевод уточняется")
    )
    phrase_row = ensure_phrase(conn, user["id"], user.get("target_language") or "en", make_phrase_hit(text, phrase_type, translation))
    return {
        "id": phrase_row["phrase_id"],
        "knowledge_id": phrase_row["user_phrase_id"],
        "kind": "phrase",
        "text": text,
        "base_form": text,
        "translation_ru": phrase_row["translation_ru"],
        "status": phrase_row["status"],
        "confidence": 0,
        "example": example,
        "relation": "phrase",
        "score": score,
        "count": 1,
    }


def example_for_word_prefix(text: str, word: str, limit: int = 180) -> str:
    source = str(text or "")
    token = re.escape(str(word or "").strip().lower())
    if not source or not token:
        return ""
    match = re.search(rf"\b{token}[a-z']*\b", source, flags=re.I)
    if not match:
        return ""
    left = max(
        source.rfind(".", 0, match.start()),
        source.rfind("!", 0, match.start()),
        source.rfind("?", 0, match.start()),
        source.rfind("\n", 0, match.start()),
    )
    right_candidates = [
        index for index in (
            source.find(".", match.end()),
            source.find("!", match.end()),
            source.find("?", match.end()),
            source.find("\n", match.end()),
        )
        if index >= 0
    ]
    start = left + 1 if left >= 0 else 0
    end = min(right_candidates) + 1 if right_candidates else len(source)
    return re.sub(r"\s+", " ", source[start:end]).strip()[:limit]


def build_kg_context(
    conn,
    user: dict[str, Any],
    context_id: str,
    raw_input: str,
    title: str | None = None,
    description: str = "",
    document_id: str | None = None,
) -> dict[str, Any]:
    topic = kg_title_topic(title or kg_infer_topic_label(raw_input))
    known_terms = {
        row["lemma"]
        for row in query_all(
            conn,
            "select w.lemma from user_words uw join words w on w.id=uw.word_id where uw.user_id=%s and uw.status in ('known', 'ignored')",
            (user["id"],),
        )
    }
    known_terms.update({
        row["base_form"]
        for row in query_all(
            conn,
            "select p.base_form from user_phrases up join phrases p on p.id=up.phrase_id where up.user_id=%s and up.status in ('known', 'ignored')",
            (user["id"],),
        )
    })
    ranked = kg_rank_related_words(
        raw_input or topic,
        excluded_words=known_terms,
        blocked_single_words=system_terms(conn, "kg_blocked_single_word"),
        blocked_entity_labels=system_terms(conn, "kg_blocked_entity_label"),
    )
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked:
        if item["word"] in seen:
            continue
        seen.add(item["word"])
        unit = kg_unit_from_word(conn, user, item, example=example_for_word_prefix(raw_input, item["word"]))
        if unit["status"] not in {"known", "ignored"} and unit["text"] not in known_terms:
            units.append(unit)
        if len([unit for unit in units if unit["kind"] == "word"]) >= 25:
            break

    for phrase in kg_build_collocations(raw_input, ranked)[:5]:
        if kg_normalize_phrase(phrase) in known_terms:
            continue
        unit = kg_unit_from_phrase(conn, user, phrase, "collocation", 82, example=raw_input[:180])
        if unit and unit["status"] not in {"known", "ignored"}:
            units.append(unit)
    for phrase in kg_build_phrasal_verbs(conn, ranked, user.get("target_language") or "en")[:4]:
        if kg_normalize_phrase(phrase) in known_terms:
            continue
        unit = kg_unit_from_phrase(conn, user, phrase, "phrasal_verb", 76)
        if unit and unit["status"] not in {"known", "ignored"}:
            units.append(unit)

    bridges = []
    for bridge in kg_build_bridge_topics(topic, ranked):
        bridge_id = f"{context_id}:bridge:{topic_slug(bridge['bridge_topic'])}"
        bridges.append({
            "id": bridge_id,
            "title": bridge["bridge_topic"],
            "description": bridge["reason"],
            "category": "Мост",
            "difficulty": "по смыслу",
            "known_count": 0,
            "unknown_count": 0,
            "coverage_percent": 0,
            "phrases_count": 0,
            "document_id": document_id,
            "shared": [],
        })

    return context_payload(
        context_id,
        topic,
        description or "Слова подобраны через semantic relatedness, частотность и вашу базу знаний.",
        "Knowledge Graph",
        "semantic + frequency",
        units[:30],
        document_id=document_id,
        bridges=bridges,
    )


def kg_bridge_context(conn, user: dict[str, Any], context_id: str, bridge_title: str, seed_words: list[str], document_id: str | None = None) -> dict[str, Any]:
    seed = " ".join([bridge_title, *seed_words])
    return build_kg_context(
        conn,
        user,
        context_id,
        seed,
        title=bridge_title,
        description=f"Мостовая тема: {bridge_title}.",
        document_id=document_id,
    )


def document_context_id_from_kg_id(context_id: str | None) -> str | None:
    if not context_id or not context_id.startswith("document:"):
        return None
    rest = context_id.removeprefix("document:")
    return re.split(r":(?:topic|bridge|kg):", rest, maxsplit=1)[0] or None


def build_document_context_from_row(conn, user: dict[str, Any], row: dict[str, Any] | None, description: str) -> dict[str, Any] | None:
    if not row:
        return None
    row_id = str(row["id"])
    source_text = row.get("clean_text") or row.get("raw_text") or ""
    return build_kg_context(
        conn,
        user,
        f"document:{row_id}",
        source_text,
        title=kg_infer_topic_label(source_text) or row["title"],
        description=description,
        document_id=row_id,
    )


def pos_to_relation(pos: str) -> str:
    value = (pos or "").lower()
    if value in {"verb", "aux"}:
        return "action"
    if value in {"propn", "noun"}:
        return "object"
    if value in {"adj", "adv"}:
        return "problem"
    return "object"


def group_units_for_graph(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"place": [], "person": [], "action": [], "object": [], "phrase": [], "problem": []}
    for unit in units:
        groups.setdefault(unit.get("relation", "object"), groups["object"]).append(unit)
    return groups


def context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": context["id"],
        "title": context["title"],
        "description": context["description"],
        "category": context["category"],
        "difficulty": context["difficulty"],
        "known_count": context["known_count"],
        "unknown_count": context["unknown_count"],
        "coverage_percent": context["coverage_percent"],
        "phrases_count": len([unit for unit in context.get("units", []) if unit.get("kind") == "phrase"]),
        "document_id": context.get("document_id"),
    }


def learn_unit_key(unit: dict[str, Any]) -> str:
    kind = "phrase" if unit.get("kind") == "phrase" else "word"
    identity = unit.get("knowledge_id") or unit.get("id") or unit.get("text") or unit.get("label")
    return f"{kind}:{identity}"


def learn_frequency_rank(unit: dict[str, Any]) -> int:
    try:
        return int(unit.get("frequency_rank") or 999999)
    except (TypeError, ValueError):
        return 999999


def normalize_learn_unit(raw: dict[str, Any]) -> dict[str, Any] | None:
    kind = "phrase" if raw.get("kind") == "phrase" else "word"
    text = re.sub(r"\s+", " ", str(raw.get("text") or raw.get("label") or raw.get("base_form") or "").strip())
    knowledge_id = str(raw.get("knowledge_id") or raw.get("user_phrase_id") or raw.get("user_word_id") or "").strip()
    if not text or not knowledge_id:
        return None
    status = str(raw.get("status") or "unknown")
    try:
        count = int(raw.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    try:
        score = float(raw.get("score") or raw.get("priority") or 0)
    except (TypeError, ValueError):
        score = 0
    return {
        "id": str(raw.get("id") or raw.get("word_id") or raw.get("phrase_id") or knowledge_id),
        "knowledge_id": knowledge_id,
        "kind": kind,
        "text": text[:120],
        "base_form": str(raw.get("base_form") or text)[:120] if kind == "phrase" else "",
        "translation_ru": str(raw.get("translation_ru") or "")[:500],
        "transcription": str(raw.get("transcription") or "")[:120],
        "part_of_speech": str(raw.get("part_of_speech") or ("phrase" if kind == "phrase" else "word"))[:40],
        "status": status,
        "example": str(raw.get("example") or "")[:500],
        "count": count,
        "frequency_rank": learn_frequency_rank(raw),
        "score": score,
    }


def normalize_learn_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for raw in units:
        unit = normalize_learn_unit(raw or {})
        if not unit:
            continue
        key = learn_unit_key(unit)
        stored = by_key.get(key)
        if not stored:
            by_key[key] = unit
            continue
        stored["count"] = max(int(stored.get("count") or 1), int(unit.get("count") or 1))
        stored["score"] = max(float(stored.get("score") or 0), float(unit.get("score") or 0))
        stored["frequency_rank"] = min(learn_frequency_rank(stored), learn_frequency_rank(unit))
    return sorted(by_key.values(), key=lambda item: (learn_frequency_rank(item), item["text"].lower()))


def refresh_learn_units_from_knowledge(conn, user: dict[str, Any], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    word_rows = {
        row["id"]: row
        for row in query_all(
            conn,
            """
            select uw.id, uw.status, uw.confidence, w.id as word_id, w.lemma, w.translation_ru,
                   w.transcription, w.part_of_speech, w.frequency_rank
            from user_words uw
            join words w on w.id=uw.word_id
            where uw.user_id=%s
            """,
            (user["id"],),
        )
    }
    phrase_rows = {
        row["id"]: row
        for row in query_all(
            conn,
            """
            select up.id, up.status, up.confidence, p.id as phrase_id, p.base_form,
                   p.phrase, p.translation_ru, p.type
            from user_phrases up
            join phrases p on p.id=up.phrase_id
            where up.user_id=%s
            """,
            (user["id"],),
        )
    }
    refreshed = []
    for unit in units:
        item = dict(unit)
        knowledge_id = item.get("knowledge_id")
        if item.get("kind") == "phrase":
            row = phrase_rows.get(knowledge_id)
            if row:
                item.update(
                    {
                        "id": row["phrase_id"],
                        "text": row["base_form"] or row["phrase"],
                        "base_form": row["base_form"] or row["phrase"],
                        "translation_ru": row["translation_ru"],
                        "part_of_speech": row["type"] or "phrase",
                        "status": row["status"],
                    }
                )
        else:
            row = word_rows.get(knowledge_id)
            if row:
                item.update(
                    {
                        "id": row["word_id"],
                        "text": row["lemma"],
                        "translation_ru": row["translation_ru"],
                        "transcription": row.get("transcription", ""),
                        "part_of_speech": row["part_of_speech"],
                        "frequency_rank": row["frequency_rank"],
                        "status": row["status"],
                    }
                )
        refreshed.append(item)
    return refreshed


def public_learn_block(conn, user: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    units = normalize_learn_units(refresh_learn_units_from_knowledge(conn, user, payload.get("units") or []))
    frequency_filter = row.get("frequency_filter") or "all"
    if frequency_filter not in {"20-80", "50-50", "all"}:
        frequency_filter = "all"
    return {
        "id": row["id"],
        "title": row["title"],
        "frequency_filter": frequency_filter,
        "units": units,
        "created_at": str(row["created_at"]),
    }


def filter_learn_units_for_frequency(units: list[dict[str, Any]], frequency_filter: str) -> list[dict[str, Any]]:
    sorted_units = sorted(units, key=lambda item: (learn_frequency_rank(item), str(item.get("text") or "").lower()))
    if frequency_filter == "all" or not sorted_units:
        return sorted_units
    if frequency_filter == "20-80":
        return sorted_units[:max(1, int(len(sorted_units) * 0.2 + 0.999999))]
    if frequency_filter == "50-50":
        return sorted_units[:max(1, int(len(sorted_units) * 0.5 + 0.999999))]
    return sorted_units


def anki_bold_term(example: str, term: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(example or "")).strip()
    if not cleaned:
        return ""
    escaped = html.escape(cleaned)
    words = [re.escape(part) for part in re.sub(r"[^A-Za-z0-9'\s-]", " ", term or "").split() if part]
    if not words:
        return escaped
    pattern = r"\b" + r"\s+".join(words) + r"\b"
    return re.sub(pattern, lambda match: f"<b>{match.group(0)}</b>", escaped, flags=re.I)


def anki_filename(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title or "learn_block").strip("_")
    return (slug or "learn_block")[:80] + "_anki.txt"


def anki_example_translation(example: str) -> str:
    text = re.sub(r"\s+", " ", str(example or "")).strip()
    if not text:
        return ""
    key = text.lower()
    if key in _ANKI_EXAMPLE_TRANSLATION_CACHE:
        return _ANKI_EXAMPLE_TRANSLATION_CACHE[key] or ""
    try:
        with _GOOGLE_TRANSLATE_LOCK:
            translated = run_googletrans_translate(text)
        value = re.sub(r"\s+", " ", str(getattr(translated, "text", "") or "")).strip()
        if value and value.lower() != key:
            _ANKI_EXAMPLE_TRANSLATION_CACHE[key] = value[:1000]
            return _ANKI_EXAMPLE_TRANSLATION_CACHE[key] or ""
    except Exception:
        pass
    _ANKI_EXAMPLE_TRANSLATION_CACHE[key] = None
    return ""


def build_learn_block_anki_text(block: dict[str, Any]) -> str:
    units = [
        unit
        for unit in filter_learn_units_for_frequency(block.get("units") or [], block.get("frequency_filter") or "all")
        if unit.get("status") not in {"known", "ignored"}
    ]
    output = io.StringIO()
    output.write("#separator:tab\n")
    output.write("#html:true\n")
    output.write("#notetype:Basic\n")
    output.write(f"#deck:{html.escape(block.get('title') or 'Learn')}\n")
    output.write("#columns:Front\tBack\n")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")

    for unit in units:
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        translation = clean_export_translation(unit.get("translation_ru")) or "Перевод не найден"
        transcription = clean_transcription_for_export(unit.get("transcription"))
        example = anki_bold_term(unit.get("example") or "", text)
        word_line = f"<span style=\"font-size:22px;font-weight:700;\"><b>{html.escape(text)}</b></span>"
        details = []
        if transcription:
            details.append(f"<span style=\"font-size:15px;color:#667085;\">/{html.escape(transcription)}/</span>")
        if example:
            details.append(f"<span style=\"font-size:16px;color:#3b4b5c;\">{example}</span>")
        tts_parts = [f"{text}."]
        if unit.get("example"):
            tts_parts.append(re.sub(r"\s+", " ", str(unit.get("example"))).strip())
        tts_text = " <break time=\"1000ms\"/> ".join([html.escape(part) for part in tts_parts if part])
        tts_line = f"[anki:tts lang=en_US]{tts_text}[/anki:tts]" if tts_text else ""
        front = "<br>".join([part for part in [word_line, *details, tts_line] if part])
        back_parts = [html.escape(translation)]
        part_of_speech = str(unit.get("part_of_speech") or "").strip()
        if part_of_speech:
            back_parts.append(f"<span style=\"color:#667085;\">{html.escape(part_of_speech)}</span>")
        example_translation = anki_example_translation(unit.get("example") or "")
        if example_translation:
            back_parts.append(f"<span style=\"color:#3b4b5c;\">Пример: {html.escape(example_translation)}</span>")
        writer.writerow([front, "<br>".join(back_parts)])

    text = output.getvalue()
    output.close()
    return text


def clean_export_translation(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text == "перевод уточняется" else text


def clean_transcription_for_export(value: Any) -> str:
    return str(value or "").replace("*", "").strip()


def translate_goal_to_target_language(text: str, target_language: str) -> str:
    if not text or not re.search(r"[а-яёА-ЯЁ]", text) or GoogleTranslator is None:
        return text

    async def _translate():
        client = GoogleTranslator(service_urls=["translate.googleapis.com"])
        return await client.translate(text, src="auto", dest=target_language or "en")

    try:
        translated = run_coroutine_from_sync(_translate)
    except Exception:
        return text
    value = re.sub(r"\s+", " ", str(getattr(translated, "text", "") or "")).strip()
    return value or text


def user_corpus_units(conn, user: dict[str, Any]) -> list[dict[str, Any]]:
    rows = query_all(conn, "select payload from analyses where user_id=%s order by created_at desc", (user["id"],))
    units_by_text: dict[str, dict[str, Any]] = {}
    for row in rows:
        for unit in document_units_from_payload(row["payload"]):
            text = str(unit.get("text", "")).lower()
            if not text:
                continue
            stored = units_by_text.get(text)
            if not stored:
                units_by_text[text] = dict(unit)
                continue
            stored["count"] = int(stored.get("count") or 0) + int(unit.get("count") or 0)
            stored["score"] = max(float(stored.get("score") or 0), float(unit.get("score") or 0))
    return list(units_by_text.values())


def build_goal_context(conn, user: dict[str, Any], goal: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    original_text = re.sub(r"\s+", " ", (goal or "").strip()) or "Everyday English"
    target_text = translate_goal_to_target_language(original_text, user.get("target_language") or "en")
    title = original_text[:80]
    context = build_kg_context(
        conn,
        user,
        "goal",
        target_text,
        title=kg_infer_topic_label(target_text) or title,
        description=f"Контекст собран из цели: {target_text}.",
    )
    bridge_contexts = [
        kg_bridge_context(conn, user, bridge["id"], bridge["title"], bridge.get("shared", []))
        for bridge in context.get("bridges", [])[:5]
    ]
    return context, [context] + bridge_contexts


def document_summary(conn, doc: dict[str, Any]) -> dict[str, Any]:
    analysis = get_analysis(conn, doc["id"])
    return {
        "id": doc["id"],
        "title": doc["title"],
        "type": doc["type"],
        "language": doc["language"],
        "created_at": str(doc["created_at"]),
        "total_words": analysis.get("total_words", 0) if analysis else 0,
        "unique_words": analysis.get("unique_words", 0) if analysis else 0,
        "coverage_percent": analysis.get("coverage_percent", 0) if analysis else 0,
    }


def build_pieces(conn, user: dict[str, Any], doc_row: dict[str, Any]) -> dict[str, Any]:
    analysis = get_analysis(conn, doc_row["id"]) or analyze_document(conn, user, doc_row)
    # For legacy SRT documents, reclean from raw_text to guarantee timecodes are removed in Text view.
    source = clean_text(doc_row["raw_text"], doc_row["type"]) if doc_row.get("type") == "srt" else (doc_row["clean_text"] or clean_text(doc_row["raw_text"], doc_row["type"]))
    words_by_lemma = {word["lemma"]: word for word in analysis["words"]}
    words_by_form = {
        form["form"]: word
        for word in analysis["words"]
        for form in word.get("forms", [])
        if form.get("form")
    }
    phrases_by_start = {phrase["start"]: phrase for phrase in analysis["phrases"]}
    doc = NLP(source)
    tokens = [token for token in doc if token.is_alpha]
    pieces = []
    cursor = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        phrase = phrases_by_start.get(token.idx)
        if phrase:
            if phrase["start"] > cursor:
                pieces.append({"type": "text", "value": source[cursor:phrase["start"]]})
            pieces.append({**phrase, "type": "phrase", "phrase_type": phrase.get("type", "phrase"), "value": source[phrase["start"]:phrase["end"]]})
            cursor = phrase["end"]
            while i + 1 < len(tokens) and tokens[i + 1].idx + len(tokens[i + 1].text) <= phrase["end"]:
                i += 1
            i += 1
            continue
        if token.idx < cursor:
            i += 1
            continue
        if token.idx > cursor:
            pieces.append({"type": "text", "value": source[cursor:token.idx]})
        lemma = normalize_lemma(token)
        token_form = token.text.lower()
        word = words_by_lemma.get(lemma) or words_by_form.get(token_form)
        short_known = is_short_word(lemma)
        pieces.append(
            {
                "type": "word",
                "value": token.text,
                "lemma": word.get("lemma", lemma) if word else lemma,
                "status": "known" if short_known else word.get("status", "unknown") if word else "unknown",
                "word_id": word.get("word_id") if word else None,
                "translation_ru": word.get("translation_ru", "") if word else "",
                "transcription": word.get("transcription", "") if word else "",
            }
        )
        cursor = token.idx + len(token.text)
        i += 1
    if cursor < len(source):
        pieces.append({"type": "text", "value": source[cursor:]})
    return {**doc_row, "created_at": str(doc_row["created_at"]), "analysis": analysis, "pieces": pieces, "token_count": len(tokens)}


@router.post("/api/register")
def register(payload: AuthPayload, response: Response):
    with db() as conn:
        email = normalize_email(payload.email)
        if not is_valid_email(email):
            raise HTTPException(status_code=400, detail="Укажите корректный email.")
        if len(payload.password or "") < 4:
            raise HTTPException(status_code=400, detail="Пароль должен быть не короче 4 символов.")
        existing = query_one(conn, "select * from users where email=%s", (email,))
        if existing:
            raise HTTPException(status_code=409, detail="Пользователь уже существует.")
        if not EMAIL_VERIFICATION_ENABLED:
            user = query_one(
                conn,
                """
                insert into users
                    (id, email, password_hash, native_language, target_language, email_verified)
                values (%s, %s, %s, %s, %s, true)
                returning *
                """,
                (
                    token_id("u"),
                    email,
                    hash_password(payload.password),
                    payload.native_language or "ru",
                    payload.target_language or "en",
                ),
            )
            token = token_id("s")
            query_one(conn, "insert into sessions (token, user_id) values (%s, %s) returning token", (token, user["id"]))
            response.set_cookie("lp_session", token, httponly=True, samesite="lax")
            return {"user": public_user(user)}
        code = f"{secrets.randbelow(1_000_000):06d}"
        query_one(
            conn,
            """
            insert into email_verification_codes
                (email, password_hash, native_language, target_language, code_hash, expires_at)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (email) do update set
                password_hash=excluded.password_hash,
                native_language=excluded.native_language,
                target_language=excluded.target_language,
                code_hash=excluded.code_hash,
                attempts=0,
                expires_at=excluded.expires_at,
                created_at=now()
            returning email
            """,
            (
                email,
                hash_password(payload.password),
                payload.native_language or "ru",
                payload.target_language or "en",
                verification_code_hash(email, code),
                datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES),
            ),
        )
        send_verification_email(email, code)
        response.delete_cookie("lp_session")
        return {"requires_verification": True, "email": email}


@router.post("/api/register/verify")
def verify_register(payload: VerifyRegistrationPayload, response: Response):
    with db() as conn:
        email = normalize_email(payload.email)
        if not is_valid_email(email):
            raise HTTPException(status_code=400, detail="Укажите корректный email.")
        code = re.sub(r"\D", "", payload.code or "")
        pending = query_one(conn, "select * from email_verification_codes where email=%s", (email,))
        if not pending:
            raise HTTPException(status_code=404, detail="Код не найден. Запросите регистрацию ещё раз.")
        if pending["expires_at"] < datetime.now(timezone.utc):
            with conn.cursor() as cur:
                cur.execute("delete from email_verification_codes where email=%s", (email,))
            raise HTTPException(status_code=410, detail="Код устарел. Запросите новый код.")
        if pending["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Слишком много попыток. Запросите новый код.")
        if verification_code_hash(email, code) != pending["code_hash"]:
            with conn.cursor() as cur:
                cur.execute("update email_verification_codes set attempts=attempts+1 where email=%s", (email,))
            raise HTTPException(status_code=400, detail="Неверный код подтверждения.")
        existing = query_one(conn, "select * from users where email=%s", (email,))
        if existing:
            with conn.cursor() as cur:
                cur.execute("delete from email_verification_codes where email=%s", (email,))
            raise HTTPException(status_code=409, detail="Пользователь уже существует.")
        user = query_one(
            conn,
            """
            insert into users
                (id, email, password_hash, native_language, target_language, email_verified)
            values (%s, %s, %s, %s, %s, true)
            returning *
            """,
            (
                token_id("u"),
                email,
                pending["password_hash"],
                pending["native_language"],
                pending["target_language"],
            ),
        )
        with conn.cursor() as cur:
            cur.execute("delete from email_verification_codes where email=%s", (email,))
        token = token_id("s")
        query_one(conn, "insert into sessions (token, user_id) values (%s, %s) returning token", (token, user["id"]))
        response.set_cookie("lp_session", token, httponly=True, samesite="lax")
        return {"user": public_user(user)}


@router.post("/api/login")
def login(payload: AuthPayload, response: Response):
    with db() as conn:
        email = normalize_email(payload.email)
        if not is_valid_email(email):
            raise HTTPException(status_code=400, detail="Укажите корректный email.")
        user = query_one(conn, "select * from users where email=%s and password_hash=%s", (email, hash_password(payload.password)))
        if not user:
            raise HTTPException(status_code=401, detail="Неверный email или пароль.")
        if not user.get("email_verified", True):
            raise HTTPException(status_code=403, detail="Подтвердите email перед входом.")
        token = token_id("s")
        query_one(conn, "insert into sessions (token, user_id) values (%s, %s) returning token", (token, user["id"]))
        response.set_cookie("lp_session", token, httponly=True, samesite="lax")
        return {"user": public_user(user)}


@router.post("/api/logout")
def logout(response: Response, lp_session: str | None = Cookie(default=None)):
    with db() as conn:
        if lp_session:
            with conn.cursor() as cur:
                cur.execute("delete from sessions where token=%s", (lp_session,))
        response.delete_cookie("lp_session")
        return {"ok": True}


@router.get("/api/me")
def me(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        return {"user": public_user(require_user(conn, lp_session, authorization))}


@router.get("/api/dashboard")
def dashboard(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        docs = query_all(conn, "select * from documents where user_id=%s order by created_at desc", (user["id"],))
        summaries = [document_summary(conn, doc) for doc in docs]
        words = query_all(conn, "select * from user_words where user_id=%s", (user["id"],))
        avg = round(sum(doc["coverage_percent"] for doc in summaries) / len(summaries)) if summaries else 0
        return {"documents": summaries, "stats": {"documents_count": len(summaries), "vocabulary_count": len(words), "learning_words": sum(1 for w in words if w["status"] == "learning"), "average_coverage": avg, "second_text_uploaded": len(summaries) >= 2}}


@router.get("/api/documents")
def documents(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        docs = query_all(conn, "select * from documents where user_id=%s order by created_at desc", (user["id"],))
        return {"documents": [document_summary(conn, doc) for doc in docs]}


@router.post("/api/documents")
def create_document(payload: DocumentPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        validate_document_payload(payload)
        clean = clean_text(payload.raw_text, payload.type)
        doc = query_one(
            conn,
            "insert into documents (id, user_id, title, type, language, raw_text, clean_text) values (%s, %s, %s, %s, %s, %s, %s) returning *",
            (token_id("d"), user["id"], payload.title, payload.type, payload.language, payload.raw_text, clean),
        )
        analysis = analyze_document(conn, user, doc)
        return {"document": document_summary(conn, doc), "analysis": analysis}


@router.get("/api/documents/{document_id}")
def get_document(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = query_one(conn, "select * from documents where id=%s and user_id=%s", (document_id, user["id"]))
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        return {"document": build_pieces(conn, user, doc)}


@router.delete("/api/documents/{document_id}")
def delete_document(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        with conn.cursor() as cur:
            cur.execute("delete from documents where id=%s and user_id=%s", (document_id, user["id"]))
        return {"ok": True}


@router.get("/api/documents/{document_id}/analysis")
def get_document_analysis(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = query_one(conn, "select * from documents where id=%s and user_id=%s", (document_id, user["id"]))
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        analysis = get_analysis(conn, document_id) or analyze_document(conn, user, doc)
        return {"analysis": analysis}


@router.post("/api/documents/{document_id}/analyze")
def post_document_analysis(document_id: str, payload: AnalyzePayload | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = query_one(conn, "select * from documents where id=%s and user_id=%s", (document_id, user["id"]))
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        return {"analysis": analyze_document(conn, user, doc, refresh_important=bool(payload and payload.refresh_important))}


@router.get("/api/knowledge")
def knowledge(context_id: str | None = None, document_id: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        selected_document_id = document_id
        if not selected_document_id and context_id:
            selected_document_id = document_context_id_from_kg_id(context_id)

        if selected_document_id:
            row = query_one(
                conn,
                "select d.*, a.payload from documents d join analyses a on a.document_id=d.id where d.user_id=%s and d.id=%s limit 1",
                (user["id"], selected_document_id),
            )
        else:
            row = query_one(conn, "select d.*, a.payload from documents d join analyses a on a.document_id=d.id where d.user_id=%s order by d.created_at desc limit 1", (user["id"],))

        document_context = build_document_context_from_row(
            conn,
            user,
            row,
            "Расширить тему выбранного текста." if selected_document_id else "Расширить тему последнего загруженного текста.",
        )
        contexts = [document_context] if document_context else []
        selected = document_context
        return {"contexts": [context_summary(item) for item in contexts], "context": selected}


@router.post("/api/knowledge/goal")
def knowledge_goal(payload: KnowledgeGoalPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        context, contexts = build_goal_context(conn, user, payload.goal)
        return {"contexts": contexts, "context": context}


@router.post("/api/knowledge/bridge")
def knowledge_bridge(payload: KnowledgeBridgePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        context = kg_bridge_context(
            conn,
            user,
            payload.context_id,
            payload.bridge_title,
            [],
            document_id=payload.document_id,
        )
        return {"contexts": [context], "context": context}


@router.post("/api/knowledge/analyze")
def knowledge_analyze(payload: KnowledgeAnalyzePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        if payload.bridge_topic:
            source = payload.bridge_topic
            context = build_kg_context(
                conn,
                user,
                f"kg:{topic_slug(payload.bridge_topic)}",
                source,
                title=payload.bridge_topic,
                description="Мостовая тема из Knowledge Graph Mode.",
            )
        else:
            source = payload.text or payload.manual_topic or "Everyday English"
            context = build_kg_context(
                conn,
                user,
                f"kg:{topic_slug(payload.manual_topic or kg_infer_topic_label(source))}",
                source,
                title=payload.manual_topic or kg_infer_topic_label(source),
                description="Theme Card построена по механизму Knowledge Graph Mode.",
            )
        return {"contexts": [context], "context": context}


def rerun_user_analyses(conn, user: dict[str, Any]) -> None:
    rows = query_all(conn, "select payload from analyses where user_id=%s", (user["id"],))
    for row in rows:
        payload = refresh_analysis_payload(conn, user, row["payload"], preserve_important=True)
        save_analysis_payload(conn, payload)


def rerun_document_analysis(conn, user: dict[str, Any], document_id: str) -> None:
    row = query_one(conn, "select payload from analyses where document_id=%s and user_id=%s", (document_id, user["id"]))
    if not row:
        return
    payload = refresh_analysis_payload(conn, user, row["payload"], preserve_important=True)
    save_analysis_payload(conn, payload)


@router.get("/api/words")
def words(status: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        params: list[Any] = [user["id"]]
        extra = ""
        if status:
            extra = " and uw.status=%s"
            params.append(status)
        rows = query_all(
            conn,
            (
                "select uw.*, row_to_json(w.*) as word "
                "from user_words uw join words w on w.id=uw.word_id "
                f"where uw.user_id=%s{extra} and char_length(w.lemma) > 1 "
                "order by w.lemma"
            ),
            tuple(params),
        )
        phrase_params: list[Any] = [user["id"]]
        phrase_extra = ""
        if status:
            phrase_extra = " and up.status=%s"
            phrase_params.append(status)
        phrases = query_all(
            conn,
            f"select up.*, row_to_json(p.*) as phrase from user_phrases up join phrases p on p.id=up.phrase_id where up.user_id=%s{phrase_extra} order by p.base_form",
            tuple(phrase_params),
        )
        return {"words": rows, "phrases": phrases}


@router.patch("/api/user-words/{knowledge_id}")
def update_user_word(knowledge_id: str, payload: StatusPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = query_one(conn, "update user_words set status=%s, confidence=%s, last_reviewed_at=now() where id=%s and user_id=%s returning *", (payload.status, payload.confidence if payload.confidence is not None else confidence_for(payload.status), knowledge_id, user["id"]))
        if not updated:
            raise HTTPException(status_code=404, detail="Слово не найдено.")
        if payload.refresh_analysis:
            if payload.document_id:
                rerun_document_analysis(conn, user, payload.document_id)
            else:
                rerun_user_analyses(conn, user)
        return {"user_word": updated}


@router.post("/api/user-words/{knowledge_id}/translation")
def load_user_word_translation(
    knowledge_id: str,
    payload: TranslationPayload | None = None,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        word = load_word_translation_on_demand(
            conn,
            user,
            knowledge_id,
            translation_ru=payload.translation_ru if payload else None,
        )
        return {"word": word}


@router.patch("/api/user-phrases/{knowledge_id}")
def update_user_phrase(knowledge_id: str, payload: StatusPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = query_one(conn, "update user_phrases set status=%s, confidence=%s where id=%s and user_id=%s returning *", (payload.status, payload.confidence if payload.confidence is not None else confidence_for(payload.status), knowledge_id, user["id"]))
        if not updated:
            raise HTTPException(status_code=404, detail="Фраза не найдена.")
        if payload.refresh_analysis:
            if payload.document_id:
                rerun_document_analysis(conn, user, payload.document_id)
            else:
                rerun_user_analyses(conn, user)
        return {"user_phrase": updated}


@router.post("/api/user-phrases/{knowledge_id}/translation")
def load_user_phrase_translation(
    knowledge_id: str,
    payload: TranslationPayload | None = None,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        phrase = load_phrase_translation_on_demand(
            conn,
            user,
            knowledge_id,
            translation_ru=payload.translation_ru if payload else None,
        )
        return {"phrase": phrase}


@router.get("/api/learn")
def learn(document_id: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        rows = query_all(
            conn,
            "select * from learn_blocks where user_id=%s order by created_at asc, id asc",
            (user["id"],),
        )
        return {"blocks": [public_learn_block(conn, user, row) for row in rows]}


@router.post("/api/learn/blocks")
def create_learn_block(payload: LearnBlockPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        units = normalize_learn_units(payload.units)
        if not units:
            raise HTTPException(status_code=400, detail="Нет новых слов для блока Learn.")
        title = re.sub(r"\s+", " ", (payload.title or "Learn block").strip())[:160] or "Learn block"
        row = query_one(
            conn,
            """
            insert into learn_blocks (id, user_id, title, payload)
            values (%s, %s, %s, %s)
            returning *
            """,
            (token_id("lb"), user["id"], title, json.dumps({"units": units})),
        )
        return {"block": public_learn_block(conn, user, row)}


@router.patch("/api/learn/blocks/{block_id}")
def update_learn_block(block_id: str, payload: LearnBlockUpdatePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        value = payload.frequency_filter or "all"
        if value not in {"20-80", "50-50", "all"}:
            raise HTTPException(status_code=400, detail="Неверный фильтр частотности.")
        row = query_one(
            conn,
            "update learn_blocks set frequency_filter=%s where id=%s and user_id=%s returning *",
            (value, block_id, user["id"]),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден.")
        return {"block": public_learn_block(conn, user, row)}


@router.delete("/api/learn/blocks/{block_id}")
def delete_learn_block(block_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        with conn.cursor() as cur:
            cur.execute("delete from learn_blocks where id=%s and user_id=%s", (block_id, user["id"]))
        return {"ok": True}


@router.get("/api/learn/blocks/{block_id}/anki")
def export_learn_block_anki(block_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        row = query_one(conn, "select * from learn_blocks where id=%s and user_id=%s", (block_id, user["id"]))
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден.")
        block = public_learn_block(conn, user, row)
        export_units = [
            unit
            for unit in filter_learn_units_for_frequency(block.get("units") or [], block.get("frequency_filter") or "all")
            if unit.get("status") not in {"known", "ignored"}
        ]
        if not export_units:
            raise HTTPException(status_code=400, detail="В блоке нет неизученных слов для ANKI.")
        text = build_learn_block_anki_text(block)
        filename = anki_filename(block["title"])
        return StreamingResponse(
            iter([text.encode("utf-8-sig")]),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/api/learn/blocks/merge")
def merge_learn_blocks(payload: LearnMergePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        block_ids = [item for item in payload.block_ids if item]
        if len(set(block_ids)) < 2:
            raise HTTPException(status_code=400, detail="Выберите минимум два блока.")
        rows = query_all(
            conn,
            "select * from learn_blocks where user_id=%s and id = any(%s) order by created_at asc, id asc",
            (user["id"], block_ids),
        )
        if len(rows) < 2:
            raise HTTPException(status_code=404, detail="Блоки не найдены.")
        units = normalize_learn_units([
            unit
            for row in rows
            for unit in ((row.get("payload") or {}).get("units") or [])
        ])
        title = ". ".join([row["title"] for row in rows if row.get("title")])[:220] or "Merged Learn block"
        with conn.cursor() as cur:
            cur.execute("delete from learn_blocks where user_id=%s and id = any(%s)", (user["id"], [row["id"] for row in rows]))
        row = query_one(
            conn,
            """
            insert into learn_blocks (id, user_id, title, payload)
            values (%s, %s, %s, %s)
            returning *
            """,
            (token_id("lb"), user["id"], title, json.dumps({"units": units})),
        )
        return {"block": public_learn_block(conn, user, row)}


@router.post("/api/learn/review")
def review(payload: ReviewPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        status = "known" if payload.grade >= 4 else "learning" if payload.grade >= 2 else "unknown"
        updated = query_one(conn, "update user_words set status=%s, confidence=%s, last_reviewed_at=now() where id=%s and user_id=%s returning *", (status, max(0, min(1, payload.grade / 4)), payload.user_word_id, user["id"]))
        if not updated:
            raise HTTPException(status_code=404, detail="Карточка не найдена.")
        query_one(conn, "insert into reviews (id, user_id, word_id, grade) values (%s, %s, %s, %s) returning id", (token_id("r"), user["id"], updated["word_id"], payload.grade))
        rerun_user_analyses(conn, user)
        return {"user_word": updated}


@router.patch("/api/settings")
def settings(payload: dict[str, str], lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        updated = query_one(
            conn,
            """
            update users set
                native_language=%s,
                target_language=%s,
                tts_enabled=%s,
                tts_voice=%s,
                tts_rate=%s,
                tts_pitch=%s,
                tts_volume=%s
            where id=%s
            returning *
            """,
            (
                payload.get("native_language", user["native_language"]),
                payload.get("target_language", user["target_language"]),
                parse_bool(payload.get("tts_enabled"), bool(user.get("tts_enabled", True))),
                (payload.get("tts_voice") or user.get("tts_voice") or ""),
                clamp_float(payload.get("tts_rate"), float(user.get("tts_rate") or 1), 0.5, 2.0),
                clamp_float(payload.get("tts_pitch"), float(user.get("tts_pitch") or 1), 0.5, 2.0),
                clamp_float(payload.get("tts_volume"), float(user.get("tts_volume") or 1), 0.0, 1.0),
                user["id"],
            ),
        )
        return {"user": public_user(updated)}


@router.get("/{full_path:path}")
def spa(full_path: str):
    target = PUBLIC_DIR / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(PUBLIC_DIR / "index.html")

