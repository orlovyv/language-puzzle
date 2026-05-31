"""High-level AI enrichment with persistent caching and daily quotas.

Each function:
  1. returns a cached result if present (no quota charge);
  2. otherwise enforces the caller's daily quota;
  3. calls the LLM, caches and returns the parsed result.

Any failure raises ``LLMUnavailable`` so callers fall back to the free path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.config import AI_DAILY_LIMIT_FREE, AI_DAILY_LIMIT_PREMIUM, LLM_MODEL
from app.repositories import ai_repository
from app.services.llm import prompts
from app.services.llm.client import LLMUnavailable, chat_json, is_configured


def _cache_key(task: str, payload: str) -> str:
    raw = f"{task}|{LLM_MODEL}|{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_premium(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if user.get("plan") != "premium":
        return False
    until = user.get("premium_until")
    if until is None:
        return True
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return False
    now = datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until >= now


def _daily_limit(user: dict[str, Any] | None) -> int:
    return AI_DAILY_LIMIT_PREMIUM if _is_premium(user) else AI_DAILY_LIMIT_FREE


def _check_and_count_quota(conn, user: dict[str, Any] | None) -> None:
    if not user:
        raise LLMUnavailable("no user for AI quota")
    limit = _daily_limit(user)
    if limit <= 0:
        raise LLMUnavailable("AI not available on current plan")
    today = datetime.now(timezone.utc).date()
    if ai_repository.usage_today(conn, user["id"], today) >= limit:
        raise LLMUnavailable("daily AI limit reached")
    ai_repository.increment_usage(conn, user["id"], today)


def _run_cached(conn, user, task: str, payload: str, system: str, user_prompt: str) -> Any:
    if not is_configured():
        raise LLMUnavailable("AI not configured")
    key = _cache_key(task, payload)
    cached = ai_repository.get_cached(conn, key)
    if cached is not None:
        return cached
    _check_and_count_quota(conn, user)
    result = chat_json(system, user_prompt)
    ai_repository.put_cached(conn, key, task, result)
    return result


# ---------------------------------------------------------------------------
# public enrichment functions
# ---------------------------------------------------------------------------
def ai_translate(conn, user, text: str, pos: str | None = None, context: str | None = None) -> str:
    payload = prompts.translate_user_prompt(text, pos, context)
    result = _run_cached(conn, user, "translate", payload, prompts.TRANSLATE_SYSTEM, payload)
    value = str(result.get("translation") or "").strip()
    if not value:
        raise LLMUnavailable("empty translation")
    return value[:500]


def ai_example(conn, user, word: str, target_language: str = "ru") -> dict[str, str]:
    payload = prompts.example_user_prompt(word, target_language)
    result = _run_cached(conn, user, "example", payload, prompts.EXAMPLE_SYSTEM, payload)
    en = str(result.get("en") or "").strip()
    ru = str(result.get("ru") or "").strip()
    if not en:
        raise LLMUnavailable("empty example")
    return {"en": en[:500], "ru": ru[:500]}


def ai_topic_vocabulary(conn, user, topic: str, known_terms: list[str]) -> list[dict[str, str]]:
    payload = prompts.topic_vocab_user_prompt(topic, known_terms)
    result = _run_cached(conn, user, "topic_vocab", payload, prompts.TOPIC_VOCAB_SYSTEM, payload)
    items = result.get("items")
    if not isinstance(items, list) or not items:
        raise LLMUnavailable("empty topic vocabulary")
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "").strip()
        if not word:
            continue
        cleaned.append({
            "word": word[:80],
            "translation": str(item.get("translation") or "").strip()[:200],
            "why": str(item.get("why") or "").strip()[:200],
        })
    if not cleaned:
        raise LLMUnavailable("no usable topic vocabulary")
    return cleaned


def ai_anki_card(conn, user, text: str, translation: str, pos: str | None = None) -> dict[str, Any]:
    payload = prompts.anki_card_user_prompt(text, translation, pos)
    result = _run_cached(conn, user, "anki_card", payload, prompts.ANKI_CARD_SYSTEM, payload)
    synonyms = result.get("synonyms")
    return {
        "mnemonic": str(result.get("mnemonic") or "").strip()[:300],
        "synonyms": [str(s).strip()[:60] for s in synonyms if str(s).strip()][:4] if isinstance(synonyms, list) else [],
        "context": str(result.get("context") or "").strip()[:300],
    }
