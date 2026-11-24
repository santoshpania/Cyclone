from __future__ import annotations

from tests.conftest import ApiUser


async def _two_lookalikes(alice: ApiUser) -> str:
    """Same name, no coordinates, different phones → queued for review, not merged."""
    ws = await alice.create_workspace()
    a = b"Name,Phone,Customer ID\nOnyx Bridge LLC,02 443 1111,A1\n"
    b = b"Business,Telephone\nONYX BRIDGE,02 999 0000\n"
    await alice.confirm_and_run(ws, await alice.upload(ws, "a.csv", a, "accounts"))
    job = await alice.confirm_and_run(ws, await alice.upload(ws, "b.csv", b, "accounts"))
    assert job["stats"]["reviews_created"] == 1
    return ws


async def test_accepting_a_review_merges_accounts_and_orders(alice: ApiUser) -> None:
    ws = await _two_lookalikes(alice)
    reviews = (await alice.get(f"/workspaces/{ws}/match-reviews")).json()
    assert len(reviews) == 1
    assert reviews[0]["evidence"]["matched_on"] == ["name"]
    assert reviews[0]["evidence"]["conflicts"] == ["phone_e164"]
    r = await alice.post(f"/workspaces/{ws}/match-reviews/{reviews[0]['id']}", json={"decision": "accept"})
    assert r.status_code == 204
    # Orders imported after the merge attach to the survivor (merged accounts are never candidates).
    orders = b"Invoice No,Date,Customer,Amount\nI-1,01/11/2026,ONYX BRIDGE,100\n"
    done = await alice.confirm_and_run(ws, await alice.upload(ws, "o.csv", orders, "orders"))
    assert done["stats"]["accounts_created"] == 0
    items = (await alice.get(f"/workspaces/{ws}/accounts")).json()["items"]
    assert [a["display_name"] for a in items] == ["Onyx Bridge LLC"]
    survivor = items[0]
    assert survivor["order_count"] == 1 and survivor["external_crm_id"] == "A1"
    merged = (await alice.get(f"/workspaces/{ws}/accounts", params={"status_filter": "merged"})).json()[
        "items"
    ]
    assert [a["display_name"] for a in merged] == ["ONYX BRIDGE"]
    again = await alice.post(
        f"/workspaces/{ws}/match-reviews/{reviews[0]['id']}", json={"decision": "accept"}
    )
    assert again.status_code == 409


async def test_rejecting_a_review_keeps_both(alice: ApiUser) -> None:
    ws = await _two_lookalikes(alice)
    review = (await alice.get(f"/workspaces/{ws}/match-reviews")).json()[0]
    r = await alice.post(f"/workspaces/{ws}/match-reviews/{review['id']}", json={"decision": "reject"})
    assert r.status_code == 204
    assert (await alice.get(f"/workspaces/{ws}/accounts")).json()["total"] == 2
    assert (await alice.get(f"/workspaces/{ws}/match-reviews")).json() == []


async def test_order_with_ambiguous_customer_name_is_queued_not_guessed(alice: ApiUser) -> None:
    ws = await _two_lookalikes(alice)  # two pending "Onyx Bridge" accounts
    orders = b"Invoice No,Date,Customer,Amount\nI-1,01/11/2026,ONYX BRIDGE,100\n"
    done = await alice.confirm_and_run(ws, await alice.upload(ws, "o.csv", orders, "orders"))
    assert done["stats"]["accounts_created"] == 1 and done["stats"]["reviews_created"] == 2
