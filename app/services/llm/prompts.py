"""Prompt templates for the four AI enrichment tasks.

Every prompt instructs the model to return a strict JSON object so the client's
``response_format={"type":"json_object"}`` parsing is deterministic.
"""

from __future__ import annotations

import json
from typing import Any

TRANSLATE_SYSTEM = (
    "You are a precise EN->RU lexicographer. Return ONLY a JSON object "
    '{"translation": "..."} with a concise, natural Russian translation. '
    "Respect the given part of speech and sentence context. No extra keys, no notes."
)

EXAMPLE_SYSTEM = (
    "You are an English teacher creating example sentences for learners. "
    'Return ONLY a JSON object {"en": "...", "ru": "..."}: one natural English '
    "sentence (B1 level) using the target word, and its Russian translation."
)

TOPIC_VOCAB_SYSTEM = (
    "You are a vocabulary curator for English learners. Given a topic and a list "
    "of words the learner already knows, return ONLY a JSON object "
    '{"items": [{"word": "...", "translation": "...", "why": "..."}]} with up to '
    "15 useful, topical English words the learner likely does NOT know. "
    "'translation' is Russian; 'why' is a short Russian note on relevance. "
    "Exclude known words. Single words or short collocations only."
)

ANKI_CARD_SYSTEM = (
    "You are building a rich Anki flashcard for an English word/phrase. Return "
    "ONLY a JSON object with these keys:\n"
    '{"mnemonic": "...", "synonyms": ["..."], "context": "...", '
    '"verb_forms": {"base": "...", "past": "...", "participle": "..."}, '
    '"other_meanings": [{"meaning": "<RU>", "note": "<RU, optional>"}], '
    '"context_examples": [{"en": "...", "ru": "..."}]}\n'
    "- mnemonic: short Russian mnemonic.\n"
    "- synonyms: up to 4 English synonyms.\n"
    "- context: short Russian usage note.\n"
    "- verb_forms: ONLY if the term is a verb — base, past simple, past participle "
    "(e.g. go/went/gone). Omit or use empty strings for non-verbs.\n"
    "- other_meanings: up to 3 OTHER Russian meanings (besides the given translation).\n"
    "- context_examples: up to 3 example sentences in DIFFERENT contexts, each with "
    "English 'en' and Russian 'ru'."
)

ANKI_CARDS_BATCH_SYSTEM = (
    "You are building rich Anki flashcards for a BATCH of English words/phrases. "
    'You receive a JSON object {"terms": [{"term": "...", "translation": "...", '
    '"part_of_speech": "..."}]}. Return ONLY a JSON object {"cards": [...]} where '
    "each element corresponds to ONE input term and has these keys:\n"
    '{"term": "<exactly the input term>", "mnemonic": "...", "synonyms": ["..."], '
    '"context": "...", "verb_forms": {"base": "...", "past": "...", "participle": "..."}, '
    '"other_meanings": [{"meaning": "<RU>", "note": "<RU, optional>"}], '
    '"context_examples": [{"en": "...", "ru": "..."}]}\n'
    "- term: copy the input term EXACTLY so it can be matched back.\n"
    "- mnemonic: short Russian mnemonic.\n"
    "- synonyms: up to 4 English synonyms.\n"
    "- context: short Russian usage note.\n"
    "- verb_forms: ONLY if the term is a verb — base, past simple, past participle "
    "(e.g. go/went/gone). Omit or use empty strings for non-verbs.\n"
    "- other_meanings: up to 3 OTHER Russian meanings (besides the given translation).\n"
    "- context_examples: up to 3 example sentences in DIFFERENT contexts, each with "
    "English 'en' and Russian 'ru'.\n"
    "Return exactly one card object per input term, preserving their order."
)

BRIDGE_TOPICS_SYSTEM = (
    "You design 'bridge topics' for an English learner: adjacent real-life "
    "situations that naturally extend a given topic and motivate new vocabulary. "
    'Return ONLY a JSON object {"topics": [{"title": "...", "reason": "...", '
    '"starter_words": ["...", "..."]}]} with up to 6 topics. '
    "'title' is a vivid, concrete ENGLISH situation name (NOT 'X situations' — "
    "e.g. 'Checking in at the airport', 'Ordering food at a cafe'). 'reason' is a "
    "short Russian note why it extends the topic. 'starter_words' are 2-4 English "
    "seed words for it."
)


def translate_user_prompt(text: str, pos: str | None, context: str | None) -> str:
    return json.dumps(
        {"word": text, "part_of_speech": pos or "", "context": context or ""},
        ensure_ascii=False,
    )


def example_user_prompt(word: str, target_language: str) -> str:
    return json.dumps({"word": word, "target_language": target_language or "ru"}, ensure_ascii=False)


def topic_vocab_user_prompt(topic: str, known_terms: list[str]) -> str:
    return json.dumps(
        {"topic": topic, "known_words": sorted(known_terms)[:200]},
        ensure_ascii=False,
    )


def anki_card_user_prompt(text: str, translation: str, pos: str | None) -> str:
    return json.dumps(
        {"term": text, "translation": translation or "", "part_of_speech": pos or ""},
        ensure_ascii=False,
    )


def anki_cards_batch_user_prompt(items: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "terms": [
                {
                    "term": item.get("text") or "",
                    "translation": item.get("translation") or "",
                    "part_of_speech": item.get("pos") or "",
                }
                for item in items
            ]
        },
        ensure_ascii=False,
    )


def bridge_topics_user_prompt(topic: str, related_words: list[str]) -> str:
    return json.dumps(
        {"topic": topic, "related_words": related_words[:20]},
        ensure_ascii=False,
    )
