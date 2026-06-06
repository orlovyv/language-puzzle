"""Import article text from a web link.

``extract_from_url`` downloads a page's HTML, then:
  * uses trafilatura to extract the recommended main article text, and
  * uses BeautifulSoup to collect the largest alternative text blocks,

so the user can pick the main text or one/several alternative blocks on the
Upload screen.

Synchronous on purpose (the whole stack is sync; FastAPI runs sync endpoints in
a threadpool). Network/parse failures raise ``HTTPException`` so the route
returns a clean 400 instead of a 500.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from fastapi import HTTPException

from app.config import URL_FETCH_MAX_BYTES, URL_FETCH_TIMEOUT
from app.services.text_processing import count_text_lines

# Keep selected blocks within the document line budget (mirrors documents.py).
MAX_RAW_TEXT_LINES = 2000
# A block must be at least this many characters to be worth offering.
_MIN_BLOCK_CHARS = 200
# How many alternative blocks to return at most.
_MAX_BLOCKS = 10
_PREVIEW_CHARS = 200

_USER_AGENT = (
    "Mozilla/5.0 (compatible; LanguagePuzzle/1.0; +https://language-puzzle.com)"
)
# Block-level containers we treat as candidate text blocks.
_BLOCK_TAGS = ("article", "main", "section", "div", "li", "blockquote")
# Stripped before extraction — boilerplate that pollutes block text.
_DROP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _is_blocked_host(host: str) -> bool:
    """Best-effort SSRF guard: block localhost and private/link-local IPs."""
    host = (host or "").strip().lower().strip(".")
    if not host or host in {"localhost", "localhost.localdomain"}:
        return True
    # Resolve the hostname; if any resolved address is private/loopback, block.
    candidates = {host}
    try:
        for info in socket.getaddrinfo(host, None):
            candidates.add(info[4][0])
    except (socket.gaierror, UnicodeError, OSError):
        # Can't resolve — let the request itself fail later rather than guess.
        pass
    for value in candidates:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def _validate_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _reject("Укажите корректную ссылку http(s)://...")
    if _is_blocked_host(parsed.hostname):
        raise _reject("Эта ссылка недоступна для загрузки.")
    return parsed.geturl()


def _fetch_html(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=URL_FETCH_TIMEOUT,
            stream=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*"},
        )
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > URL_FETCH_MAX_BYTES:
                break
        response.close()
        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")
    except requests.RequestException:
        raise _reject("Не удалось загрузить ссылку. Проверьте адрес и попробуйте снова.")


def _trim_to_line_budget(text: str) -> str:
    """Cap a block at MAX_RAW_TEXT_LINES so a selected block fits the document."""
    if count_text_lines(text) <= MAX_RAW_TEXT_LINES:
        return text
    lines = re.split(r"\r\n|\r|\n", text)[:MAX_RAW_TEXT_LINES]
    return "\n".join(lines).strip()


def _block_text(node) -> str:
    """Readable text of a container, paragraphs separated by blank lines."""
    text = node.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _collect_blocks(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()

    candidates: list[str] = []
    for node in soup.find_all(_BLOCK_TAGS):
        text = _block_text(node)
        if len(text) >= _MIN_BLOCK_CHARS:
            candidates.append(text)

    # Largest first, then drop blocks already contained in a bigger kept block
    # (containers nest, so a parent <div> duplicates its child paragraphs).
    candidates.sort(key=len, reverse=True)
    kept: list[str] = []
    for text in candidates:
        if any(text in bigger for bigger in kept):
            continue
        kept.append(text)
        if len(kept) >= _MAX_BLOCKS:
            break
    return kept


def _preview(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:_PREVIEW_CHARS] + ("…" if len(flat) > _PREVIEW_CHARS else "")


def extract_from_url(url: str) -> dict[str, Any]:
    """Return {"url", "main_text", "blocks"} for the Upload URL-import UI."""
    clean_url = _validate_url(url)
    html = _fetch_html(clean_url)

    main_text = ""
    extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
    if extracted:
        main_text = _trim_to_line_budget(extracted.strip())

    blocks = []
    for index, text in enumerate(_collect_blocks(html)):
        trimmed = _trim_to_line_budget(text)
        blocks.append({
            "id": index,
            "chars": len(trimmed),
            "preview": _preview(trimmed),
            "text": trimmed,
        })

    return {"url": clean_url, "main_text": main_text, "blocks": blocks}
