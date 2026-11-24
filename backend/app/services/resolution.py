"""DB side of entity resolution: fetch candidates, apply the pure decision, write the result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entity_resolution import Candidate, Decision, Incoming, decide

_CANDIDATES = text("""
WITH p AS (
  SELECT CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL
              ELSE ST_SetSRID(ST_MakePoint(CAST(:lng AS float8), CAST(:lat AS float8)), 4326) END AS pt
)
SELECT a.id, a.google_place_id, a.osm_ref, a.registry_ref, a.external_crm_id, a.phone_e164,
       a.website_domain::text AS website_domain,
       similarity(a.name_norm, CAST(:name AS text)) AS name_sim,
       CASE WHEN a.geom IS NOT NULL AND p.pt IS NOT NULL
            THEN ST_Distance(a.geom::geography, p.pt::geography) END AS distance_m
FROM accounts a, p
WHERE a.status <> 'merged' AND (
     (CAST(:ext AS text) IS NOT NULL AND a.external_crm_id = CAST(:ext AS text))
  OR (CAST(:reg AS text) IS NOT NULL AND a.registry_ref = CAST(:reg AS text))
  OR (CAST(:phone AS text) IS NOT NULL AND a.phone_e164 = CAST(:phone AS text))
  OR (CAST(:domain AS text) IS NOT NULL AND a.website_domain = CAST(:domain AS citext))
  OR (p.pt IS NOT NULL AND a.geom IS NOT NULL
      AND ST_DWithin(a.geom::geography, p.pt::geography, 300)
      AND similarity(a.name_norm, CAST(:name AS text)) >= 0.3)
  OR (CAST(:name AS text) <> '' AND a.name_norm % CAST(:name AS text))
)
ORDER BY name_sim DESC
LIMIT 20
""")


@dataclass
class AccountInput:
    display_name: str
    name_norm: str
    status: str
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    geocode: dict[str, Any] | None = None
    phone_e164: str | None = None
    website_domain: str | None = None
    external_crm_id: str | None = None
    registry_ref: str | None = None
    attributes: dict[str, Any] | None = None
    provenance_source: str = "csv_import"


async def find_candidates(session: AsyncSession, a: AccountInput) -> list[Candidate]:
    rows = await session.execute(
        _CANDIDATES,
        {
            "lat": a.lat,
            "lng": a.lng,
            "name": a.name_norm,
            "ext": a.external_crm_id,
            "reg": a.registry_ref,
            "phone": a.phone_e164,
            "domain": a.website_domain,
        },
    )
    return [
        Candidate(
            account_id=r.id,
            name_sim=float(r.name_sim or 0),
            distance_m=None if r.distance_m is None else float(r.distance_m),
            google_place_id=r.google_place_id,
            osm_ref=r.osm_ref,
            registry_ref=r.registry_ref,
            external_crm_id=r.external_crm_id,
            phone_e164=r.phone_e164,
            website_domain=r.website_domain,
        )
        for r in rows
    ]


def _provenance(a: AccountInput) -> dict[str, Any]:
    fields = ["display_name", "address", "phone_e164", "website_domain", "external_crm_id", "registry_ref"]
    prov: dict[str, Any] = {f: {"source": a.provenance_source} for f in fields if getattr(a, f)}
    if a.lat is not None and a.geocode:
        prov["geom"] = {
            "source": a.geocode.get("provider", a.provenance_source),
            "expires_at": a.geocode.get("storable_until"),
        }
    return prov


async def create_account(session: AsyncSession, workspace_id: UUID, a: AccountInput) -> UUID:
    row = await session.execute(
        text("""
        INSERT INTO accounts (workspace_id, status, display_name, name_norm, address, geom, geocode, phone_e164,
                              website_domain, external_crm_id, registry_ref, attributes, field_provenance)
        VALUES (:w, :status, :name, :norm, :address,
                CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL
                     ELSE ST_SetSRID(ST_MakePoint(CAST(:lng AS float8), CAST(:lat AS float8)), 4326) END,
                CAST(:geocode AS jsonb), :phone, :domain, :ext, :reg, CAST(:attrs AS jsonb), CAST(:prov AS jsonb))
        RETURNING id
    """),
        {
            "w": workspace_id,
            "status": a.status,
            "name": a.display_name,
            "norm": a.name_norm,
            "address": a.address,
            "lat": a.lat,
            "lng": a.lng,
            "geocode": json.dumps(a.geocode) if a.geocode else None,
            "phone": a.phone_e164,
            "domain": a.website_domain,
            "ext": a.external_crm_id,
            "reg": a.registry_ref,
            "attrs": json.dumps(a.attributes or {}, ensure_ascii=False, default=str),
            "prov": json.dumps(_provenance(a)),
        },
    )
    return UUID(str(row.scalar_one()))


async def enrich_existing(session: AsyncSession, account_id: UUID, a: AccountInput) -> None:
    """Fill gaps on a matched account without overwriting values it already has.
    A customer list upgrades a prospect to customer."""
    await session.execute(
        text("""
        UPDATE accounts SET
          address = coalesce(address, :address),
          geom = coalesce(geom, CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL
                     ELSE ST_SetSRID(ST_MakePoint(CAST(:lng AS float8), CAST(:lat AS float8)), 4326) END),
          geocode = coalesce(geocode, CAST(:geocode AS jsonb)),
          phone_e164 = coalesce(phone_e164, :phone),
          website_domain = coalesce(website_domain, :domain),
          external_crm_id = coalesce(external_crm_id, :ext),
          registry_ref = coalesce(registry_ref, :reg),
          attributes = CAST(:attrs AS jsonb) || attributes,
          field_provenance = CAST(:prov AS jsonb) || field_provenance,
          status = CASE WHEN status = 'prospect' AND :status IN ('customer', 'lapsed_customer') THEN :status ELSE status END,
          updated_at = now()
        WHERE id = :id
    """),
        {
            "id": account_id,
            "address": a.address,
            "lat": a.lat,
            "lng": a.lng,
            "geocode": json.dumps(a.geocode) if a.geocode else None,
            "phone": a.phone_e164,
            "domain": a.website_domain,
            "ext": a.external_crm_id,
            "reg": a.registry_ref,
            "status": a.status,
            "attrs": json.dumps(a.attributes or {}, ensure_ascii=False, default=str),
            "prov": json.dumps(_provenance(a)),
        },
    )


@dataclass
class ResolutionOutcome:
    account_id: UUID
    decision: Decision
    created: bool


async def resolve_and_write(
    session: AsyncSession, workspace_id: UUID, source_record_id: UUID, a: AccountInput
) -> ResolutionOutcome:
    """Link to an existing account, or create one (queueing reviews when unsure).
    A 'review' decision still creates a separate account so no data is lost; accepting the
    review merges the two (services/reviews.py)."""
    inc = Incoming(
        registry_ref=a.registry_ref,
        external_crm_id=a.external_crm_id,
        phone_e164=a.phone_e164,
        website_domain=a.website_domain,
    )
    decision = decide(inc, await find_candidates(session, a))
    if decision.kind == "link" and decision.account_id:
        await enrich_existing(session, decision.account_id, a)
        account_id, created = decision.account_id, False
    else:
        account_id, created = await create_account(session, workspace_id, a), True
        for cand_id, score, ev in decision.reviews:
            await session.execute(
                text("""
                INSERT INTO match_reviews (workspace_id, source_record_id, candidate_account_id, score, evidence)
                VALUES (:w, :sr, :c, :s, CAST(:e AS jsonb)) ON CONFLICT DO NOTHING
            """),
                {
                    "w": workspace_id,
                    "sr": source_record_id,
                    "c": cand_id,
                    "s": round(score, 3),
                    "e": json.dumps(ev),
                },
            )
    await session.execute(
        text("UPDATE source_records SET account_id = :a, match = CAST(:m AS jsonb) WHERE id = :id"),
        {
            "a": account_id,
            "id": source_record_id,
            "m": json.dumps(
                {"method": decision.kind, "score": round(decision.score, 3), **decision.evidence}
            ),
        },
    )
    return ResolutionOutcome(account_id, decision, created)
