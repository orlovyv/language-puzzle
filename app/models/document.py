"""Domain models for documents."""

from __future__ import annotations

from pydantic import BaseModel


class DocumentSummary(BaseModel):
    """List/dashboard projection of a document with its coverage stats."""

    id: str
    title: str
    type: str
    language: str
    created_at: str
    total_words: int = 0
    unique_words: int = 0
    coverage_percent: int = 0
