"""What an imported column can map to, per import kind. Generic business fields only —
anything else is kept as `attributes.<key>` (CLAUDE.md rule 1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ImportKind = Literal["accounts", "orders", "registry"]
ValueType = Literal["text", "date", "amount", "phone", "domain", "email", "coordinate", "currency"]


class Transform(StrEnum):
    trim = "trim"
    concat = "concat"
    split_part = "split_part"
    parse_date = "parse_date"
    parse_amount = "parse_amount"
    phone_e164 = "phone_e164"
    domain = "domain"
    lowercase = "lowercase"
    coalesce = "coalesce"
    coordinate = "coordinate"


@dataclass(frozen=True)
class TargetField:
    name: str
    label: str
    value_type: ValueType
    default_transform: Transform
    multi_column: bool = False  # several source columns may be combined (concat/coalesce)


_COMMON_LOCATION = [
    TargetField("address", "Address", "text", Transform.concat, multi_column=True),
    TargetField("city", "City / emirate / district", "text", Transform.concat, multi_column=True),
    TargetField("country", "Country", "text", Transform.trim),
    TargetField("lat", "Latitude", "coordinate", Transform.coordinate),
    TargetField("lng", "Longitude", "coordinate", Transform.coordinate),
]
_CONTACT = [
    TargetField("phone", "Phone", "phone", Transform.phone_e164, multi_column=True),
    TargetField("email", "Email", "email", Transform.lowercase, multi_column=True),
    TargetField("website", "Website", "domain", Transform.domain),
]

TARGETS: dict[ImportKind, list[TargetField]] = {
    "accounts": [
        TargetField("display_name", "Business name", "text", Transform.trim),
        TargetField("display_name_ar", "Business name (Arabic)", "text", Transform.trim),
        TargetField("external_crm_id", "Your customer ID", "text", Transform.trim),
        *_COMMON_LOCATION,
        *_CONTACT,
    ],
    "orders": [
        TargetField("external_order_id", "Invoice / order number", "text", Transform.trim),
        TargetField("order_date", "Invoice / order date", "date", Transform.parse_date),
        TargetField("amount", "Amount", "amount", Transform.parse_amount),
        TargetField("currency", "Currency", "currency", Transform.trim),
        TargetField("customer_key", "Customer ID", "text", Transform.trim),
        TargetField("customer_name", "Customer name", "text", Transform.trim),
        *_COMMON_LOCATION,
        TargetField("phone", "Customer phone", "phone", Transform.phone_e164, multi_column=True),
    ],
    "registry": [
        TargetField("registry_ref", "Licence / registration number", "text", Transform.trim),
        TargetField("display_name", "Trade name", "text", Transform.trim),
        TargetField("display_name_ar", "Trade name (Arabic)", "text", Transform.trim),
        TargetField("activity", "Licensed activity", "text", Transform.concat, multi_column=True),
        *_COMMON_LOCATION,
        *_CONTACT,
    ],
}

# At least one target from each group must be mapped before an import can be confirmed.
REQUIRED: dict[ImportKind, list[set[str]]] = {
    "accounts": [{"display_name", "display_name_ar"}],
    "orders": [{"order_date"}, {"customer_key", "customer_name"}],
    "registry": [{"display_name", "display_name_ar"}],
}

# Transforms that make sense for each value type (the first is the default).
ALLOWED_TRANSFORMS: dict[ValueType, set[Transform]] = {
    "text": {Transform.trim, Transform.concat, Transform.split_part, Transform.coalesce, Transform.lowercase},
    "date": {Transform.parse_date},
    "amount": {Transform.parse_amount},
    "phone": {Transform.phone_e164},
    "domain": {Transform.domain},
    "email": {Transform.lowercase, Transform.trim, Transform.coalesce},
    "coordinate": {Transform.coordinate},
    "currency": {Transform.trim},
}

ATTRIBUTE_KEY = re.compile(r"^attributes\.[a-z][a-z0-9_]{0,48}$")


def target_index(kind: ImportKind) -> dict[str, TargetField]:
    return {t.name: t for t in TARGETS[kind]}


def resolve_target(kind: ImportKind, name: str) -> TargetField | None:
    """Known target, or a free-form attribute (`attributes.<snake_case>`) stored as text."""
    if name in target_index(kind):
        return target_index(kind)[name]
    if ATTRIBUTE_KEY.match(name):
        return TargetField(name, name.removeprefix("attributes."), "text", Transform.trim, multi_column=True)
    return None


def attribute_key_for(header: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")[:48] or "column"
    if not key[0].isalpha():
        key = f"col_{key}"[:48]
    return f"attributes.{key}"
