"""Text cleaning, tokenisation helpers and the shared spaCy pipeline.

This module owns the single ``NLP`` instance used across the app so the large
``en_core_web_lg`` model is loaded exactly once.
"""

from __future__ import annotations

import re
from typing import Any

try:
    import spacy
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("spaCy is required. Install requirements.txt first.") from exc

try:
    NLP = spacy.load("en_core_web_lg")
except OSError as exc:  # pragma: no cover
    raise RuntimeError("spaCy model en_core_web_lg is not installed.") from exc


_TIMECODE = r"\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b"


def count_text_lines(value: str) -> int:
    return len(re.split(r"\r\n|\r|\n", value)) if value else 0


def looks_like_binary_text(value: str) -> bool:
    if "\x00" in value:
        return True
    if not value:
        return False
    suspicious = sum(1 for char in value if ord(char) < 32 and char not in "\t\n\r")
    return suspicious / len(value) > 0.05


def clean_text(raw: str, doc_type: str = "text") -> str:
    text = (raw or "").replace("\r", "\n")
    subtitle_like = bool(re.search(_TIMECODE, text))
    if doc_type == "srt" or subtitle_like:
        text = re.sub(_TIMECODE, " ", text)
        lines = []
        for line in text.split("\n"):
            value = line.strip()
            if re.fullmatch(r"\d+", value):
                continue
            if re.search(_TIMECODE, value):
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


def kg_normalize_phrase(value: str) -> str:
    value = re.sub(r"[^A-Za-z\s'-]", " ", (value or "").lower())
    return re.sub(r"\s+", " ", value).strip()


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
        index
        for index in (
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
