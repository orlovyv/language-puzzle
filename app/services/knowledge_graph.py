"""Knowledge Graph mode: build themed word/phrase contexts from a topic or text.

Words are ranked by semantic relatedness to the topic vector, corpus frequency
and a usefulness heuristic, then filtered against what the user already knows.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger("language_puzzle.kg")

from app.repositories import phrase_repository, word_repository
from app.services.analysis import ensure_phrase, ensure_word, make_phrase_hit
from app.services.scoring import pos_to_relation
from app.services.text_processing import (
    NLP,
    example_for_word_prefix,
    kg_normalize_phrase,
    normalize_lemma,
)
from app.services.translation import resolve_lexical_translation, translate_goal_to_target_language
from app.services.vocabulary import (
    phrase_dictionary,
    phrase_dictionary_translation,
    system_terms,
)
from app.services.llm import enrichment
from app.services.llm.client import LLMUnavailable
from app.utils.security import token_id


try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    from wordfreq import top_n_list, zipf_frequency
except ImportError:  # pragma: no cover
    top_n_list = None
    zipf_frequency = None


# Candidate pool / frequency band tuning.
KG_MIN_ZIPF = 3.0
KG_MAX_ZIPF = 5.35
KG_MAX_FREQUENCY_WORDS = 20000
KG_MAX_CANDIDATES = 2600

# Ranking weights (semantic + frequency + usefulness, minus frequency-band penalties).
KG_SEMANTIC_MIN = 0.24
KG_SEMANTIC_WEIGHT = 0.62
KG_FREQUENCY_WEIGHT = 0.28
KG_USEFULNESS_WEIGHT = 0.10
KG_RARE_ZIPF = 3.15
KG_RARE_PENALTY = 0.18
KG_COMMON_ZIPF = 5.05
KG_COMMON_PENALTY = 0.12


# ---------------------------------------------------------------------------
# frequency helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# topic labelling
# ---------------------------------------------------------------------------
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


def topic_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:48] or token_id("topic")


def topic_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:1].upper() + text[1:] if text else "Topic"


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------
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
        if semantic < KG_SEMANTIC_MIN:
            continue
        frequency = float(candidate["frequency"])
        usefulness = (1.0 if 4 <= len(word) <= 10 else 0.72) * (1.0 if candidate["pos"] in {"noun", "verb"} else 0.86)
        rare_penalty = max(0.0, KG_RARE_ZIPF - frequency) * KG_RARE_PENALTY
        too_common_penalty = max(0.0, frequency - KG_COMMON_ZIPF) * KG_COMMON_PENALTY
        score = (
            semantic * KG_SEMANTIC_WEIGHT
            + kg_frequency_to_score(frequency) * KG_FREQUENCY_WEIGHT
            + usefulness * KG_USEFULNESS_WEIGHT
            - rare_penalty
            - too_common_penalty
        )
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


# ---------------------------------------------------------------------------
# collocations / phrasal verbs / bridges
# ---------------------------------------------------------------------------
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


def kg_build_bridge_topics(conn, user: dict[str, Any], topic: str, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # AI-crafted, vivid bridge situations (titles + reason + seed words) when AI
    # is available — Premium, or everyone in donation mode.
    if enrichment._ai_enabled(user):
        related = [item["word"] for item in ranked[:20] if item.get("word")]
        try:
            ai_topics = enrichment.ai_bridge_topics(conn, user, topic, related)
            logger.info("KG AI bridge topics: %d for %r", len(ai_topics), topic)
            return [
                {"bridge_topic": t["title"], "reason": t.get("reason", ""),
                 "starter_words": t.get("starter_words", [])}
                for t in ai_topics
            ]
        except LLMUnavailable as exc:
            logger.info("KG AI bridge topics unavailable for %r — %s", topic, exc)

    # Free / fallback: simple template from ranked seed words.
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


# ---------------------------------------------------------------------------
# unit construction
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# context assembly
# ---------------------------------------------------------------------------
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


def group_units_for_graph(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"place": [], "person": [], "action": [], "object": [], "phrase": [], "problem": []}
    for unit in units:
        groups.setdefault(unit.get("relation", "object"), groups["object"]).append(unit)
    return groups


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
    known_terms = {row["lemma"] for row in word_repository.known_lemmas(conn, user["id"])}
    known_terms.update({row["base_form"] for row in phrase_repository.known_phrase_base_forms(conn, user["id"])})
    # Vocabulary always comes from our frequency/semantic ranking (free and
    # premium alike); AI is used only for bridge topics.
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
    for bridge in kg_build_bridge_topics(conn, user, topic, ranked):
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
            "shared": bridge.get("starter_words", []),
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
