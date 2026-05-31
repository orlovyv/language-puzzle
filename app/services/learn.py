"""Learn blocks: normalising saved units, refreshing them against current
knowledge, frequency filtering and Anki deck export."""

from __future__ import annotations

import csv
import html
import io
import re
from typing import Any

from app.repositories import phrase_repository, word_repository
from app.services.translation import anki_example_translation
from app.services.llm import enrichment
from app.services.llm.client import LLMUnavailable

VALID_FREQUENCY_FILTERS = {"20-80", "50-50", "all"}


# ---------------------------------------------------------------------------
# unit normalisation
# ---------------------------------------------------------------------------
def learn_unit_key(unit: dict[str, Any]) -> str:
    kind = "phrase" if unit.get("kind") == "phrase" else "word"
    identity = unit.get("knowledge_id") or unit.get("id") or unit.get("text") or unit.get("label")
    return f"{kind}:{identity}"


def learn_frequency_rank(unit: dict[str, Any]) -> int:
    try:
        return int(unit.get("frequency_rank") or 999999)
    except (TypeError, ValueError):
        return 999999


def normalize_learn_unit(raw: dict[str, Any]) -> dict[str, Any] | None:
    kind = "phrase" if raw.get("kind") == "phrase" else "word"
    text = re.sub(r"\s+", " ", str(raw.get("text") or raw.get("label") or raw.get("base_form") or "").strip())
    knowledge_id = str(raw.get("knowledge_id") or raw.get("user_phrase_id") or raw.get("user_word_id") or "").strip()
    if not text or not knowledge_id:
        return None
    status = str(raw.get("status") or "unknown")
    try:
        count = int(raw.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    try:
        score = float(raw.get("score") or raw.get("priority") or 0)
    except (TypeError, ValueError):
        score = 0
    return {
        "id": str(raw.get("id") or raw.get("word_id") or raw.get("phrase_id") or knowledge_id),
        "knowledge_id": knowledge_id,
        "kind": kind,
        "text": text[:120],
        "base_form": str(raw.get("base_form") or text)[:120] if kind == "phrase" else "",
        "translation_ru": str(raw.get("translation_ru") or "")[:500],
        "transcription": str(raw.get("transcription") or "")[:120],
        "part_of_speech": str(raw.get("part_of_speech") or ("phrase" if kind == "phrase" else "word"))[:40],
        "status": status,
        "example": str(raw.get("example") or "")[:500],
        "count": count,
        "frequency_rank": learn_frequency_rank(raw),
        "score": score,
    }


def normalize_learn_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for raw in units:
        unit = normalize_learn_unit(raw or {})
        if not unit:
            continue
        key = learn_unit_key(unit)
        stored = by_key.get(key)
        if not stored:
            by_key[key] = unit
            continue
        stored["count"] = max(int(stored.get("count") or 1), int(unit.get("count") or 1))
        stored["score"] = max(float(stored.get("score") or 0), float(unit.get("score") or 0))
        stored["frequency_rank"] = min(learn_frequency_rank(stored), learn_frequency_rank(unit))
    return sorted(by_key.values(), key=lambda item: (learn_frequency_rank(item), item["text"].lower()))


def refresh_learn_units_from_knowledge(conn, user: dict[str, Any], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    word_rows = {row["id"]: row for row in word_repository.user_words_with_word_rows(conn, user["id"])}
    phrase_rows = {row["id"]: row for row in phrase_repository.user_phrases_with_phrase_rows(conn, user["id"])}
    refreshed = []
    for unit in units:
        item = dict(unit)
        knowledge_id = item.get("knowledge_id")
        if item.get("kind") == "phrase":
            row = phrase_rows.get(knowledge_id)
            if row:
                item.update(
                    {
                        "id": row["phrase_id"],
                        "text": row["base_form"] or row["phrase"],
                        "base_form": row["base_form"] or row["phrase"],
                        "translation_ru": row["translation_ru"],
                        "part_of_speech": row["type"] or "phrase",
                        "status": row["status"],
                    }
                )
        else:
            row = word_rows.get(knowledge_id)
            if row:
                item.update(
                    {
                        "id": row["word_id"],
                        "text": row["lemma"],
                        "translation_ru": row["translation_ru"],
                        "transcription": row.get("transcription", ""),
                        "part_of_speech": row["part_of_speech"],
                        "frequency_rank": row["frequency_rank"],
                        "status": row["status"],
                    }
                )
        refreshed.append(item)
    return refreshed


def public_learn_block(conn, user: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    units = normalize_learn_units(refresh_learn_units_from_knowledge(conn, user, payload.get("units") or []))
    frequency_filter = row.get("frequency_filter") or "all"
    if frequency_filter not in VALID_FREQUENCY_FILTERS:
        frequency_filter = "all"
    return {
        "id": row["id"],
        "title": row["title"],
        "frequency_filter": frequency_filter,
        "units": units,
        "created_at": str(row["created_at"]),
    }


def filter_learn_units_for_frequency(units: list[dict[str, Any]], frequency_filter: str) -> list[dict[str, Any]]:
    sorted_units = sorted(units, key=lambda item: (learn_frequency_rank(item), str(item.get("text") or "").lower()))
    if frequency_filter == "all" or not sorted_units:
        return sorted_units
    if frequency_filter == "20-80":
        return sorted_units[:max(1, int(len(sorted_units) * 0.2 + 0.999999))]
    if frequency_filter == "50-50":
        return sorted_units[:max(1, int(len(sorted_units) * 0.5 + 0.999999))]
    return sorted_units


# ---------------------------------------------------------------------------
# Anki export
# ---------------------------------------------------------------------------
def clean_export_translation(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text == "перевод уточняется" else text


def clean_transcription_for_export(value: Any) -> str:
    return str(value or "").replace("*", "").strip()


def anki_bold_term(example: str, term: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(example or "")).strip()
    if not cleaned:
        return ""
    escaped = html.escape(cleaned)
    words = [re.escape(part) for part in re.sub(r"[^A-Za-z0-9'\s-]", " ", term or "").split() if part]
    if not words:
        return escaped
    pattern = r"\b" + r"\s+".join(words) + r"\b"
    return re.sub(pattern, lambda match: f"<b>{match.group(0)}</b>", escaped, flags=re.I)


def anki_filename(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title or "learn_block").strip("_")
    return (slug or "learn_block")[:80] + "_anki.txt"


def _ai_anki_card(conn, user, text: str, translation: str, pos: str | None) -> dict[str, Any] | None:
    """Premium AI card enrichment, or None if unavailable."""
    if conn is None or user is None:
        return None
    try:
        return enrichment.ai_anki_card(conn, user, text, translation, pos=pos)
    except LLMUnavailable:
        return None


def build_learn_block_anki_text(block: dict[str, Any], conn=None, user=None) -> str:
    units = [
        unit
        for unit in filter_learn_units_for_frequency(block.get("units") or [], block.get("frequency_filter") or "all")
        if unit.get("status") not in {"known", "ignored"}
    ]
    output = io.StringIO()
    output.write("#separator:tab\n")
    output.write("#html:true\n")
    output.write("#notetype:Basic\n")
    output.write(f"#deck:{html.escape(block.get('title') or 'Learn')}\n")
    output.write("#columns:Front\tBack\n")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")

    for unit in units:
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        translation = clean_export_translation(unit.get("translation_ru")) or "Перевод не найден"
        transcription = clean_transcription_for_export(unit.get("transcription"))
        example = anki_bold_term(unit.get("example") or "", text)
        word_line = f"<span style=\"font-size:22px;font-weight:700;\"><b>{html.escape(text)}</b></span>"
        details = []
        if transcription:
            details.append(f"<span style=\"font-size:15px;color:#667085;\">/{html.escape(transcription)}/</span>")
        if example:
            details.append(f"<span style=\"font-size:16px;color:#3b4b5c;\">{example}</span>")
        tts_parts = [f"{text}."]
        if unit.get("example"):
            tts_parts.append(re.sub(r"\s+", " ", str(unit.get("example"))).strip())
        tts_text = " <break time=\"1000ms\"/> ".join([html.escape(part) for part in tts_parts if part])
        tts_line = f"[anki:tts lang=en_US]{tts_text}[/anki:tts]" if tts_text else ""
        front = "<br>".join([part for part in [word_line, *details, tts_line] if part])
        back_parts = [html.escape(translation)]
        part_of_speech = str(unit.get("part_of_speech") or "").strip()
        if part_of_speech:
            back_parts.append(f"<span style=\"color:#667085;\">{html.escape(part_of_speech)}</span>")
        example_translation = anki_example_translation(unit.get("example") or "")
        if example_translation:
            back_parts.append(f"<span style=\"color:#3b4b5c;\">Пример: {html.escape(example_translation)}</span>")
        card = _ai_anki_card(conn, user, text, clean_export_translation(unit.get("translation_ru")), part_of_speech)
        if card:
            if card.get("synonyms"):
                back_parts.append(f"<span style=\"color:#667085;\">Синонимы: {html.escape(', '.join(card['synonyms']))}</span>")
            if card.get("mnemonic"):
                back_parts.append(f"<span style=\"color:#3b4b5c;\">Мнемоника: {html.escape(card['mnemonic'])}</span>")
            if card.get("context"):
                back_parts.append(f"<span style=\"color:#3b4b5c;\">{html.escape(card['context'])}</span>")
        writer.writerow([front, "<br>".join(back_parts)])

    text = output.getvalue()
    output.close()
    return text
