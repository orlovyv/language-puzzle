"""Document analysis: turning a stored document into word/phrase coverage stats.

This is the cohesive core that ties together words, phrases, user knowledge and
the persisted ``analyses`` payloads, including the routines that re-run analyses
when a user's knowledge changes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.config import USE_WORDNET_FALLBACK
from app.repositories import (
    analysis_repository,
    document_repository,
    phrase_repository,
    word_repository,
)
from app.services.scoring import confidence_for, pos_to_relation, priority_for, rank_for
from app.services.text_processing import NLP, clean_text, is_short_word, normalize_lemma
from app.services.translation import (
    clean_client_translation,
    has_resolved_translation,
    resolve_lexical_translation,
    word_transcription,
    wordnet_definition,
)
from app.services.vocabulary import detect_phrases, known_seed_terms, phrase_dictionary_translation
from app.services.llm import enrichment
from app.services.llm.client import LLMUnavailable
from app.utils.security import token_id


def _ai_translation(conn, user: dict[str, Any], text: str, pos: str | None = None, context: str | None = None) -> str:
    """Premium AI translation, or "" if unavailable (caller falls back)."""
    try:
        return enrichment.ai_translate(conn, user, text, pos=pos, context=context)
    except LLMUnavailable:
        return ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# word / phrase materialisation
# ---------------------------------------------------------------------------
def ensure_word(
    conn,
    user_id: str,
    language: str,
    lemma: str,
    pos: str,
    known_seeds: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    word = word_repository.find_word(conn, language, lemma)
    if not word:
        word_id = token_id("w")
        lexical_value = resolve_lexical_translation(conn, lemma)
        transcription = word_transcription(lemma) if language == "en" else ""
        word = word_repository.insert_word(
            conn, word_id, language, lemma, pos, lexical_value, transcription, rank_for(lemma)
        )
    elif word["translation_ru"] == "перевод уточняется":
        lexical_value = resolve_lexical_translation(conn, lemma, fallback="")
        if not lexical_value and USE_WORDNET_FALLBACK:
            lexical_value = wordnet_definition(conn, lemma, word.get("part_of_speech") or pos) or ""
        if lexical_value:
            word = word_repository.update_word_translation(conn, word["id"], lexical_value)
    if language == "en" and not (word.get("transcription") or "").strip():
        transcription = word_transcription(lemma)
        if transcription:
            word = word_repository.update_word_transcription(conn, word["id"], transcription)
    knowledge = word_repository.find_user_word(conn, user_id, word["id"])
    if not knowledge:
        seed_terms = known_seeds if known_seeds is not None else known_seed_terms(conn)
        status = "known" if lemma in seed_terms else "unknown"
        knowledge = word_repository.insert_user_word(
            conn, token_id("uw"), user_id, word["id"], status, confidence_for(status)
        )
    return word, knowledge


def ensure_phrase(conn, user_id: str, language: str, hit: dict[str, Any]) -> dict[str, Any]:
    phrase = phrase_repository.find_phrase(conn, language, hit["base_form"])
    if not phrase:
        phrase = phrase_repository.insert_phrase(
            conn, token_id("p"), language, hit["phrase"], hit["base_form"], hit["type"], hit["translation_ru"]
        )
    elif (
        not has_resolved_translation(phrase.get("translation_ru"))
        and has_resolved_translation(hit.get("translation_ru"))
    ):
        phrase = phrase_repository.update_phrase_translation(conn, phrase["id"], hit["translation_ru"])
    knowledge = phrase_repository.find_user_phrase(conn, user_id, phrase["id"])
    if not knowledge:
        knowledge = phrase_repository.insert_user_phrase(conn, token_id("up"), user_id, phrase["id"])
    return {**hit, "phrase_id": phrase["id"], "user_phrase_id": knowledge["id"], "status": knowledge["status"]}


def make_phrase_hit(base_form: str, phrase_type: str, translation: str) -> dict[str, Any]:
    return {
        "start": 0,
        "end": len(base_form),
        "phrase": base_form,
        "base_form": base_form,
        "type": phrase_type,
        "translation_ru": translation,
    }


# ---------------------------------------------------------------------------
# document analysis
# ---------------------------------------------------------------------------
def analyze_document(
    conn,
    user: dict[str, Any],
    document: dict[str, Any],
    refresh_important: bool = False,
    preserve_ids: list[str] | None = None,
) -> dict[str, Any]:
    clean = clean_text(document["raw_text"], document["type"])
    doc = NLP(clean, disable=["ner"])
    phrase_hits = [
        ensure_phrase(conn, user["id"], document["language"], hit)
        for hit in detect_phrases(conn, doc, document["language"])
    ]
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
    document_repository.update_clean_text(conn, document["id"], clean)
    analysis_repository.upsert_analysis(conn, payload)
    return payload


def get_analysis(conn, document_id: str) -> dict[str, Any] | None:
    return analysis_repository.find_analysis_payload(conn, document_id)


def get_user_analysis(conn, user_id: str, document_id: str) -> dict[str, Any] | None:
    return analysis_repository.find_user_analysis_payload(conn, user_id, document_id)


# ---------------------------------------------------------------------------
# payload refresh / persistence
# ---------------------------------------------------------------------------
def refresh_analysis_payload(
    conn,
    user: dict[str, Any],
    payload: dict[str, Any],
    preserve_important: bool = True,
) -> dict[str, Any]:
    word_statuses = {row["word_id"]: row for row in word_repository.user_words(conn, user["id"])}
    word_rows = {row["id"]: row for row in word_repository.all_words(conn)}
    phrase_statuses = {row["phrase_id"]: row for row in phrase_repository.user_phrases(conn, user["id"])}

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
    analysis_repository.update_analysis_payload(conn, payload)


def refresh_all_analysis_payloads(conn) -> None:
    for row in analysis_repository.all_analyses_with_user(conn):
        payload = row.pop("payload")
        payload = refresh_analysis_payload(conn, row, payload, preserve_important=True)
        save_analysis_payload(conn, payload)


def rerun_user_analyses(conn, user: dict[str, Any]) -> None:
    for row in analysis_repository.user_analysis_payloads(conn, user["id"]):
        payload = refresh_analysis_payload(conn, user, row["payload"], preserve_important=True)
        save_analysis_payload(conn, payload)


def rerun_document_analysis(conn, user: dict[str, Any], document_id: str) -> None:
    payload = analysis_repository.find_user_analysis_payload(conn, user["id"], document_id)
    if not payload:
        return
    payload = refresh_analysis_payload(conn, user, payload, preserve_important=True)
    save_analysis_payload(conn, payload)


# ---------------------------------------------------------------------------
# on-demand translation loading
# ---------------------------------------------------------------------------
def load_word_translation_on_demand(
    conn,
    user: dict[str, Any],
    knowledge_id: str,
    translation_ru: str | None = None,
) -> dict[str, Any]:
    row = word_repository.find_user_word_with_word(conn, knowledge_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Слово не найдено.")

    # Premium: always try a context-aware AI translation (cached, so it costs
    # tokens only once per word), overwriting the dictionary value when it works.
    if enrichment._is_premium(user):
        ai = _ai_translation(
            conn, user, row.get("lemma", ""), pos=row.get("part_of_speech"), context=row.get("example")
        )
        if ai:
            row = word_repository.update_word_translation(conn, row["id"], ai)
            rerun_user_analyses(conn, user)
            return {**row, "user_word_id": knowledge_id}
        if has_resolved_translation(row.get("translation_ru")):
            return row

    # Free (or AI unavailable): keep the existing translation, else client value.
    if has_resolved_translation(row.get("translation_ru")):
        return row
    translation = clean_client_translation(translation_ru)
    if translation:
        row = word_repository.update_word_translation(conn, row["id"], translation)
        rerun_user_analyses(conn, user)
        return {**row, "user_word_id": knowledge_id}
    return row


def load_phrase_translation_on_demand(
    conn,
    user: dict[str, Any],
    knowledge_id: str,
    translation_ru: str | None = None,
) -> dict[str, Any]:
    row = phrase_repository.find_user_phrase_with_phrase(conn, knowledge_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Фраза не найдена.")

    phrase = row.get("base_form") or row.get("phrase")

    # Premium: prefer an AI translation (cached), overwriting existing value.
    if enrichment._is_premium(user):
        ai = _ai_translation(conn, user, phrase, pos=row.get("type"))
        if ai:
            row = phrase_repository.update_phrase_translation(conn, row["id"], ai)
            rerun_user_analyses(conn, user)
            return {**row, "user_phrase_id": knowledge_id}
        if has_resolved_translation(row.get("translation_ru")):
            return row

    if has_resolved_translation(row.get("translation_ru")):
        return row

    translation = phrase_dictionary_translation(
        conn,
        phrase,
        phrase_type=row.get("type"),
        language=row.get("language") or user.get("target_language") or "en",
    )
    if not translation:
        translation = clean_client_translation(translation_ru)
    if translation:
        row = phrase_repository.update_phrase_translation(conn, row["id"], translation)
        rerun_user_analyses(conn, user)
        return {**row, "user_phrase_id": knowledge_id}
    return row


# ---------------------------------------------------------------------------
# on-demand AI card (synonyms / mnemonic / context) for premium
# ---------------------------------------------------------------------------
def load_word_ai_card(conn, user: dict[str, Any], knowledge_id: str) -> dict[str, Any]:
    row = word_repository.find_user_word_with_word(conn, knowledge_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Слово не найдено.")
    try:
        return enrichment.ai_card(
            conn, user, row.get("lemma", ""), row.get("translation_ru", ""), pos=row.get("part_of_speech")
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail="AI-подсказки сейчас недоступны.") from exc


def load_phrase_ai_card(conn, user: dict[str, Any], knowledge_id: str) -> dict[str, Any]:
    row = phrase_repository.find_user_phrase_with_phrase(conn, knowledge_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Фраза не найдена.")
    text = row.get("base_form") or row.get("phrase") or ""
    try:
        return enrichment.ai_card(conn, user, text, row.get("translation_ru", ""), pos=row.get("type"))
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail="AI-подсказки сейчас недоступны.") from exc


# ---------------------------------------------------------------------------
# unit projection
# ---------------------------------------------------------------------------
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
