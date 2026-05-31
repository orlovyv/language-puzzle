from datetime import datetime, timedelta, timezone

import app.services.llm.enrichment as enrich
from app.services.llm.client import LLMUnavailable


def _future():
    return datetime.now(timezone.utc) + timedelta(days=5)


def _past():
    return datetime.now(timezone.utc) - timedelta(days=1)


# ---------------------------------------------------------------------------
# premium detection
# ---------------------------------------------------------------------------
def test_is_premium_variants():
    assert enrich._is_premium(None) is False
    assert enrich._is_premium({"plan": "free"}) is False
    assert enrich._is_premium({"plan": "premium", "premium_until": _future()}) is True
    assert enrich._is_premium({"plan": "premium", "premium_until": _past()}) is False
    # no expiry => active
    assert enrich._is_premium({"plan": "premium", "premium_until": None}) is True
    # iso string is parsed
    assert enrich._is_premium({"plan": "premium", "premium_until": _future().isoformat()}) is True


# ---------------------------------------------------------------------------
# enrichment with stubbed cache/client/quota
# ---------------------------------------------------------------------------
class FakeCache:
    def __init__(self):
        self.store = {}

    def get_cached(self, conn, key):
        return self.store.get(key)

    def put_cached(self, conn, key, task, payload):
        self.store[key] = payload


def _patch(monkeypatch, *, configured=True, response=None, cache=None):
    cache = cache or FakeCache()
    monkeypatch.setattr(enrich, "is_configured", lambda: configured)
    monkeypatch.setattr(enrich.ai_repository, "get_cached", cache.get_cached)
    monkeypatch.setattr(enrich.ai_repository, "put_cached", cache.put_cached)
    monkeypatch.setattr(enrich, "_check_and_count_quota", lambda conn, user: None)
    if response is not None:
        monkeypatch.setattr(enrich, "chat_json", lambda system, prompt: response)
    return cache


def test_ai_translate_returns_value(monkeypatch):
    _patch(monkeypatch, response={"translation": "путешествие"})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    assert enrich.ai_translate(None, user, "travel", "noun") == "путешествие"


def test_ai_translate_caches(monkeypatch):
    cache = _patch(monkeypatch, response={"translation": "путешествие"})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    enrich.ai_translate(None, user, "travel", "noun")
    # second call must hit cache: break the client to prove it's not called
    monkeypatch.setattr(enrich, "chat_json", lambda s, p: (_ for _ in ()).throw(AssertionError("should be cached")))
    assert enrich.ai_translate(None, user, "travel", "noun") == "путешествие"
    assert len(cache.store) == 1


def test_ai_example_shape(monkeypatch):
    _patch(monkeypatch, response={"en": "I love to travel.", "ru": "Я люблю путешествовать."})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    result = enrich.ai_example(None, user, "travel")
    assert result["en"] == "I love to travel."
    assert result["ru"] == "Я люблю путешествовать."


def test_ai_topic_vocabulary_filters(monkeypatch):
    _patch(monkeypatch, response={"items": [
        {"word": "boarding pass", "translation": "посадочный талон", "why": "аэропорт"},
        {"word": "", "translation": "x"},  # dropped
        "garbage",  # dropped
    ]})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    items = enrich.ai_topic_vocabulary(None, user, "airport", ["travel"])
    assert len(items) == 1
    assert items[0]["word"] == "boarding pass"


def test_unconfigured_raises(monkeypatch):
    _patch(monkeypatch, configured=False)
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    try:
        enrich.ai_translate(None, user, "travel")
        assert False, "expected LLMUnavailable"
    except LLMUnavailable:
        pass


def test_empty_translation_raises(monkeypatch):
    _patch(monkeypatch, response={"translation": "  "})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    try:
        enrich.ai_translate(None, user, "travel")
        assert False, "expected LLMUnavailable"
    except LLMUnavailable:
        pass
