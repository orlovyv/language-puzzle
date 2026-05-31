"""Knowledge Graph mode endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Header

from app.core.database import db
from app.repositories import document_repository
from app.schemas.user_schema import (
    KnowledgeAnalyzePayload,
    KnowledgeBridgePayload,
    KnowledgeGoalPayload,
)
from app.services.auth_service import require_user
from app.services.knowledge_graph import (
    build_document_context_from_row,
    build_goal_context,
    build_kg_context,
    context_summary,
    document_context_id_from_kg_id,
    kg_bridge_context,
    kg_infer_topic_label,
    topic_slug,
)

router = APIRouter()


@router.get("/api/knowledge")
def knowledge(context_id: str | None = None, document_id: str | None = None, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        selected_document_id = document_id
        if not selected_document_id and context_id:
            selected_document_id = document_context_id_from_kg_id(context_id)

        if selected_document_id:
            row = document_repository.find_document_with_analysis(conn, user["id"], selected_document_id)
        else:
            row = document_repository.latest_document_with_analysis(conn, user["id"])

        document_context = build_document_context_from_row(
            conn,
            user,
            row,
            "Расширить тему выбранного текста." if selected_document_id else "Расширить тему последнего загруженного текста.",
        )
        contexts = [document_context] if document_context else []
        return {"contexts": [context_summary(item) for item in contexts], "context": document_context}


@router.post("/api/knowledge/goal")
def knowledge_goal(payload: KnowledgeGoalPayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        context, contexts = build_goal_context(conn, user, payload.goal)
        return {"contexts": contexts, "context": context}


@router.post("/api/knowledge/bridge")
def knowledge_bridge(payload: KnowledgeBridgePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        context = kg_bridge_context(
            conn,
            user,
            payload.context_id,
            payload.bridge_title,
            [],
            document_id=payload.document_id,
        )
        return {"contexts": [context], "context": context}


@router.post("/api/knowledge/analyze")
def knowledge_analyze(payload: KnowledgeAnalyzePayload, lp_session: str | None = Cookie(default=None), authorization: str | None = Header(default=None)):
    with db() as conn:
        user = require_user(conn, lp_session, authorization)
        if payload.bridge_topic:
            context = build_kg_context(
                conn,
                user,
                f"kg:{topic_slug(payload.bridge_topic)}",
                payload.bridge_topic,
                title=payload.bridge_topic,
                description="Мостовая тема из Knowledge Graph Mode.",
            )
        else:
            source = payload.text or payload.manual_topic or "Everyday English"
            context = build_kg_context(
                conn,
                user,
                f"kg:{topic_slug(payload.manual_topic or kg_infer_topic_label(source))}",
                source,
                title=payload.manual_topic or kg_infer_topic_label(source),
                description="Theme Card построена по механизму Knowledge Graph Mode.",
            )
        return {"contexts": [context], "context": context}
