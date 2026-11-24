import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from app.imports import heuristics
from app.imports.mapping import ColumnMapping, FieldMapping, MappingError, apply_mapping, validate_mapping
from app.imports.reader import header_fingerprint, read_table
from app.imports.targets import Transform
from tests.conftest import fixture_bytes, odoo_xlsx


def _by_target(m: ColumnMapping) -> dict[str, FieldMapping]:
    return {f.target: f for f in m.fields}


def test_heuristics_tally_customers() -> None:
    t = read_table("tally.csv", fixture_bytes("tally_customers.csv"))
    r = heuristics.propose("accounts", t.headers, t.sample, default_region="AE")
    m = _by_target(r.mapping)
    assert m["display_name"].source_columns == ["Party Name"]
    assert m["external_crm_id"].source_columns == ["Party Code"]
    assert m["address"].source_columns == ["Address 1", "Address 2"]
    assert m["address"].transform is Transform.concat
    assert m["city"].source_columns == ["Emirate"]
    assert m["phone"].source_columns == ["Mobile No."]
    assert m["email"].source_columns == ["E-Mail"]
    assert r.unresolved == ["TRN"]  # left for the LLM (or the user)
    assert not r.missing_required
    validate_mapping("accounts", t.headers, r.mapping)


def test_heuristics_odoo_xlsx() -> None:
    t = read_table("contacts.xlsx", odoo_xlsx())
    r = heuristics.propose("accounts", t.headers, t.sample, default_region="AE")
    m = _by_target(r.mapping)
    assert m["display_name"].source_columns == ["Display Name"]
    assert m["external_crm_id"].source_columns == ["Internal Reference"]
    assert m["address"].source_columns == ["Street", "Street2"]
    assert m["phone"].source_columns == ["Phone", "Mobile"]
    assert m["website"].source_columns == ["Website"]
    assert m["lat"].source_columns == ["Geo Latitude"]
    assert m["lng"].source_columns == ["Geo Longitude"]
    validate_mapping("accounts", t.headers, r.mapping)


def test_heuristics_zoho_invoices() -> None:
    t = read_table("inv.csv", fixture_bytes("zoho_invoices.csv"))
    r = heuristics.propose("orders", t.headers, t.sample, default_region="AE")
    m = _by_target(r.mapping)
    assert m["external_order_id"].source_columns == ["Invoice Number"]
    assert m["order_date"].source_columns == ["Invoice Date"]
    assert m["customer_name"].source_columns == ["Customer Name"]
    assert m["customer_key"].source_columns == ["Customer ID"]
    assert m["amount"].source_columns == ["Total"]
    assert m["currency"].source_columns == ["Currency Code"]
    validate_mapping("orders", t.headers, r.mapping)


def test_heuristics_arabic_headers() -> None:
    data = "اسم العميل,رقم الهاتف,العنوان,المدينة\nمؤسسة الريان,06 5551122,شارع الوحدة,الشارقة\n".encode()
    t = read_table("ar.csv", data)
    m = _by_target(heuristics.propose("accounts", t.headers, t.sample, default_region="AE").mapping)
    assert m["display_name"].source_columns == ["اسم العميل"]
    assert m["phone"].source_columns == ["رقم الهاتف"]
    assert m["address"].source_columns == ["العنوان"]
    assert m["city"].source_columns == ["المدينة"]


def test_value_sniffing_finds_unlabelled_columns() -> None:
    rows = [{"Name": f"Biz {i}", "col_x": f"050 12{i} 4567", "col_y": f"biz{i}@biz{i}.ae"} for i in range(10)]
    r = heuristics.propose("accounts", ["Name", "col_x", "col_y"], rows, default_region="AE")
    m = _by_target(r.mapping)
    assert m["phone"].source_columns == ["col_x"]
    assert m["email"].source_columns == ["col_y"]


def test_date_header_with_non_date_values_is_vetoed() -> None:
    rows = [{"Name": "A", "Date": "pending"}, {"Name": "B", "Date": "n/a"}]
    r = heuristics.propose("orders", ["Name", "Date"], rows, default_region="AE")
    assert "order_date" not in _by_target(r.mapping)
    assert r.missing_required  # order_date required for orders


