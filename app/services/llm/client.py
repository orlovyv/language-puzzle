"""Thin synchronous OpenRouter client (OpenAI-compatible chat completions).

Synchronous on purpose (see memory "db-stays-sync"): the whole stack is sync and
FastAPI runs sync endpoints in a threadpool. Any failure — missing key, network,
timeout, malformed JSON — raises ``LLMUnavailable`` so callers degrade to the
free path instead of erroring the request.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from app.config import (
    LLM_MODEL,
    LLM_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    USE_AI_FEATURES,
)


class LLMUnavailable(RuntimeError):
    """Raised when the LLM cannot produce a usable response."""


def is_configured() -> bool:
    return bool(USE_AI_FEATURES and OPENROUTER_API_KEY)


def chat_json(system_prompt: str, user_prompt: str, *, model: str | None = None) -> dict[str, Any]:
    """Run a chat completion expecting a strict JSON object back.

    Returns the parsed dict. Raises ``LLMUnavailable`` on any problem.
    """
    if not is_configured():
        raise LLMUnavailable("AI features disabled or OPENROUTER_API_KEY missing")

    body = {
        "model": model or LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # OpenRouter attribution headers (optional but recommended).
        "X-Title": "Language Puzzle",
    }
    try:
        response = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise LLMUnavailable("LLM returned non-object JSON")
        return parsed
    except LLMUnavailable:
        raise
    except Exception as exc:  # network, HTTP, JSON, KeyError
        raise LLMUnavailable(str(exc)) from exc
