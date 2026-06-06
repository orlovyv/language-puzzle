"""Document upload, listing, reading and deletion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.config import USE_URL_IMPORT
from app.core.database import db
from app.repositories import document_repository, word_repository
from app.schemas.user_schema import DocumentPayload, ExtractUrlPayload
from app.services.analysis import analyze_document
from app.services.auth_service import require_user
from app.services.documents import build_pieces, document_summary, validate_document_payload
from app.services.text_processing import clean_text
from app.services.url_extraction import extract_from_url
from app.utils.security import token_id

router = APIRouter()


@router.get("/api/dashboard")
def dashboard(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        docs = document_repository.user_documents(conn, user["id"])
        summaries = [document_summary(conn, doc) for doc in docs]
        words = word_repository.user_words(conn, user["id"])
        avg = round(sum(doc["coverage_percent"] for doc in summaries) / len(summaries)) if summaries else 0
        return {
            "documents": summaries,
            "stats": {
                "documents_count": len(summaries),
                "vocabulary_count": len(words),
                "learning_words": sum(1 for w in words if w["status"] == "learning"),
                "average_coverage": avg,
                "second_text_uploaded": len(summaries) >= 2,
            },
        }


@router.get("/api/documents")
def documents(lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        docs = document_repository.user_documents(conn, user["id"])
        return {"documents": [document_summary(conn, doc) for doc in docs]}


@router.post("/api/documents")
def create_document(payload: DocumentPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        validate_document_payload(payload)
        clean = clean_text(payload.raw_text, payload.type)
        doc = document_repository.insert_document(
            conn, token_id("d"), user["id"], payload.title, payload.type, payload.language, payload.raw_text, clean
        )
        analysis = analyze_document(conn, user, doc)
        return {"document": document_summary(conn, doc), "analysis": analysis}


@router.post("/api/documents/extract-url")
def extract_url(payload: ExtractUrlPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        require_user(conn, lp_session, authorization)
        if not USE_URL_IMPORT:
            raise HTTPException(status_code=403, detail="Импорт из ссылки отключён.")
        return extract_from_url(payload.url)


@router.get("/api/documents/{document_id}")
def get_document(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = document_repository.find_document(conn, document_id, user["id"])
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        return {"document": build_pieces(conn, user, doc)}


@router.delete("/api/documents/{document_id}")
def delete_document(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        document_repository.delete_document(conn, document_id, user["id"])
        return {"ok": True}
