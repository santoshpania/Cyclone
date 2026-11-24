from datetime import date
from decimal import Decimal

import pytest

from app.domain.normalize import (
    normalize_domain,
    normalize_name,
    normalize_phone,
    parse_amount,
    parse_coordinate,
    parse_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Al Noor Trading L.L.C", "al noor trading"),
        ("AL NOOR TRADING LLC", "al noor trading"),
        ("Marina Crest FZ-LLC", "marina crest"),
        ("Falcon Star FZE", "falcon star"),
        ("Gulf Pearl Est.", "gulf pearl"),
        ("Desert Rose Co. LLC", "desert rose"),
        ("Sand & Sea Services", "sand and sea services"),
        ("مؤسسة الريان", "الريان"),
        ("شركة النور ذ.م.م", "النور"),
        ("الرَّيّان", "الريان"),  # diacritics removed
        ("LLC", "llc"),  # never strip a name down to nothing
        ("", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("050 123 4567", "+971501234567"),
        ("+971 4 222 3344", "+97142223344"),
        ("00971 4 885 1200", "+97148851200"),
        ("02-6661234", "+97126661234"),
        ("04 2678900 / 050 4447788", "+97142678900"),
        ("not available", None),
        ("", None),
        ("123", None),
    ],
)
def test_normalize_phone_uae(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw, "AE") == expected


def test_normalize_phone_other_region() -> None:
    assert normalize_phone("(212) 555-0100", "US") == "+12125550100"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.alnoortrading.ae/contact", "alnoortrading.ae"),
        ("falconstar.com", "falconstar.com"),
        ("shop.example.co.uk", "example.co.uk"),
        ("sales@bluedune.ae", "bluedune.ae"),
        ("gulfpearl@gmail.com", None),  # mailbox provider says nothing about the business
        ("not a url", None),
        ("", None),
    ],
)
def test_normalize_domain(raw: str, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("05/03/2026", date(2026, 3, 5)),  # day-first
        ("2026-03-05", date(2026, 3, 5)),  # ISO never day-first
        ("5 Mar 2026", date(2026, 3, 5)),
        ("46086", date(2026, 3, 5)),  # Excel serial
        ("", None),
    ],
)
def test_parse_date(raw: str, expected: date | None) -> None:
    assert parse_date(raw) == expected


def test_parse_date_explicit_format_and_bad_value() -> None:
    assert parse_date("03/05/2026", fmt="%m/%d/%Y") == date(2026, 3, 5)
    with pytest.raises(ValueError):
        parse_date("not a date")


@pytest.mark.parametrize(
    ("raw", "sep", "expected"),
    [
        ("AED 1,250.00", ".", Decimal("1250.00")),
        ("1 234,5 د.إ", ",", Decimal("1234.5")),
        ("(980.50)", ".", Decimal("-980.50")),
        ("$12", ".", Decimal("12")),
        ("١٢٣٫٥", ".", Decimal("123.5")),  # Arabic-Indic digits
        ("", ".", None),
    ],
)
def test_parse_amount(raw: str, sep: str, expected: Decimal | None) -> None:
    assert parse_amount(raw, decimal_sep=sep) == expected


def test_parse_amount_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_amount("12.3.4")


def test_parse_coordinate_range() -> None:
    assert parse_coordinate("25,2048", axis="lat") == pytest.approx(25.2048)
    with pytest.raises(ValueError):
        parse_coordinate("95", axis="lat")
