from uuid import uuid4

import pytest

from app.adapters.llm.base import LLMResult
from app.domain.entity_resolution import Candidate, Incoming, decide
from app.imports.llm_mapper import LLMColumnSuggestion, LLMMappingResponse, LLMParam, merge_suggestions
from app.imports.mapping import ColumnMapping, FieldMapping
from app.imports.targets import Transform

A = uuid4()


def cand(**kw: object) -> Candidate:
    base: dict[str, object] = {"account_id": A, "name_sim": 0.0, "distance_m": None}
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("incoming", "candidate", "kind"),
    [
        # exact external key
        (Incoming(external_crm_id="C001"), cand(external_crm_id="C001"), "link"),
        # same phone, close by
        (Incoming(phone_e164="+97141"), cand(phone_e164="+97141", distance_m=120.0), "link"),
        # same phone, no coordinates, similar name
        (Incoming(phone_e164="+97141"), cand(phone_e164="+97141", name_sim=0.7), "link"),
        # same phone but 5 km apart → chain branch? human decides
        (Incoming(phone_e164="+97141"), cand(phone_e164="+97141", distance_m=5000.0, name_sim=0.9), "review"),
        # same domain, dissimilar name, no coords → review
        (Incoming(website_domain="x.ae"), cand(website_domain="x.ae", name_sim=0.2), "review"),
        # similar name next door → link
        (Incoming(), cand(name_sim=0.95, distance_m=10.0), "link"),
        # similar name 120 m away → review
        (Incoming(), cand(name_sim=0.7, distance_m=120.0), "review"),
        # identical name, nobody has coordinates, nothing conflicts → link (invoices carry names only)
        (Incoming(), cand(name_sim=1.0), "link"),
        # identical name but a different phone on both sides → review
        (Incoming(phone_e164="+9712"), cand(name_sim=1.0, phone_e164="+9713"), "review"),
        # near-identical name, no coordinates → review
        (Incoming(), cand(name_sim=0.92), "review"),
        # weak name match far away → new
        (Incoming(), cand(name_sim=0.4, distance_m=900.0), "new"),
    ],
)
def test_decide(incoming: Incoming, candidate: Candidate, kind: str) -> None:
    d = decide(incoming, [candidate])
    assert d.kind == kind
    if kind == "review":
        assert d.reviews and d.reviews[0][0] == A


def test_two_equally_good_name_matches_are_ambiguous() -> None:
    d = decide(Incoming(), [cand(name_sim=1.0), Candidate(account_id=uuid4(), name_sim=1.0, distance_m=None)])
    assert d.kind == "review" and len(d.reviews) == 2


def test_decide_no_candidates() -> None:
    assert decide(Incoming(phone_e164="+1"), []).kind == "new"


def test_merge_llm_suggestions_validates_everything() -> None:
    headers = ["Nom", "Tél", "Secteur", "Interne", "Ville"]
    base = ColumnMapping(
        fields=[
            FieldMapping(
                target="city", source_columns=["Ville"], transform=Transform.concat, origin="heuristic"
            )
        ],
        unmapped=["Nom", "Tél", "Secteur", "Interne"],
    )
    resp = LLMMappingResponse(
        suggestions=[
            LLMColumnSuggestion(
                column="Nom", target="display_name", transform=Transform.trim, confidence=0.99, reason="name"
            ),
            LLMColumnSuggestion(
                column="Tél",
                target="phone",
                transform=Transform.parse_date,
                confidence=0.8,
                params=[LLMParam(key="default_region", value="FR")],
                reason="phone",
            ),
            LLMColumnSuggestion(
                column="Secteur", target="attributes.segment", confidence=0.7, reason="segment"
            ),
            LLMColumnSuggestion(column="Interne", target="drop_table_users", confidence=0.9, reason="?"),
            LLMColumnSuggestion(
                column="Ville", target="display_name", confidence=0.9, reason="already mapped column"
            ),
            LLMColumnSuggestion(column="Ghost", target="email", confidence=0.9, reason="not in file"),
        ]
    )
    merged = merge_suggestions("accounts", headers, base, LLMResult(resp, 10, 10, "fake"), base.unmapped)
    m = {f.target: f for f in merged.fields}
    assert m["display_name"].source_columns == ["Nom"]
    assert m["display_name"].confidence == 0.9  # capped
    assert m["display_name"].origin == "llm"
    assert m["phone"].transform is Transform.phone_e164  # invalid transform replaced by default
    assert m["phone"].params == {"default_region": "FR"}
    assert m["attributes.segment"].source_columns == ["Secteur"]
    assert m["city"].source_columns == ["Ville"]
    assert "drop_table_users" not in m
    assert merged.unmapped == ["Interne"]
    assert any("unknown target" in w for w in merged.warnings)
