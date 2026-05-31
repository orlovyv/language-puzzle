"""Minimal forward-only SQL migration runner.

Each ``*.sql`` file in :data:`app.config.MIGRATIONS_DIR` is applied once, in
filename order, and recorded in ``schema_migrations``. Files are expected to be
idempotent (``IF NOT EXISTS`` / ``ON CONFLICT``) so re-running against a legacy
database created by the old in-code schema is safe.
"""

from __future__ import annotations

from app.config import MIGRATIONS_DIR
from app.core.database import db, query_all


def _ensure_migrations_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                filename text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )


def _applied_filenames(conn) -> set[str]:
    return {row["filename"] for row in query_all(conn, "select filename from schema_migrations")}


def run_migrations() -> list[str]:
    """Apply pending migrations and return the filenames that were run."""
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(path for path in MIGRATIONS_DIR.glob("*.sql"))
    applied: list[str] = []
    with db() as conn:
        _ensure_migrations_table(conn)
        done = _applied_filenames(conn)
        for path in files:
            if path.name in done:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "insert into schema_migrations (filename) values (%s)",
                    (path.name,),
                )
            applied.append(path.name)
    return applied