def test_validate_mapping_reports_every_problem() -> None:
    bad = ColumnMapping(
        fields=[
            FieldMapping(target="display_name", source_columns=["Nope"], transform=Transform.trim),
            FieldMapping(target="order_date", source_columns=["A"], transform=Transform.trim),
            FieldMapping(target="attributes.Bad Key", source_columns=["B"], transform=Transform.trim),
            FieldMapping(target="lat", source_columns=["A", "B"], transform=Transform.coordinate),
        ]
    )
    with pytest.raises(MappingError) as exc:
        validate_mapping("accounts", ["A", "B"], bad)
    text = " | ".join(exc.value.problems)
    assert "'Nope' is not in the file" in text
    assert "unknown target 'order_date'" in text
    assert "unknown target 'attributes.Bad Key'" in text
    assert "takes a single column" in text


def test_validate_mapping_rejects_wrong_transform_and_double_use() -> None:
    m = ColumnMapping(
        fields=[
            FieldMapping(target="display_name", source_columns=["A"], transform=Transform.parse_date),
            FieldMapping(target="attributes.a_copy", source_columns=["A"], transform=Transform.trim),
        ]
    )
    with pytest.raises(MappingError) as exc:
        validate_mapping("accounts", ["A"], m)
    assert any("does not fit" in p for p in exc.value.problems)
    assert any("used by both" in p for p in exc.value.problems)


def test_apply_mapping_transforms_and_errors() -> None:
    m = ColumnMapping(
        fields=[
            FieldMapping(target="customer_name", source_columns=["Name"], transform=Transform.trim),
            FieldMapping(target="order_date", source_columns=["D"], transform=Transform.parse_date),
            FieldMapping(target="amount", source_columns=["Amt"], transform=Transform.parse_amount),
            FieldMapping(target="address", source_columns=["A1", "A2"], transform=Transform.concat),
            FieldMapping(target="phone", source_columns=["P1", "P2"], transform=Transform.phone_e164),
            FieldMapping(
                target="attributes.segment",
                source_columns=["Seg"],
                transform=Transform.split_part,
                params={"sep": "-", "index": 0},
            ),
        ]
    )
    values, errors = apply_mapping(
        m,
        {
            "Name": " Al Safa ",
            "D": "05/03/2026",
            "Amt": "AED 1,000",
            "A1": "Bldg 8",
            "A2": "Bldg 8",
            "P1": "",
            "P2": "055-1112233",
            "Seg": "Gold-2024",
        },
        default_region="AE",
    )
    assert values == {
        "customer_name": "Al Safa",
        "order_date": date(2026, 3, 5),
        "amount": Decimal("1000"),
        "address": "Bldg 8",
        "phone": "+971551112233",
        "attributes.segment": "Gold",
    }
    assert errors == {}
    values, errors = apply_mapping(m, {"Name": "X", "D": "soon", "P1": "nope"}, default_region="AE")
    assert set(errors) == {"order_date", "phone"}
    assert values == {"customer_name": "X"}


def test_reader_encodings_delimiters_and_fingerprint() -> None:
    cp1256 = "الاسم;الهاتف\nالريان;065551122\n".encode("cp1256")
    t = read_table("ar.csv", cp1256)
    assert t.headers == ["الاسم", "الهاتف"]
    assert t.rows == [{"الاسم": "الريان", "الهاتف": "065551122"}]

    buf = io.StringIO()
    csv.writer(buf, delimiter="\t").writerows([["Name", "Name", ""], ["a", "b", "c"], ["", "", ""]])
    t = read_table("x.tsv", buf.getvalue().encode())
    assert t.headers == ["Name", "Name (2)", "column_3"]
    assert len(t.rows) == 1  # blank row dropped

    assert header_fingerprint(["Name", "Phone"]) == header_fingerprint(["phone", "NAME "])
    assert header_fingerprint(["Name", "Phone"]) != header_fingerprint(["Name", "Mobile"])
