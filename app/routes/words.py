"""Vocabulary endpoints: word/phrase listing, status updates and on-demand
translation loading."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.core.database import db
from app.repositories import phrase_repository, word_repository
from app.schemas.user_schema import StatusPayload, TranslationPayload
from app.services.analysis import (
    load_phrase_translation_on_demand,
    load_word_translation_on_demand,
    rerun_document_analysis,
    rerun_user_analyses,
)
from app.services.auth_service import require_user
from app.services.scoring import confidence_for

router = APIRouter()


def _maybe_refresh(conn, user, payload: StatusPayload) -> None:
    if not payload.refresh_analysis:
        return
    if payload.document_id:
        rerun_document_analysis(conn, user, payload.document_id)
    else:
        rerun_user_analyses(conn, user)


@router.get("/api/words")
def words(status: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        rows = word_repository.user_words_with_word_json(conn, user["id"], status)
        phrases = phrase_repository.user_phrases_with_phrase_json(conn, user["id"], status)
        return {"words": rows, "phrases": phrases}


@router.patch("/api/user-words/{knowledge_id}")
def update_user_word(knowledge_id: str, payload: StatusPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        confidence = payload.confidence if payload.confidence is not None else confidence_for(payload.status)
        updated = word_repository.update_user_word_status(conn, knowledge_id, user["id"], payload.status, confidence)
        if not updated:
            raise HTTPException(status_code=404, detail="Слово не найдено.")
        _maybe_refresh(conn, user, payload)
        return {"user_word": updated}


@router.post("/api/user-words/{knowledge_id}/translation")
def load_user_word_translation(
    knowledge_id: str,
    payload: TranslationPayload | None = None,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        word = load_word_translation_on_demand(
            conn, user, knowledge_id, translation_ru=payload.translation_ru if payload else None
        )
        return {"word": word}


@router.patch("/api/user-phrases/{knowledge_id}")
def update_user_phrase(knowledge_id: str, payload: StatusPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        confidence = payload.confidence if payload.confidence is not None else confidence_for(payload.status)
        updated = phrase_repository.update_user_phrase_status(conn, knowledge_id, user["id"], payload.status, confidence)
        if not updated:
            raise HTTPException(status_code=404, detail="Фраза не найдена.")
        _maybe_refresh(conn, user, payload)
        return {"user_phrase": updated}


@router.post("/api/user-phrases/{knowledge_id}/translation")
def load_user_phrase_translation(
    knowledge_id: str,
    payload: TranslationPayload | None = None,
    lp_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        phrase = load_phrase_translation_on_demand(
            conn, user, knowledge_id, translation_ru=payload.translation_ru if payload else None
        )
        return {"phrase": phrase}
