"""End-to-end import flow through the API, including the Phase 1 exit criteria:
two differently shaped ERP exports + one invoice export import with ≥95% of rows mapped and
no manual reformatting; planted duplicates are surfaced."""

from __future__ import annotations

from typing import Any

import psycopg

from app.adapters.geocoding import set_geocoders
from app.adapters.geocoding.base import GeocodeResult
from app.adapters.llm import set_llm_client
from app.adapters.llm.fake import FakeLLM
from app.imports.llm_mapper import PROMPT_NAME
from tests.conftest import ApiUser, fixture_bytes, odoo_xlsx

# Tally rows have no coordinates; this stands in for OpenCage.
KNOWN_AREAS = {
    "bur dubai": (25.2635, 55.2972),
    "jebel ali": (24.9857, 55.0273),
    "dubai marina": (25.0805, 55.1403),
    "trade centre": (25.2285, 55.2861),
    "deira": (25.2711, 55.3075),
    "al qusais": (25.2797, 55.3767),
}


class FakeGeocoder:
    provider, sku = "opencage", "opencage_request"

    def __init__(self) -> None:
        self.calls = 0

    async def geocode(self, query: str, *, country_codes: str) -> GeocodeResult | None:
        self.calls += 1
        q = query.lower()
        for area, (lat, lng) in KNOWN_AREAS.items():
            if area in q:
                return GeocodeResult(lat, lng, "street", 0.9, self.provider, None)
        return None


async def test_upload_proposes_mapping_and_requires_confirmation(alice: ApiUser) -> None:
    ws = await alice.create_workspace()
    job = await alice.upload(ws, "tally.csv", fixture_bytes("tally_customers.csv"), "accounts")
    assert job["status"] == "mapping_proposed"
    assert job["row_count"] == 20
    assert len(job["sample_rows"]) == 20
    targets = {f["target"] for f in job["proposed_mapping"]["fields"]}
    assert {"display_name", "external_crm_id", "address", "city", "phone", "email"} <= targets
    assert "AI column mapping is off" in " ".join(job["proposed_mapping"]["warnings"])  # TRN left unmapped
    r = await alice.post(f"/workspaces/{ws}/imports/{job['id']}/run")
    assert r.status_code == 409  # not confirmed yet


async def test_phase1_exit_criteria(alice: ApiUser, owner_conn: psycopg.Connection[Any]) -> None:
    geo = FakeGeocoder()
    set_geocoders([geo])
    ws = await alice.create_workspace()

    # 1. Tally-style customer master (CSV, split address, messy phones, no coordinates)
    tally = await alice.confirm_and_run(
        ws, await alice.upload(ws, "tally.csv", fixture_bytes("tally_customers.csv"), "accounts")
    )
    assert tally["status"] == "succeeded", tally["stats"]
    st = tally["stats"]
    assert st["rows_total"] == 20
    assert st["rows_imported"] / st["rows_total"] >= 0.95  # one row has no name → error report
    assert st["rows_failed"] == 1 and tally["has_error_report"]
    assert st["geocoded"] >= 6 and geo.calls > 0

    # 2. Odoo-style contacts (XLSX, coordinates, different header vocabulary, overlapping customers)
    odoo = await alice.confirm_and_run(ws, await alice.upload(ws, "contacts.xlsx", odoo_xlsx(), "accounts"))
    assert odoo["status"] == "succeeded", odoo["stats"]
    so = odoo["stats"]
    assert so["rows_imported"] == so["rows_total"] == 15
    # Al Noor (same phone), Falcon Star (same phone), Marina Crest (same phone) link automatically.
    assert so["accounts_matched"] >= 3
    # Horizon Line: similar name, Tally geocode 'Trade Centre' sits at the same point → linked or queued.
    assert so["accounts_matched"] + so["reviews_created"] >= 4

    # 3. Zoho-style invoices (day-first dates, "AED 1,250.00" amounts, IDs + names)
    inv = await alice.confirm_and_run(
        ws, await alice.upload(ws, "invoices.csv", fixture_bytes("zoho_invoices.csv"), "orders")
    )
    assert inv["status"] == "succeeded", inv["stats"]
    si = inv["stats"]
    assert si["rows_total"] == 21
    assert si["rows_imported"] / si["rows_total"] >= 0.95
    assert si["orders_inserted"] == 20 and si["rows_failed"] == 1

    accounts = (await alice.get(f"/workspaces/{ws}/accounts", params={"limit": 500})).json()
    by_name = {a["display_name"]: a for a in accounts["items"]}
    assert by_name["Al Noor Trading L.L.C"]["order_count"] == 2
    assert by_name["Al Noor Trading L.L.C"]["status"] == "customer"
    assert by_name["Al Noor Trading L.L.C"]["website_domain"] == "alnoortrading.ae"  # filled in from Odoo
    assert by_name["Falcon Star FZE"]["status"] == "lapsed_customer"  # last order 14 months ago
    assert by_name["Al Noor Trading L.L.C"]["phone_e164"] == "+971501234567"
    assert "Brand New Customer LLC" in by_name  # orders for unknown customers create accounts
    # No account was created twice for the planted duplicates
    names = [a["display_name"] for a in accounts["items"]]
    assert "AL NOOR TRADING LLC" not in names
    assert "Falcon Star" not in names
    # Invoices that carry only a customer name attach to the existing account, not a copy.
    assert names.count("Cedar Gate LLC") == 1 and names.count("Lotus Bay FZE") == 1
    assert by_name["Cedar Gate LLC"]["order_count"] == 1
    assert si["accounts_created"] == 1  # only "Brand New Customer LLC"
    assert accounts["total"] == len(set(names))

    # Error report is downloadable and keeps the original row
    r = await alice.get(f"/workspaces/{ws}/imports/{tally['id']}/errors")
    assert r.status_code == 200 and "no business name" in r.text and "Al Rigga St" in r.text


