"""Pure scoring/ranking heuristics shared across analysis and the knowledge graph."""

from __future__ import annotations

# Verbs ranked by rough corpus frequency; index acts as their frequency rank.
_COMMON_VERBS = [
    "be", "have", "do", "say", "go", "get", "make", "know", "think", "take",
    "see", "come", "want", "look", "use", "find", "give", "tell", "work", "call",
]

_STATUS_CONFIDENCE = {
    "unknown": 0.1,
    "seen": 0.35,
    "learning": 0.6,
    "known": 0.95,
    "ignored": 1,
}


def rank_for(lemma: str) -> int:
    """Approximate frequency rank for a lemma (lower = more common)."""
    if lemma in _COMMON_VERBS:
        return _COMMON_VERBS.index(lemma) + 1
    return min(9000, 600 + len(lemma) * 137)


def confidence_for(status: str) -> float:
    return _STATUS_CONFIDENCE.get(status, 0.1)


def priority_for(count: int, rank: int, status: str, lemma: str) -> float:
    if status == "ignored":
        return -1
    usefulness = max(0, 1000 - rank) / 80
    noise = 100 if len(lemma) <= 1 else 0
    return count * 10 + usefulness - noise


def pos_to_relation(pos: str) -> str:
    value = (pos or "").lower()
    if value in {"verb", "aux"}:
        return "action"
    if value in {"propn", "noun"}:
        return "object"
    if value in {"adj", "adv"}:
        return "problem"
    return "object"
