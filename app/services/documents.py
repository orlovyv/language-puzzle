"""Document-level helpers: upload validation, list summaries and the annotated
text-piece stream used by the document reading view."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.config import REQUIRE_ENGLISH_TEXT
from app.schemas.user_schema import DocumentPayload
from app.services.analysis import analyze_document, get_analysis
from app.services.language_detection import is_probably_english
from app.services.text_processing import (
    NLP,
    clean_text,
    count_text_lines,
    is_short_word,
    looks_like_binary_text,
    normalize_lemma,
)

SUPPORTED_DOCUMENT_TYPES = {"text", "srt", "book_chapter", "article"}
MAX_RAW_TEXT_LINES = 2000


def validate_document_payload(payload: DocumentPayload) -> None:
    if payload.type not in SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип документа.")
    if looks_like_binary_text(payload.raw_text):
        raise HTTPException(status_code=400, detail="Похоже, это бинарный файл. Загрузите текстовый .txt или .srt.")
    lines = count_text_lines(payload.raw_text)
    if lines > MAX_RAW_TEXT_LINES:
        raise HTTPException(status_code=400, detail=f"Текст слишком длинный: {lines} строк. Максимум {MAX_RAW_TEXT_LINES} строк.")
    # English-only corpus: block confidently non-English uploads (pasted text,
    # files and URL-imported blocks all funnel through here).
    if REQUIRE_ENGLISH_TEXT and not is_probably_english(clean_text(payload.raw_text, payload.type)):
        raise HTTPException(status_code=400, detail="Текст должен быть на английском языке. Загрузите англоязычный текст.")


def document_summary(conn, doc: dict[str, Any]) -> dict[str, Any]:
    analysis = get_analysis(conn, doc["id"])
    return {
        "id": doc["id"],
        "title": doc["title"],
        "type": doc["type"],
        "language": doc["language"],
        "created_at": str(doc["created_at"]),
        "total_words": analysis.get("total_words", 0) if analysis else 0,
        "unique_words": analysis.get("unique_words", 0) if analysis else 0,
        "coverage_percent": analysis.get("coverage_percent", 0) if analysis else 0,
    }


def build_pieces(conn, user: dict[str, Any], doc_row: dict[str, Any]) -> dict[str, Any]:
    analysis = get_analysis(conn, doc_row["id"]) or analyze_document(conn, user, doc_row)
    # For legacy SRT documents, reclean from raw_text to guarantee timecodes are removed in Text view.
    source = clean_text(doc_row["raw_text"], doc_row["type"]) if doc_row.get("type") == "srt" else (doc_row["clean_text"] or clean_text(doc_row["raw_text"], doc_row["type"]))
    words_by_lemma = {word["lemma"]: word for word in analysis["words"]}
    words_by_form = {
        form["form"]: word
        for word in analysis["words"]
        for form in word.get("forms", [])
        if form.get("form")
    }
    phrases_by_start = {phrase["start"]: phrase for phrase in analysis["phrases"]}
    doc = NLP(source)
    tokens = [token for token in doc if token.is_alpha]
    pieces = []
    cursor = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        phrase = phrases_by_start.get(token.idx)
        if phrase:
            if phrase["start"] > cursor:
                pieces.append({"type": "text", "value": source[cursor:phrase["start"]]})
            pieces.append({**phrase, "type": "phrase", "phrase_type": phrase.get("type", "phrase"), "value": source[phrase["start"]:phrase["end"]]})
            cursor = phrase["end"]
            while i + 1 < len(tokens) and tokens[i + 1].idx + len(tokens[i + 1].text) <= phrase["end"]:
                i += 1
            i += 1
            continue
        if token.idx < cursor:
            i += 1
            continue
        if token.idx > cursor:
            pieces.append({"type": "text", "value": source[cursor:token.idx]})
        lemma = normalize_lemma(token)
        token_form = token.text.lower()
        word = words_by_lemma.get(lemma) or words_by_form.get(token_form)
        short_known = is_short_word(lemma)
        pieces.append(
            {
                "type": "word",
                "value": token.text,
                "lemma": word.get("lemma", lemma) if word else lemma,
                "status": "known" if short_known else word.get("status", "unknown") if word else "unknown",
                "word_id": word.get("word_id") if word else None,
                "translation_ru": word.get("translation_ru", "") if word else "",
                "transcription": word.get("transcription", "") if word else "",
            }
        )
        cursor = token.idx + len(token.text)
        i += 1
    if cursor < len(source):
        pieces.append({"type": "text", "value": source[cursor:]})
    return {**doc_row, "created_at": str(doc_row["created_at"]), "analysis": analysis, "pieces": pieces, "token_count": len(tokens)}
