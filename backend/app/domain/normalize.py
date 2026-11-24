"""Pure normalisers for names, phones, domains, dates, amounts and coordinates. No I/O beyond
reading bundled catalogs once."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import phonenumbers
import tldextract
from dateutil import parser as date_parser

_CATALOGS = Path(__file__).resolve().parent.parent / "catalogs"

# Arabic: harakat/tashkeel + superscript alef, tatweel; letter-variant folding.
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


@lru_cache
def _legal_forms() -> tuple[list[list[str]], list[str]]:
    data = json.loads((_CATALOGS / "legal_forms.json").read_text(encoding="utf-8"))
    suffixes = sorted(({tuple(fold_text(s).split()) for s in data["suffixes"]}), key=lambda t: -len(t))
    return [list(t) for t in suffixes if t], [fold_text(p) for p in data["prefixes"]]


@lru_cache
def public_mail_domains() -> frozenset[str]:
    data = json.loads((_CATALOGS / "public_mail_domains.json").read_text(encoding="utf-8"))
    return frozenset(d.lower() for d in data["domains"])


def fold_text(value: str) -> str:
    """Case/diacritic/punctuation folding shared by names and header matching."""
    s = unicodedata.normalize("NFKC", value).lower()
    s = _AR_DIACRITICS.sub("", s).translate(_AR_FOLD)
    s = s.replace(".", "")  # "l.l.c" -> "llc", "ذ.م.م" -> "ذمم"
    s = s.replace("&", " and ")
    s = _NON_WORD.sub(" ", s).replace("_", " ")
    return _SPACES.sub(" ", s).strip()


def normalize_name(value: str | None) -> str:
    """Comparable business name: folded, legal forms (LLC, FZE, ذ.م.م …) removed from the ends."""
    if not value:
        return ""
    tokens = fold_text(value).split()
    suffixes, prefixes = _legal_forms()
    changed = True
    while changed and len(tokens) > 1:
        changed = False
        for suf in suffixes:
            if len(tokens) > len(suf) and tokens[-len(suf) :] == suf:
                tokens = tokens[: -len(suf)]
                changed = True
                break
        if len(tokens) > 1 and tokens[0] in prefixes:
            tokens = tokens[1:]
            changed = True
    return " ".join(tokens)


def normalize_phone(value: str | None, default_region: str = "AE") -> str | None:
    """First plausible number in the cell, as E.164. Cells often hold "04 123 4567 / 050 ..."."""
    if not value:
        return None
    for chunk in re.split(r"[/,;|]| or ", str(value)):
        chunk = chunk.strip()
        if sum(c.isdigit() for c in chunk) < 6:
            continue
        try:
            num = phonenumbers.parse(chunk, default_region.upper())
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_possible_number(num):
            return str(phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164))
    return None


# Offline: bundled public-suffix snapshot, never fetched at runtime.
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def normalize_domain(value: str | None, *, from_email: bool = False) -> str | None:
    """Registered domain of a URL or email ("https://www.shop.example.co.uk/x" -> "example.co.uk").
    Public mailbox domains (gmail.com …) return None when the value came from an email."""
    if not value:
        return None
    raw = str(value).strip().lower()
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
        from_email = True
    raw = re.sub(r"^[a-z]+://", "", raw).split("/")[0].split("?")[0].strip(". ")
    if not raw or " " in raw:
        return None
    ext = _tld(raw)
    if not ext.domain or not ext.suffix:
        return None
    domain = f"{ext.domain}.{ext.suffix}"
    if from_email and domain in public_mail_domains():
        return None
    return domain


_EXCEL_EPOCH = date(1899, 12, 30)


def parse_date(value: str | None, *, dayfirst: bool = True, fmt: str | None = None) -> date | None:
    """Dates from ERP exports. Day-first by default (UAE/GCC convention). Accepts Excel serials."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if fmt:
        return datetime.strptime(raw, fmt).date()
    if re.fullmatch(r"\d{5}(\.\d+)?", raw):  # Excel serial day number
        serial = float(raw)
        if 20000 <= serial <= 80000:
            return _EXCEL_EPOCH + timedelta(days=int(serial))
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}([ T].*)?", raw):  # ISO is never day-first
        return date_parser.isoparse(raw[:10]).date()
    return date_parser.parse(raw, dayfirst=dayfirst).date()


_CURRENCY_NOISE = re.compile(r"[A-Za-z$€£¥₹]|د\.?إ|ر\.?س|ر\.?ق|د\.?ك|ر\.?ع|د\.?ب", re.UNICODE)


def parse_amount(value: str | None, *, decimal_sep: str = ".") -> Decimal | None:
    """ "AED 1,234.50", "(1.234,50)", "1 234,5 د.إ" -> Decimal. Parentheses mean negative."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    negative = (raw.startswith("(") and raw.endswith(")")) or raw.startswith("-") or raw.endswith("-")
    s = _CURRENCY_NOISE.sub("", raw).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))
    s = re.sub(r"[()\s'\-+]", "", s)
    s = s.replace(".", "").replace(",", ".") if decimal_sep == "," else s.replace(",", "")
    if not s:
        return None
    try:
        amount = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value!r}") from exc
    return -amount if negative else amount


def parse_coordinate(value: str | None, *, axis: str) -> float | None:
    if value is None or not str(value).strip():
        return None
    v = float(str(value).strip().replace(",", "."))
    limit = 90.0 if axis == "lat" else 180.0
    if not -limit <= v <= limit:
        raise ValueError(f"{axis} out of range: {v}")
    return v
