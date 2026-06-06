"""Lightweight English-language detection for uploaded/pasted text.

Used to keep the corpus English-only: ``validate_document_payload`` blocks
documents whose cleaned text is confidently detected as another language.

Deliberately lenient — only a *confident* non-English result blocks an upload.
Very short text or a detector failure passes, so valid short English snippets
are never rejected by a flaky detector.
"""

from __future__ import annotations

try:
    from langdetect import DetectorFactory, LangDetectException, detect
    # Deterministic results across runs (langdetect is randomised by default).
    DetectorFactory.seed = 0
    _AVAILABLE = True
except ImportError:  # pragma: no cover - dependency optional at runtime
    _AVAILABLE = False

# Below this length langdetect is unreliable, so we don't block.
_MIN_CHARS = 40
# Only inspect the start of long texts — enough signal, far cheaper.
_SAMPLE_CHARS = 3000


def is_probably_english(text: str) -> bool:
    """True unless the text is confidently detected as a non-English language."""
    sample = (text or "").strip()
    if not _AVAILABLE or len(sample) < _MIN_CHARS:
        return True
    try:
        return detect(sample[:_SAMPLE_CHARS]) == "en"
    except LangDetectException:
        # No detectable language features — don't block.
        return True
