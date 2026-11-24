"""Order-history rollups: last order, count, lifetime value, and customer vs lapsed status."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def refresh_rollups(
    session: AsyncSession, account_ids: list[UUID] | None, *, lapsed_after_months: int
) -> int:
    """Recompute rollups for the given accounts (None = every account with orders).
    Status rule: an account with orders is `customer` if it ordered within the window, else
    `lapsed_customer`. Prospects, disqualified and merged accounts are left alone unless they
    have orders (then they are customers by definition)."""
    params: dict[str, object] = {"months": lapsed_after_months}
    scope = ""
    if account_ids is not None:
        if not account_ids:
            return 0
        scope = "AND a.id = ANY(CAST(:ids AS uuid[]))"
        params["ids"] = [str(i) for i in account_ids]
    res = await session.execute(
        text(f"""
        WITH agg AS (
          SELECT account_id, max(order_date) AS last_order, count(*) AS n, sum(amount) AS ltv
          FROM historical_orders GROUP BY account_id
        )
        UPDATE accounts a SET
          last_order_at = agg.last_order,
          order_count = agg.n,
          lifetime_value = agg.ltv,
          status = CASE
            WHEN a.status = 'merged' THEN a.status
            WHEN agg.last_order >= (current_date - make_interval(months => CAST(:months AS int))) THEN 'customer'
            ELSE 'lapsed_customer' END,
          updated_at = now()
        FROM agg
        WHERE agg.account_id = a.id {scope}
    """),
        params,
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]
