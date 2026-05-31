from app.services.text_processing import clean_text, is_short_word, kg_normalize_phrase


def test_clean_text_strips_srt_timecodes_and_indices():
    raw = "1\n00:00:01,000 --> 00:00:04,000\nHello there.\n\n2\n00:00:05,000 --> 00:00:06,000\nGeneral Kenobi."
    cleaned = clean_text(raw, "srt")
    assert "-->" not in cleaned
    assert "Hello there." in cleaned
    assert "General Kenobi." in cleaned
    # bare subtitle index numbers should be gone
    assert "\n1\n" not in f"\n{cleaned}\n"


def test_clean_text_fixes_ocr_artifacts():
    assert "All" in clean_text("AII good", "text")


def test_is_short_word():
    assert is_short_word("a") is True
    assert is_short_word("I") is True
    assert is_short_word("cat") is False


def test_kg_normalize_phrase():
    assert kg_normalize_phrase("Hello,  World!!") == "hello world"
    assert kg_normalize_phrase("  multiple   spaces ") == "multiple spaces"
