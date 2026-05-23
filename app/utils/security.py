from __future__ import annotations

import asyncio
import hashlib
import secrets
from threading import Thread
from typing import Any

from app.config import APP_SECRET


def run_coroutine_from_sync(coro_factory) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro_factory())
        except Exception as exc:
            result["error"] = exc

    thread = Thread(target=runner)
    thread.start()
    thread.join()

    if "error" in result:
        raise result["error"]
    return result.get("value")


def hash_password(password: str) -> str:
    return hashlib.sha256(f"{APP_SECRET}:{password}".encode("utf-8")).hexdigest()


def token_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"
