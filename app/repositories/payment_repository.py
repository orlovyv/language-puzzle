"""SQL access for the ``payments`` ledger."""

from __future__ import annotations

from typing import Any

from app.core.database import execute, query_all, query_one


def insert_payment(
    conn,
    payment_id: str,
    user_id: str,
    provider_id: str | None,
    amount: float,
    currency: str,
    status: str,
    period_days: int,
    provider: str = "yookassa",
) -> dict[str, Any]:
    # ``yookassa_id`` is the generic provider payment/invoice id column.
    return query_one(
        conn,
        """
        insert into payments (id, user_id, yookassa_id, amount, currency, status, period_days, provider)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning *
        """,
        (payment_id, user_id, provider_id, amount, currency, status, period_days, provider),
    )


def find_by_provider_id(conn, provider_id: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from payments where yookassa_id=%s", (provider_id,))


def find_by_id(conn, payment_id: str) -> dict[str, Any] | None:
    return query_one(conn, "select * from payments where id=%s", (payment_id,))


def update_status(conn, provider_id: str, status: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update payments set status=%s, updated_at=now() where yookassa_id=%s returning *",
        (status, provider_id),
    )


def update_status_by_id(conn, payment_id: str, status: str) -> dict[str, Any] | None:
    return query_one(
        conn,
        "update payments set status=%s, updated_at=now() where id=%s returning *",
        (status, payment_id),
    )


def user_payments(conn, user_id: str) -> list[dict[str, Any]]:
    return query_all(
        conn,
        "select * from payments where user_id=%s order by created_at desc",
        (user_id,),
    )
