"""Decide whether an incoming record is an existing account, a possible duplicate for human
review, or a new account. Pure: candidates are fetched elsewhere (services/resolution.py).

Rules (docs/schema.md "Entity resolution order"):
1. Exact external key (place_id, osm_ref, registry_ref, customer ID) → link.
2. Same phone or website domain AND (≤300 m, or no coordinates but similar name) → link.
   Same phone/domain but far apart or dissimilar names → review (chains share numbers).
3. Similar name (≥0.6) within 150 m → score; ≥0.85 auto-link, else review.
   No coordinates on either side: exact name and no conflicting identifier → link;
   near-identical name (≥0.9), or exact name with a conflicting phone/domain/ID → review.
4. Two or more equally strong name-only matches → review (ambiguous), never a silent pick.
5. Otherwise → new.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

AUTO_LINK = 0.85
NAME_MIN = 0.6
NEAR_M = 150.0
KEY_NEAR_M = 300.0


@dataclass(frozen=True)
class Incoming:
    google_place_id: str | None = None
    osm_ref: str | None = None
    registry_ref: str | None = None
    external_crm_id: str | None = None
    phone_e164: str | None = None
    website_domain: str | None = None


@dataclass(frozen=True)
class Candidate:
    account_id: UUID
    name_sim: float
    distance_m: float | None
    google_place_id: str | None = None
    osm_ref: str | None = None
    registry_ref: str | None = None
    external_crm_id: str | None = None
    phone_e164: str | None = None
    website_domain: str | None = None


@dataclass
class Decision:
    kind: Literal["link", "review", "new"]
    account_id: UUID | None = None
    score: float = 0.0
    evidence: dict[str, object] = field(default_factory=dict)
    reviews: list[tuple[UUID, float, dict[str, object]]] = field(default_factory=list)


def _exact_key(inc: Incoming, c: Candidate) -> str | None:
    for attr in ("google_place_id", "osm_ref", "registry_ref", "external_crm_id"):
        a, b = getattr(inc, attr), getattr(c, attr)
        if a and b and a == b:
            return attr
    return None


def _conflict(inc: Incoming, c: Candidate) -> list[str]:
    """Identifiers present on both sides that disagree (strong evidence of different businesses)."""
    out = []
    for attr in ("external_crm_id", "registry_ref", "phone_e164", "website_domain"):
        a, b = getattr(inc, attr), getattr(c, attr)
        if a and b and a != b:
            out.append(attr)
    return out


def score_candidate(inc: Incoming, c: Candidate) -> tuple[float, dict[str, object]]:
    ev: dict[str, object] = {
        "name_sim": round(c.name_sim, 3),
        "distance_m": None if c.distance_m is None else round(c.distance_m, 1),
    }
    key = _exact_key(inc, c)
    if key:
        ev["matched_on"] = [key]
        return 1.0, ev
    phone_eq = bool(inc.phone_e164 and inc.phone_e164 == c.phone_e164)
    domain_eq = bool(inc.website_domain and inc.website_domain == c.website_domain)
    ev["phone_eq"], ev["domain_eq"] = phone_eq, domain_eq
    if phone_eq or domain_eq:
        ev["matched_on"] = [k for k, v in (("phone", phone_eq), ("domain", domain_eq)) if v]
        if c.distance_m is not None:
            return (0.95 if c.distance_m <= KEY_NEAR_M else 0.6), ev
        return (0.9 if c.name_sim >= 0.5 else 0.6), ev
    if c.distance_m is not None and c.distance_m <= NEAR_M and c.name_sim >= NAME_MIN:
        ev["matched_on"] = ["name", "location"]
        proximity = 1.0 - c.distance_m / NEAR_M
        return round(0.6 * c.name_sim + 0.4 * proximity, 3), ev
    if c.distance_m is None and c.name_sim >= 0.9:
        ev["matched_on"] = ["name"]
        conflicts = _conflict(inc, c)
        if conflicts:
            ev["conflicts"] = conflicts
            return 0.7, ev
        return (0.88 if c.name_sim >= 0.99 else 0.7), ev
    return 0.0, ev


def decide(inc: Incoming, candidates: list[Candidate]) -> Decision:
    scored = sorted(((c, *score_candidate(inc, c)) for c in candidates), key=lambda x: -x[1])
    scored = [s for s in scored if s[1] > 0]
    if not scored:
        return Decision("new")
    best, best_score, best_ev = scored[0]
    ambiguous = len(scored) > 1 and scored[1][1] >= AUTO_LINK and best_ev.get("matched_on") == ["name"]
    if best_score >= AUTO_LINK and not ambiguous:
        return Decision("link", best.account_id, best_score, best_ev)
    return Decision(
        "review",
        best.account_id,
        best_score,
        best_ev,
        reviews=[(c.account_id, s, ev) for c, s, ev in scored[:3]],
    )
