"""Phrase-dictionary seed importer: parses the TSV and is idempotent."""

import importlib

from app.config import PHRASE_DICTIONARY_SEED

# app/__init__.py rebinds `app.startup` to the startup() function, so import the
# submodule explicitly.
startup = importlib.import_module("app.startup")


def test_seed_file_exists_and_well_formed():
    assert PHRASE_DICTIONARY_SEED.exists()
    lines = PHRASE_DICTIONARY_SEED.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) > 100  # real dictionary, not a stub
    for line in lines[:50]:
        parts = line.split("\t")
        assert len(parts) >= 4, line
        assert parts[0] == "en"
        assert parts[1] in {"phrasal_verb", "fixed_expression"}
        assert parts[2].strip()  # base_form present


def test_importer_skips_when_already_populated(monkeypatch):
    calls = {"insert": 0}
    monkeypatch.setattr(startup.lexicon_repository, "phrase_dictionary_count", lambda conn: 689)
    monkeypatch.setattr(startup.lexicon_repository, "bulk_insert_phrase_dictionary",
                        lambda conn, rows: calls.__setitem__("insert", calls["insert"] + 1))
    # db() context manager just needs to yield something; patch it minimally.
    import contextlib

    @contextlib.contextmanager
    def fake_db():
        yield object()

    monkeypatch.setattr(startup, "db", fake_db)
    startup.import_phrase_dictionary_if_needed()
    assert calls["insert"] == 0  # populated -> no insert


def test_importer_loads_when_empty(monkeypatch):
    captured = {}
    monkeypatch.setattr(startup.lexicon_repository, "phrase_dictionary_count", lambda conn: 0)
    monkeypatch.setattr(startup.lexicon_repository, "bulk_insert_phrase_dictionary",
                        lambda conn, rows: captured.__setitem__("rows", rows))
    import contextlib

    @contextlib.contextmanager
    def fake_db():
        yield object()

    monkeypatch.setattr(startup, "db", fake_db)
    startup.import_phrase_dictionary_if_needed()
    rows = captured["rows"]
    assert len(rows) > 100
    # tuple shape: (language, base_form, type, translation_ru)
    lang, base_form, phrase_type, _tr = rows[0]
    assert lang == "en"
    assert phrase_type in {"phrasal_verb", "fixed_expression"}
    assert base_form
