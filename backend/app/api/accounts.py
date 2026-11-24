from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import Ws
from app.services.reviews import ReviewNotPending, decide_review

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["accounts"])

AccountStatus = Literal["customer", "lapsed_customer", "prospect", "disqualified", "merged"]


class AccountOut(BaseModel):
    id: UUID
    status: str
    display_name: str
    address: str | None
    lat: float | None
    lng: float | None
    geocode_precision: str | None
    phone_e164: str | None
    website_domain: str | None
    external_crm_id: str | None
    last_order_at: date | None
    order_count: int
    lifetime_value: float | None
    attributes: dict[str, Any]


class AccountPage(BaseModel):
    items: list[AccountOut]
    total: int


_ACCOUNT_COLS = """a.id, a.status, a.display_name, a.address, ST_Y(a.geom) AS lat, ST_X(a.geom) AS lng,
  a.geocode->>'precision' AS geocode_precision, a.phone_e164, a.website_domain::text AS website_domain,
  a.external_crm_id, a.last_order_at, a.order_count, a.lifetime_value, a.attributes"""


def _account(r: Any) -> AccountOut:
    return AccountOut(
        **{**r._mapping, "lifetime_value": float(r.lifetime_value) if r.lifetime_value is not None else None}
    )


@router.get("/accounts")
async def list_accounts(
    ws: Ws, status_filter: AccountStatus | None = None, q: str | None = None, limit: int = 50, offset: int = 0
) -> AccountPage:
    where = ["a.status <> 'merged'"] if status_filter is None else ["a.status = :st"]
    params: dict[str, Any] = {"st": status_filter, "l": min(max(limit, 1), 500), "o": max(offset, 0)}
    if q:
        where.append("(a.display_name ILIKE :q OR a.phone_e164 LIKE :q OR a.external_crm_id ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    clause = " AND ".join(where)
    total = (
        await ws.session.execute(text(f"SELECT count(*) FROM accounts a WHERE {clause}"), params)
    ).scalar_one()
    rows = await ws.session.execute(
        text(
            f"SELECT {_ACCOUNT_COLS} FROM accounts a WHERE {clause} ORDER BY a.display_name LIMIT :l OFFSET :o"
        ),
        params,
    )
    return AccountPage(items=[_account(r) for r in rows], total=int(total))


class ReviewOut(BaseModel):
    id: UUID
    score: float
    evidence: dict[str, Any]
    status: str
    incoming: AccountOut
    candidate: AccountOut


@router.get("/match-reviews")
async def list_reviews(
    ws: Ws, status_filter: Literal["pending", "accepted", "rejected"] = "pending"
) -> list[ReviewOut]:
    rows = (
        await ws.session.execute(
            text("""
        SELECT r.id, r.score, r.evidence, r.status, s.account_id AS incoming_id, r.candidate_account_id
        FROM match_reviews r JOIN source_records s ON s.id = r.source_record_id
        WHERE r.status = :st ORDER BY r.score DESC LIMIT 200
    """),
            {"st": status_filter},
        )
    ).all()
    ids = {i for r in rows for i in (r.incoming_id, r.candidate_account_id) if i}
    accounts: dict[UUID, AccountOut] = {}
    if ids:
        for a in await ws.session.execute(
            text(f"SELECT {_ACCOUNT_COLS} FROM accounts a WHERE a.id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(i) for i in ids]},
        ):
            accounts[a.id] = _account(a)
    return [
        ReviewOut(
            id=r.id,
            score=float(r.score),
            evidence=r.evidence,
            status=r.status,
            incoming=accounts[r.incoming_id],
            candidate=accounts[r.candidate_account_id],
        )
        for r in rows
        if r.incoming_id in accounts and r.candidate_account_id in accounts
    ]


class ReviewDecision(BaseModel):
    decision: Literal["accept", "reject"]


@router.post("/match-reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decide(ws: Ws, review_id: UUID, body: ReviewDecision) -> None:
    ws.require("manager")
    months = (
        await ws.session.execute(
            text(
                "SELECT coalesce((settings->>'lapsed_after_months')::int, 12) FROM workspaces WHERE id = :w"
            ),
            {"w": ws.workspace_id},
        )
    ).scalar_one()
    try:
        await decide_review(
            ws.session,
            review_id,
            accept=body.decision == "accept",
            user_id=ws.user.id,
            lapsed_after_months=int(months),
        )
    except ReviewNotPending as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "review is not pending") from exc
