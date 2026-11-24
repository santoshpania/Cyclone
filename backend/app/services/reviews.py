"""Resolve a duplicate-match review. Accepting merges the newer account into the candidate."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.orders import refresh_rollups


class ReviewNotPending(ValueError):
    pass


async def decide_review(
    session: AsyncSession, review_id: UUID, *, accept: bool, user_id: UUID, lapsed_after_months: int
) -> None:
    review = (
        await session.execute(
            text("""
        SELECT r.id, r.status, r.candidate_account_id, s.account_id AS source_account_id
        FROM match_reviews r JOIN source_records s ON s.id = r.source_record_id
        WHERE r.id = :id FOR UPDATE OF r
    """),
            {"id": review_id},
        )
    ).one_or_none()
    if review is None or review.status != "pending":
        raise ReviewNotPending(str(review_id))
    await session.execute(
        text("""
        UPDATE match_reviews SET status = :st, decided_by = :u, decided_at = now() WHERE id = :id
    """),
        {"st": "accepted" if accept else "rejected", "u": user_id, "id": review_id},
    )
    if not accept:
        return
    keep, drop = review.candidate_account_id, review.source_account_id
    if drop is None or drop == keep:
        return
    await session.execute(
        text("""
        UPDATE accounts k SET
          address = coalesce(k.address, d.address), geom = coalesce(k.geom, d.geom), geocode = coalesce(k.geocode, d.geocode),
          phone_e164 = coalesce(k.phone_e164, d.phone_e164), website_domain = coalesce(k.website_domain, d.website_domain),
          external_crm_id = coalesce(k.external_crm_id, d.external_crm_id), registry_ref = coalesce(k.registry_ref, d.registry_ref),
          attributes = d.attributes || k.attributes, field_provenance = d.field_provenance || k.field_provenance,
          updated_at = now()
        FROM accounts d WHERE k.id = :keep AND d.id = :drop
    """),
        {"keep": keep, "drop": drop},
    )
    for table in ("source_records", "historical_orders", "enrichments", "account_pitches", "route_stops"):
        await session.execute(
            text(f"UPDATE {table} SET account_id = :keep WHERE account_id = :drop"),
            {"keep": keep, "drop": drop},
        )
    await session.execute(
        text("""
        UPDATE accounts SET status = 'merged', merged_into_id = :keep, updated_at = now() WHERE id = :drop
    """),
        {"keep": keep, "drop": drop},
    )
    # Other pending reviews pointing at the merged account now point at the survivor.
    await session.execute(
        text("""
        UPDATE match_reviews SET status = 'rejected', decided_by = :u, decided_at = now()
        WHERE status = 'pending' AND candidate_account_id = :drop
    """),
        {"drop": drop, "u": user_id},
    )
    await refresh_rollups(session, [keep], lapsed_after_months=lapsed_after_months)
