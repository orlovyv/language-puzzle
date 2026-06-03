"""Stage 1-3 AI features: card enrichment, KG source flag, premium translation."""

from datetime import datetime, timedelta, timezone

import app.services.llm.enrichment as enrich
import app.services.knowledge_graph as kg


def _future():
    return datetime.now(timezone.utc) + timedelta(days=5)


class _Cache:
    def __init__(self):
        self.store = {}

    def get(self, conn, key):
        return self.store.get(key)

    def put(self, conn, key, task, payload):
        self.store[key] = payload


def _patch_enrich(monkeypatch, response):
    cache = _Cache()
    monkeypatch.setattr(enrich, "is_configured", lambda: True)
    monkeypatch.setattr(enrich.ai_repository, "get_cached", cache.get)
    monkeypatch.setattr(enrich.ai_repository, "put_cached", cache.put)
    monkeypatch.setattr(enrich, "_check_and_count_quota", lambda conn, user: None)
    monkeypatch.setattr(enrich, "chat_json", lambda system, prompt: response)
    return cache


# ---------------------------------------------------------------------------
# Stage 2: ai_card
# ---------------------------------------------------------------------------
def test_ai_card_shape(monkeypatch):
    _patch_enrich(monkeypatch, {
        "mnemonic": "помни так",
        "synonyms": ["trip", "journey", "", "tour"],
        "context": "used in travel contexts",
    })
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    card = enrich.ai_card(None, user, "travel", "путешествие", pos="noun")
    assert card["mnemonic"] == "помни так"
    assert card["synonyms"] == ["trip", "journey", "tour"]  # empty dropped
    assert card["context"] == "used in travel contexts"


def test_ai_card_is_anki_card_alias(monkeypatch):
    _patch_enrich(monkeypatch, {"mnemonic": "m", "synonyms": [], "context": "c"})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    a = enrich.ai_card(None, user, "x", "y")
    b = enrich.ai_anki_card(None, user, "x", "y")
    assert a == b


def test_ai_card_verb_forms_meanings_examples(monkeypatch):
    _patch_enrich(monkeypatch, {
        "mnemonic": "m",
        "synonyms": ["leave"],
        "context": "c",
        "verb_forms": {"base": "go", "past": "went", "participle": "gone"},
        "other_meanings": [
            {"meaning": "ходить", "note": "о транспорте"},
            {"meaning": "становиться"},
            {"meaning": "пропадать"},
            {"meaning": "лишний"},  # 4th -> trimmed to 3
        ],
        "context_examples": [
            {"en": "Let's go home.", "ru": "Пойдём домой."},
            {"en": "The milk went bad.", "ru": "Молоко испортилось."},
        ],
    })
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    card = enrich.ai_card(None, user, "go", "идти", pos="verb")
    assert card["verb_forms"] == {"base": "go", "past": "went", "participle": "gone"}
    assert len(card["other_meanings"]) == 3  # capped
    assert card["other_meanings"][0] == {"meaning": "ходить", "note": "о транспорте"}
    assert len(card["context_examples"]) == 2
    assert card["context_examples"][0]["en"] == "Let's go home."


def test_ai_card_non_verb_drops_empty_forms(monkeypatch):
    _patch_enrich(monkeypatch, {
        "mnemonic": "m", "synonyms": [], "context": "c",
        "verb_forms": {"base": "", "past": "", "participle": ""},
        "other_meanings": [], "context_examples": [],
    })
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    card = enrich.ai_card(None, user, "table", "стол", pos="noun")
    assert card["verb_forms"] == {}  # nothing meaningful -> dropped
    assert card["other_meanings"] == []
    assert card["context_examples"] == []


def test_ai_card_examples_require_en(monkeypatch):
    _patch_enrich(monkeypatch, {
        "mnemonic": "m", "synonyms": [], "context": "c",
        "context_examples": [
            {"en": "", "ru": "без английского"},  # dropped
            {"en": "Valid one.", "ru": "Верный."},
            "garbage",  # dropped
        ],
    })
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    card = enrich.ai_card(None, user, "x", "y")
    assert len(card["context_examples"]) == 1
    assert card["context_examples"][0]["en"] == "Valid one."


# ---------------------------------------------------------------------------
# Bridge topics via AI (premium) with template fallback (free)
# ---------------------------------------------------------------------------
def test_ai_bridge_topics_shape(monkeypatch):
    _patch_enrich(monkeypatch, {"topics": [
        {"title": "Регистрация на рейс", "reason": "продолжает тему путешествий",
         "starter_words": ["check-in", "boarding", "", "gate"]},
        {"title": "", "reason": "x"},  # dropped
    ]})
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    topics = enrich.ai_bridge_topics(None, user, "travel", ["airport", "ticket"])
    assert len(topics) == 1
    assert topics[0]["title"] == "Регистрация на рейс"
    assert topics[0]["starter_words"] == ["check-in", "boarding", "gate"]  # empty dropped


def test_kg_bridge_topics_uses_ai_for_premium(monkeypatch):
    monkeypatch.setattr(
        kg.enrichment, "ai_bridge_topics",
        lambda conn, user, topic, related: [
            {"title": "Заказ еды в кафе", "reason": "смежная ситуация", "starter_words": ["menu", "order"]},
        ],
    )
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    ranked = [{"word": "food", "pos": "noun"}, {"word": "eat", "pos": "verb"}]
    bridges = kg.kg_build_bridge_topics(None, user, "restaurant", ranked)
    assert bridges[0]["bridge_topic"] == "Заказ еды в кафе"
    assert bridges[0]["reason"] == "смежная ситуация"
    assert bridges[0]["starter_words"] == ["menu", "order"]


def test_kg_bridge_topics_template_for_free():
    user = {"id": "u1", "plan": "free"}
    ranked = [{"word": "food", "pos": "noun"}, {"word": "eat", "pos": "verb"}]
    bridges = kg.kg_build_bridge_topics(None, user, "restaurant", ranked)
    # template path: non-empty, generic "<word> situations" style, no reason
    assert bridges
    assert all(b["reason"] == "" for b in bridges)


def test_kg_bridge_topics_ai_failure_falls_back(monkeypatch):
    def boom(conn, user, topic, related):
        raise kg.LLMUnavailable("down")

    monkeypatch.setattr(kg.enrichment, "ai_bridge_topics", boom)
    user = {"id": "u1", "plan": "premium", "premium_until": _future()}
    ranked = [{"word": "food", "pos": "noun"}]
    bridges = kg.kg_build_bridge_topics(None, user, "restaurant", ranked)
    assert bridges  # fell back to template
