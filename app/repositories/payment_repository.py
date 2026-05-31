"""SQL access for the ``payments`` ledger."""

from __future__ import annotations

from typing import Any

from app.core.database import execute, query_all, query_one


def insert_payment(
    conn,
    payment_id: str,
    user_id: str,
    yookassa_id: str | None,
    amount: float,
    currency: str,
    status: str,
    period_days: int,
) -> dict[str, Any]:
    return query_one(
        conn,
        """
        insert into payments (id, user_id, yookassa_id, amount, currency, status, period_days)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning *
        """,
        (payment_id, user_id, yookassa_id, amount, currency, status, period_days),
    )


def find_by_yookassa_id(conn, yookassa_id: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from payments where yookassa_id=%s", (yookassa_id,))


def update_status(conn, yookassa_id: str, status: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update payments set status=%s, updated_at=now() where yookassa_id=%s returning *",
        (status, yookassa_id),
    )


def user_payments(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select * from payments where user_id=%s order by created_at desc",
        (user_id,),
    )
