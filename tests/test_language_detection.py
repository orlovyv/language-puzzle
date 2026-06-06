"""English-language guard used to keep the corpus English-only."""

import pytest
from fastapi import HTTPException

from app.schemas.user_schema import DocumentPayload
from app.services.documents import validate_document_payload
from app.services.language_detection import is_probably_english


def test_english_text_passes():
    text = (
        "This is a clearly English paragraph about travelling and learning new "
        "vocabulary every day. The system highlights unknown words and phrases."
    )
    assert is_probably_english(text) is True


def test_russian_text_is_rejected():
    text = (
        "Это явно русский текст про путешествия и изучение новых слов каждый "
        "день. Сервис подсвечивает незнакомые слова и устойчивые выражения."
    )
    assert is_probably_english(text) is False


def test_short_text_is_lenient():
    # Too short to detect reliably -> never block.
    assert is_probably_english("Привет") is True
    assert is_probably_english("") is True


def test_validate_document_payload_blocks_non_english():
    russian = (
        "Это длинный русский текст, который не должен загружаться в сервис, "
        "потому что корпус только англоязычный, проверяем срабатывание ошибки."
    )
    with pytest.raises(HTTPException) as exc:
        validate_document_payload(DocumentPayload(title="t", type="text", raw_text=russian))
    assert exc.value.status_code == 400


def test_validate_document_payload_allows_english():
    english = (
        "This is a perfectly valid English text that should be accepted by the "
        "upload validation without raising any error about the language."
    )
    # Should not raise.
    validate_document_payload(DocumentPayload(title="t", type="text", raw_text=english))
