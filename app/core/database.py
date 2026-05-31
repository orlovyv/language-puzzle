"""Database access layer.

Owns the PostgreSQL connection lifecycle and the small query helpers used across
the app. Connections are served from a process-wide :class:`psycopg_pool.ConnectionPool`
so requests reuse warm connections instead of opening a fresh TCP/auth handshake every
time (the previous ``psycopg.connect`` per request was the main DB inefficiency).

If ``psycopg_pool`` is unavailable the module transparently falls back to one
connection per call, so the app keeps working in minimal environments.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

import psycopg
from fastapi import HTTPException

from app.config import DATABASE_URL, DB_POOL_MAX_SIZE, DB_POOL_MIN_SIZE

try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - pool is optional
    ConnectionPool = None  # type: ignore[assignment]


_POOL: "ConnectionPool | None" = None
_POOL_LOCK = Lock()


def _build_pool() -> "ConnectionPool | None":
    if ConnectionPool is None:
        return None
    return ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=DB_POOL_MIN_SIZE,
        max_size=DB_POOL_MAX_SIZE,
        open=False,
        kwargs={"autocommit": False},
    )


def open_pool() -> None:
    """Create and open the shared pool. Safe to call once the database exists."""
    global _POOL
    if ConnectionPool is None:
        return
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = _build_pool()
        if _POOL is not None:
            _POOL.open()


def close_pool() -> None:
    """Close the shared pool on application shutdown."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
            _POOL = None


@contextmanager
def db() -> Iterator[psycopg.Connection]:
    """Yield a transactional connection, committing on success.

    Raises a 503 ``HTTPException`` when PostgreSQL is unreachable, preserving the
    behaviour the routes rely on.
    """
    try:
        if ConnectionPool is not None:
            if _POOL is None:
                open_pool()
            with _POOL.connection() as conn:  # type: ignore[union-attr]
                yield conn
        else:
            with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
                yield conn
                conn.commit()
    except psycopg.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "PostgreSQL недоступен. Проверь DATABASE_URL. "
                f"Деталь: {str(exc).splitlines()[0]}"
            ),
        ) from exc


def row_to_dict(row: tuple, columns: list[str]) -> dict[str, Any]:
    return dict(zip(columns, row))


def query_one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        return row_to_dict(row, [desc.name for desc in cur.description])


def query_all(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [desc.name for desc in cur.description]
        return [row_to_dict(row, cols) for row in rows]


def execute(conn, sql: str, params: tuple = ()) -> None:
    """Run a statement that returns no rows (DELETE/UPDATE without RETURNING)."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
