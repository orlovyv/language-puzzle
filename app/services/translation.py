"""Translation, transcription and WordNet lookup.

Resolution order for a lemma: MUSE bilingual dictionary -> optional Google
Translate fallback -> optional WordNet definition. All Google-Translate-backed
calls funnel through one lock/cache here so the rest of the app never touches the
async ``googletrans`` client directly.
"""

from __future__ import annotations

import re
import tarfile
from threading import Lock
from typing import Any

from app.config import (
    GOOGLETRANS_SOURCE_LANG,
    GOOGLETRANS_TARGET_LANG,
    USE_GOOGLETRANS_FALLBACK,
    USE_IPA_TRANSCRIPTION,
)
from app.repositories import lexicon_repository, word_repository
from app.utils.security import run_coroutine_from_sync

try:
    from googletrans import Translator as GoogleTranslator
except ImportError:  # pragma: no cover
    GoogleTranslator = None
try:
    import eng_to_ipa as eng_to_ipa_lib
except ImportError:  # pragma: no cover
    eng_to_ipa_lib = None


UNRESOLVED_TRANSLATION = "перевод уточняется"

_GOOGLE_TRANSLATE_LOCK = Lock()
_GOOGLETRANS_CACHE: dict[str, str | None] = {}
_ANKI_EXAMPLE_TRANSLATION_CACHE: dict[str, str | None] = {}
_IPA_LOCK = Lock()
_IPA_CACHE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# IPA transcription
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# MUSE bilingual dictionary
# ---------------------------------------------------------------------------
def muse_translation(conn, lemma: str, limit: int = 3) -> str | None:
    rows = lexicon_repository.muse_targets(conn, lemma.lower().replace(" ", "_"), limit)
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


# ---------------------------------------------------------------------------
# Google Translate (async client wrapped for sync callers)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
def resolve_lexical_translation(
    conn,
    lemma: str,
    fallback: str = UNRESOLVED_TRANSLATION,
    allow_googletrans: bool = False,
) -> str:
    return (
        muse_translation(conn, lemma)
        or (googletrans_translation(lemma) if allow_googletrans else None)
        or fallback
    )


def has_resolved_translation(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text and text != UNRESOLVED_TRANSLATION)


def clean_client_translation(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not has_resolved_translation(text):
        return ""
    return text[:500]


def update_words_from_muse(conn) -> None:
    for word in word_repository.words_with_unresolved_translation(conn):
        value = resolve_lexical_translation(conn, word["lemma"], fallback="")
        if value:
            word_repository.update_word_translation(conn, word["id"], value)


# ---------------------------------------------------------------------------
# WordNet
# ---------------------------------------------------------------------------
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


def format_wordnet_entry(entry: dict[str, Any]) -> str:
    synonyms = [item for item in (entry.get("synonyms") or []) if item]
    suffix = f"; syn: {', '.join(synonyms[:5])}" if len(synonyms) > 1 else ""
    return f"WordNet: {entry['definition']}{suffix}"[:500]


def wordnet_definition(conn, lemma: str, pos: str | None) -> str | None:
    wn_pos = wordnet_pos(pos)
    normalized = wordnet_lemma(lemma)
    if wn_pos:
        entry = lexicon_repository.wordnet_entry(conn, normalized, wn_pos)
        if entry:
            return format_wordnet_entry(entry)
    entry = lexicon_repository.wordnet_entry_any_pos(conn, normalized)
    return format_wordnet_entry(entry) if entry else None
