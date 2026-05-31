"""Static single-page-app fallback. Must be registered after all API routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import PUBLIC_DIR

router = APIRouter()


@router.get("/{full_path:path}")
def spa(full_path: str):
    target = PUBLIC_DIR / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(PUBLIC_DIR / "index.html")
