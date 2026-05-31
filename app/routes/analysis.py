"""Document analysis endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.core.database import db
from app.repositories import document_repository
from app.schemas.user_schema import AnalyzePayload
from app.services.analysis import analyze_document, get_analysis
from app.services.auth_service import require_user

router = APIRouter()


@router.get("/api/documents/{document_id}/analysis")
def get_document_analysis(document_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = document_repository.find_document(conn, document_id, user["id"])
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        analysis = get_analysis(conn, document_id) or analyze_document(conn, user, doc)
        return {"analysis": analysis}


@router.post("/api/documents/{document_id}/analyze")
def post_document_analysis(document_id: str, payload: AnalyzePayload | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        doc = document_repository.find_document(conn, document_id, user["id"])
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        return {"analysis": analyze_document(conn, user, doc, refresh_important=bool(payload and payload.refresh_important))}
