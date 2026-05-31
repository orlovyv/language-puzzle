"""Learn blocks, Anki export and spaced-review endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Cookie, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.core.database import db
from app.repositories import analysis_repository, learn_repository, word_repository
from app.schemas.user_schema import (
    LearnBlockPayload,
    LearnBlockUpdatePayload,
    LearnMergePayload,
    ReviewPayload,
)
from app.services.analysis import rerun_user_analyses
from app.services.auth_service import require_user
from app.services.learn import (
    VALID_FREQUENCY_FILTERS,
    anki_filename,
    build_learn_block_anki_text,
    filter_learn_units_for_frequency,
    normalize_learn_units,
    public_learn_block,
)
from app.utils.security import token_id

router = APIRouter()


@router.get("/api/learn")
def learn(document_id: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        rows = learn_repository.user_learn_blocks(conn, user["id"])
        return {"blocks": [public_learn_block(conn, user, row) for row in rows]}


@router.post("/api/learn/blocks")
def create_learn_block(payload: LearnBlockPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        units = normalize_learn_units(payload.units)
        if not units:
            raise HTTPException(status_code=400, detail="Нет новых слов для блока Learn.")
        title = re.sub(r"\s+", " ", (payload.title or "Learn block").strip())[:160] or "Learn block"
        row = learn_repository.insert_learn_block(conn, token_id("lb"), user["id"], title, units)
        return {"block": public_learn_block(conn, user, row)}


@router.patch("/api/learn/blocks/{block_id}")
def update_learn_block(block_id: str, payload: LearnBlockUpdatePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        value = payload.frequency_filter or "all"
        if value not in VALID_FREQUENCY_FILTERS:
            raise HTTPException(status_code=400, detail="Неверный фильтр частотности.")
        row = learn_repository.update_learn_block_filter(conn, block_id, user["id"], value)
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден.")
        return {"block": public_learn_block(conn, user, row)}


@router.delete("/api/learn/blocks/{block_id}")
def delete_learn_block(block_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        learn_repository.delete_learn_block(conn, block_id, user["id"])
        return {"ok": True}


@router.get("/api/learn/blocks/{block_id}/anki")
def export_learn_block_anki(block_id: str, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        row = learn_repository.find_learn_block(conn, block_id, user["id"])
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден.")
        block = public_learn_block(conn, user, row)
        export_units = [
            unit
            for unit in filter_learn_units_for_frequency(block.get("units") or [], block.get("frequency_filter") or "all")
            if unit.get("status") not in {"known", "ignored"}
        ]
        if not export_units:
            raise HTTPException(status_code=400, detail="В блоке нет неизученных слов для ANKI.")
        text = build_learn_block_anki_text(block)
        filename = anki_filename(block["title"])
        return StreamingResponse(
            iter([text.encode("utf-8-sig")]),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/api/learn/blocks/merge")
def merge_learn_blocks(payload: LearnMergePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        block_ids = [item for item in payload.block_ids if item]
        if len(set(block_ids)) < 2:
            raise HTTPException(status_code=400, detail="Выберите минимум два блока.")
        rows = learn_repository.find_learn_blocks(conn, user["id"], block_ids)
        if len(rows) < 2:
            raise HTTPException(status_code=404, detail="Блоки не найдены.")
        units = normalize_learn_units([
            unit
            for row in rows
            for unit in ((row.get("payload") or {}).get("units") or [])
        ])
        title = ". ".join([row["title"] for row in rows if row.get("title")])[:220] or "Merged Learn block"
        learn_repository.delete_learn_blocks(conn, user["id"], [row["id"] for row in rows])
        row = learn_repository.insert_learn_block(conn, token_id("lb"), user["id"], title, units)
        return {"block": public_learn_block(conn, user, row)}


@router.post("/api/learn/review")
def review(payload: ReviewPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        status = "known" if payload.grade >= 4 else "learning" if payload.grade >= 2 else "unknown"
        confidence = max(0, min(1, payload.grade / 4))
        updated = word_repository.update_user_word_status(conn, payload.user_word_id, user["id"], status, confidence)
        if not updated:
            raise HTTPException(status_code=404, detail="Карточка не найдена.")
        analysis_repository.insert_review(conn, token_id("r"), user["id"], updated["word_id"], payload.grade)
        rerun_user_analyses(conn, user)
        return {"user_word": updated}
