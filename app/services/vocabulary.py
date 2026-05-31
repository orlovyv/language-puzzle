"""System term lists and phrase-dictionary lookups, plus spaCy phrase detection."""

from __future__ import annotations

from typing import Any

from spacy.matcher import PhraseMatcher

from app.repositories import lexicon_repository
from app.services.text_processing import NLP, kg_normalize_phrase, normalize_lemma
from app.services.translation import has_resolved_translation


# ---------------------------------------------------------------------------
# system terms
# ---------------------------------------------------------------------------
def system_terms(conn, term_type: str) -> set[str]:
    return lexicon_repository.terms_of_type(conn, term_type)


def known_seed_terms(conn) -> set[str]:
    return system_terms(conn, "known_seed")


def context_topic_stopwords(conn) -> set[str]:
    return known_seed_terms(conn) | system_terms(conn, "context_topic_stopword")


# ---------------------------------------------------------------------------
# phrase dictionary
# ---------------------------------------------------------------------------
def phrase_dictionary(conn, language: str = "en") -> list[dict[str, Any]]:
    return lexicon_repository.phrase_dictionary(conn, language)


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
        row = lexicon_repository.phrase_translation_by_type(conn, language, text, phrase_type)
        if row and has_resolved_translation(row["translation_ru"]):
            return row["translation_ru"]
    row = lexicon_repository.phrase_translation_any_type(conn, language, text)
    if row and has_resolved_translation(row["translation_ru"]):
        return row["translation_ru"]
    return None


# ---------------------------------------------------------------------------
# phrase detection over a parsed document
# ---------------------------------------------------------------------------
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