async def test_reimport_same_file_is_idempotent_and_mapping_is_reused(alice: ApiUser) -> None:
    ws = await alice.create_workspace()
    data = fixture_bytes("tally_customers.csv")
    first = await alice.confirm_and_run(ws, await alice.upload(ws, "tally.csv", data, "accounts"))
    second_job = await alice.upload(ws, "tally-again.csv", data, "accounts")
    assert all(f["origin"] == "reused" for f in second_job["proposed_mapping"]["fields"])
    second = await alice.confirm_and_run(ws, second_job)
    assert second["stats"]["rows_skipped_duplicate"] == first["stats"]["rows_imported"]
    assert second["stats"]["accounts_created"] == 0


async def test_llm_maps_columns_heuristics_cannot(alice: ApiUser) -> None:
    fake = FakeLLM(
        {
            PROMPT_NAME: {
                "suggestions": [
                    {
                        "column": "Raison sociale",
                        "target": "display_name",
                        "transform": "trim",
                        "confidence": 0.95,
                        "reason": "fr: company name",
                    },
                    {
                        "column": "Tél.",
                        "target": "phone",
                        "transform": "phone_e164",
                        "confidence": 0.9,
                        "reason": "fr: phone",
                    },
                    {
                        "column": "Notes internes",
                        "target": None,
                        "confidence": 0.8,
                        "reason": "internal notes",
                    },
                ]
            }
        }
    )
    set_llm_client(fake)
    ws = await alice.create_workspace()
    data = "Raison sociale,Tél.,Notes internes\nCedar Gate,04 344 5566,vip\nLotus Bay,07 204 1100,\n".encode()
    job = await alice.upload(ws, "fr.csv", data, "accounts")
    fields = {f["target"]: f for f in job["proposed_mapping"]["fields"]}
    assert fields["display_name"]["origin"] == "llm" and fields["display_name"]["confidence"] == 0.9
    assert fields["phone"]["source_columns"] == ["Tél."]
    assert job["proposed_mapping"]["unmapped"] == ["Notes internes"]
    assert len(fake.calls) == 1
    assert "Cedar Gate" in fake.calls[0][1]  # sample values sent (LLM_SEND_SAMPLE_VALUES default)
    done = await alice.confirm_and_run(ws, job)
    assert done["stats"]["rows_imported"] == 2


async def test_llm_skipped_when_budget_exhausted(alice: ApiUser, owner_conn: psycopg.Connection[Any]) -> None:
    fake = FakeLLM({PROMPT_NAME: {"suggestions": []}})
    set_llm_client(fake)
    ws = await alice.create_workspace()
    owner_conn.execute("UPDATE workspaces SET monthly_api_budget_usd = 0 WHERE id = %s", (ws,))
    job = await alice.upload(ws, "fr.csv", b"Raison sociale,Tel\nA,1\n", "accounts")
    assert fake.calls == []  # never called
    assert any("budget exceeded" in w for w in job["proposed_mapping"]["warnings"])


async def test_invalid_mapping_is_rejected_with_reasons(alice: ApiUser) -> None:
    ws = await alice.create_workspace()
    job = await alice.upload(ws, "tally.csv", fixture_bytes("tally_customers.csv"), "accounts")
    bad = {"fields": [{"target": "order_date", "source_columns": ["Party Name"], "transform": "parse_date"}]}
    r = await alice.put(f"/workspaces/{ws}/imports/{job['id']}/mapping", json=bad)
    assert r.status_code == 422
    problems = r.json()["detail"]["problems"]
    assert any("unknown target 'order_date'" in p for p in problems)
    assert any("display_name" in p for p in problems)


async def test_workspace_isolation_through_api(alice: ApiUser, bob: ApiUser) -> None:
    ws = await alice.create_workspace("Alice Co")
    job = await alice.upload(ws, "tally.csv", fixture_bytes("tally_customers.csv"), "accounts")
    assert (await bob.get(f"/workspaces/{ws}")).status_code == 404
    assert (await bob.get(f"/workspaces/{ws}/imports/{job['id']}")).status_code == 404
    assert (await bob.get("/workspaces")).json() == []
    assert [w["name"] for w in (await alice.get("/workspaces")).json()] == ["Alice Co"]
    assert (await alice.client.get("/workspaces")).status_code == 401
    bad_token = {"Authorization": "Bearer " + "x.y.z"}
    assert (await alice.client.get("/workspaces", headers=bad_token)).status_code == 401


async def test_upload_rejects_unsupported_and_empty_files(alice: ApiUser) -> None:
    ws = await alice.create_workspace()
    r = await alice.post(
        f"/workspaces/{ws}/imports", files={"file": ("x.pdf", b"%PDF")}, data={"kind": "accounts"}
    )
    assert r.status_code == 415
    r = await alice.post(
        f"/workspaces/{ws}/imports", files={"file": ("x.csv", b"")}, data={"kind": "accounts"}
    )
    assert r.status_code == 422
