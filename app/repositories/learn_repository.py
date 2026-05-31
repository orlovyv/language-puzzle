"""SQL access for the ``learn_blocks`` table."""

from __future__ import annotations

import json
from typing import Any

from app.core.database import execute, query_all, query_one


def user_learn_blocks(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select * from learn_blocks where user_id=%s order by created_at asc, id asc",
        (user_id,),
    )


def find_learn_block(conn, block_id: str, user_id: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "select * from learn_blocks where id=%s and user_id=%s",
        (block_id, user_id),
    )


def find_learn_blocks(conn, user_id: str, block_ids: list[str]) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select * from learn_blocks where user_id=%s and id = any(%s) order by created_at asc, id asc",
        (user_id, block_ids),
    )


def insert_learn_block(
    conn,
    block_id: str,
    user_id: str,
    title: str,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into learn_blocks (id, user_id, title, payload)
        values (%s, %s, %s, %s)
        returning *
        """,
        (block_id, user_id, title, json.dumps({"units": units})),
    )


def update_learn_block_filter(
    conn,
    block_id: str,
    user_id: str,
    frequency_filter: str,
) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update learn_blocks set frequency_filter=%s where id=%s and user_id=%s returning *",
        (frequency_filter, block_id, user_id),
    )


def delete_learn_block(conn, block_id: str, user_id: str) -> None:
    execute(conn, "delete from learn_blocks where id=%s and user_id=%s", (block_id, user_id))


def delete_learn_blocks(conn, user_id: str, block_ids: list[str]) -> None:
    execute(conn, "delete from learn_blocks where user_id=%s and id = any(%s)", (user_id, block_ids))
