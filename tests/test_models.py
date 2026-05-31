from app.models.document import DocumentSummary
from app.models.user import PublicUser


def test_public_user_validates_row_and_ignores_extra():
    row = {
        "id": "u1",
        "email": "a@b.c",
        "native_language": "ru",
        "target_language": "en",
        "created_at": "2026-01-01T00:00:00+00:00",
        "password_hash": "should-be-ignored",
    }
    user = PublicUser.model_validate(row)
    assert user.email == "a@b.c"
    assert user.tts_enabled is True
    assert "password_hash" not in user.model_dump()


def test_document_summary_defaults():
    summary = DocumentSummary.model_validate(
        {"id": "d1", "title": "t", "type": "text", "language": "en", "created_at": "2026-01-01"}
    )
    assert summary.coverage_percent == 0
