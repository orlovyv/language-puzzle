from app.services.learn import (
    anki_filename,
    filter_learn_units_for_frequency,
    learn_unit_key,
    normalize_learn_unit,
    normalize_learn_units,
)


def test_normalize_learn_unit_requires_text_and_knowledge_id():
    assert normalize_learn_unit({"kind": "word", "text": "cat"}) is None
    assert normalize_learn_unit({"kind": "word", "knowledge_id": "uw1"}) is None
    unit = normalize_learn_unit({"kind": "word", "text": "cat", "knowledge_id": "uw1"})
    assert unit is not None
    assert unit["text"] == "cat" and unit["kind"] == "word"


def test_normalize_learn_units_merges_duplicates():
    units = normalize_learn_units([
        {"kind": "word", "text": "cat", "knowledge_id": "uw1", "count": 1, "score": 5, "frequency_rank": 100},
        {"kind": "word", "text": "cat", "knowledge_id": "uw1", "count": 3, "score": 2, "frequency_rank": 50},
    ])
    assert len(units) == 1
    assert units[0]["count"] == 3
    assert units[0]["score"] == 5
    assert units[0]["frequency_rank"] == 50


def test_learn_unit_key_distinguishes_kind():
    word = {"kind": "word", "knowledge_id": "k1"}
    phrase = {"kind": "phrase", "knowledge_id": "k1"}
    assert learn_unit_key(word) != learn_unit_key(phrase)


def test_filter_learn_units_for_frequency():
    units = [
        {"text": f"w{i}", "knowledge_id": f"uw{i}", "frequency_rank": i}
        for i in range(1, 11)
    ]
    assert len(filter_learn_units_for_frequency(units, "all")) == 10
    assert len(filter_learn_units_for_frequency(units, "20-80")) == 2
    assert len(filter_learn_units_for_frequency(units, "50-50")) == 5


def test_anki_filename_sanitised():
    assert anki_filename("My Block!!") == "My_Block_anki.txt"
    assert anki_filename("") == "learn_block_anki.txt"
