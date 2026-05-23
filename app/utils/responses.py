from __future__ import annotations

from fastapi.responses import JSONResponse


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)
