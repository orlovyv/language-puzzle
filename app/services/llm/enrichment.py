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


def ai_healthcheck(conn, user: dict[str, Any] | None) -> dict[str, Any]:
    """Diagnose the AI setup: config, plan/quota, and a live test call.

    Never raises — returns a report dict so an admin can see the real cause
    (bad key, missing model, no balance, quota, ...).
    """
    today = datetime.now(timezone.utc).date()
    usage_today = None
    if conn is not None and user:
        usage_today = ai_repository.usage_today(conn, user["id"], today)
    report: dict[str, Any] = {
        "configured": is_configured(),
        "model": LLM_MODEL,
        "is_premium": _is_premium(user),
        "daily_limit": _daily_limit(user),
        "usage_today": usage_today,
        "ok": False,
        "error": None,
    }
    if not is_configured():
        report["error"] = "AI not configured (USE_AI_FEATURES off or OPENROUTER_API_KEY missing)"
        return report
    try:
        # Minimal live call — bypasses cache/quota to test the real connection.
        result = chat_json(
            'Return JSON {"ok": true}.',
            '{"ping": 1}',
        )
        report["ok"] = bool(result)
        report["sample"] = result
    except Exception as exc:  # LLMUnavailable and anything unexpected
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


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


def ai_bridge_topics(conn, user, topic: str, related_words: list[str]) -> list[dict[str, Any]]:
    payload = prompts.bridge_topics_user_prompt(topic, related_words)
    result = _run_cached(conn, user, "bridge_topics", payload, prompts.BRIDGE_TOPICS_SYSTEM, payload)
    topics = result.get("topics")
    if not isinstance(topics, list) or not topics:
        raise LLMUnavailable("empty bridge topics")
    cleaned = []
    for item in topics:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        starters = item.get("starter_words")
        cleaned.append({
            "title": title[:80],
            "reason": str(item.get("reason") or "").strip()[:200],
            "starter_words": [str(s).strip()[:40] for s in starters if str(s).strip()][:4]
            if isinstance(starters, list) else [],
        })
    if not cleaned:
        raise LLMUnavailable("no usable bridge topics")
    return cleaned[:6]


def _clean_verb_forms(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    forms = {
        "base": str(raw.get("base") or "").strip()[:60],
        "past": str(raw.get("past") or "").strip()[:60],
        "participle": str(raw.get("participle") or "").strip()[:60],
    }
    # Drop entirely if nothing meaningful was returned (non-verb).
    return forms if any(forms.values()) else {}


def _clean_other_meanings(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if isinstance(item, dict):
            meaning = str(item.get("meaning") or "").strip()
            note = str(item.get("note") or "").strip()
        else:
            meaning, note = str(item or "").strip(), ""
        if meaning:
            cleaned.append({"meaning": meaning[:200], "note": note[:200]})
    return cleaned[:3]


def _clean_context_examples(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        en = str(item.get("en") or "").strip()
        if not en:
            continue
        cleaned.append({"en": en[:300], "ru": str(item.get("ru") or "").strip()[:300]})
    return cleaned[:3]


def ai_anki_card(conn, user, text: str, translation: str, pos: str | None = None) -> dict[str, Any]:
    payload = prompts.anki_card_user_prompt(text, translation, pos)
    # task "card_v2": new schema (forms/meanings/examples); old "anki_card" cache
    # entries are ignored so cards regenerate with the richer fields.
    result = _run_cached(conn, user, "card_v2", payload, prompts.ANKI_CARD_SYSTEM, payload)
    synonyms = result.get("synonyms")
    return {
        "mnemonic": str(result.get("mnemonic") or "").strip()[:300],
        "synonyms": [str(s).strip()[:60] for s in synonyms if str(s).strip()][:4] if isinstance(synonyms, list) else [],
        "context": str(result.get("context") or "").strip()[:300],
        "verb_forms": _clean_verb_forms(result.get("verb_forms")),
        "other_meanings": _clean_other_meanings(result.get("other_meanings")),
        "context_examples": _clean_context_examples(result.get("context_examples")),
    }


# UI alias: same enriched card (mnemonic/synonyms/context), shown on demand in
# the word/phrase detail panel. Shares the cache with the Anki export.
def ai_card(conn, user, text: str, translation: str, pos: str | None = None) -> dict[str, Any]:
    return ai_anki_card(conn, user, text, translation, pos=pos)
