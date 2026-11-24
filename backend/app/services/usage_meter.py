"""Budget enforcement for every paid external call (CLAUDE.md cost guardrails).

`reserve()` records the estimated cost in api_usage_ledger BEFORE the call and raises
BudgetExceeded if the workspace's monthly budget (or the run budget) would be exceeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PRICING = Path(__file__).resolve().parent.parent / "config" / "pricing.yaml"


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: str, limit: Decimal, would_be: Decimal):
        super().__init__(f"{scope} budget exceeded: limit ${limit}, would reach ${would_be:.4f}")
        self.scope, self.limit, self.would_be = scope, limit, would_be


class UnknownSku(KeyError):
    pass


@lru_cache
def pricing() -> dict[str, dict[str, dict[str, object]]]:
    data: dict[str, dict[str, dict[str, object]]] = yaml.safe_load(_PRICING.read_text())
    return data


def unit_price(provider: str, sku: str) -> Decimal:
    try:
        return Decimal(str(pricing()[provider][sku]["usd_per_unit"]))
    except KeyError as exc:
        raise UnknownSku(f"{provider}.{sku} is not in config/pricing.yaml") from exc


@dataclass
class UsageMeter:
    session: AsyncSession
    workspace_id: UUID
    discovery_run_id: UUID | None = None
    run_budget_usd: Decimal | None = None

    async def month_spend(self) -> Decimal:
        row = await self.session.execute(
            text(
                "SELECT coalesce(sum(est_cost_usd), 0) FROM api_usage_ledger "
                "WHERE workspace_id = :w AND created_at >= date_trunc('month', now())"
            ),
            {"w": self.workspace_id},
        )
        return Decimal(row.scalar_one())

    async def run_spend(self) -> Decimal:
        if self.discovery_run_id is None:
            return Decimal(0)
        row = await self.session.execute(
            text("SELECT coalesce(sum(est_cost_usd), 0) FROM api_usage_ledger WHERE discovery_run_id = :r"),
            {"r": self.discovery_run_id},
        )
        return Decimal(row.scalar_one())

    async def reserve(self, provider: str, sku: str, units: int) -> Decimal:
        if units <= 0:
            return Decimal(0)
        cost = unit_price(provider, sku) * units
        budget = (
            await self.session.execute(
                text("SELECT monthly_api_budget_usd FROM workspaces WHERE id = :w"), {"w": self.workspace_id}
            )
        ).scalar_one()
        would_be = await self.month_spend() + cost
        if would_be > Decimal(budget):
            raise BudgetExceeded("monthly", Decimal(budget), would_be)
        if self.run_budget_usd is not None:
            run_would_be = await self.run_spend() + cost
            if run_would_be > self.run_budget_usd:
                raise BudgetExceeded("run", self.run_budget_usd, run_would_be)
        await self.session.execute(
            text(
                "INSERT INTO api_usage_ledger (workspace_id, discovery_run_id, provider, sku, units, est_cost_usd) "
                "VALUES (:w, :r, :p, :s, :u, :c)"
            ),
            {
                "w": self.workspace_id,
                "r": self.discovery_run_id,
                "p": provider,
                "s": sku,
                "u": units,
                "c": cost,
            },
        )
        return cost
