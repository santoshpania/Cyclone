"""Column-mapping contract (docs/schema.md) — validation and row application. Pure."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain import normalize
from app.imports.targets import (
    ALLOWED_TRANSFORMS,
    REQUIRED,
    ImportKind,
    Transform,
    resolve_target,
)

Origin = Literal["reused", "heuristic", "llm", "user"]


class FieldMapping(BaseModel):
    target: str
    source_columns: list[str] = Field(min_length=1)
    transform: Transform
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1, default=1.0)
    origin: Origin = "user"
    reason: str | None = None


class ColumnMapping(BaseModel):
    fields: list[FieldMapping]
    unmapped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MappingError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_mapping(kind: ImportKind, headers: list[str], mapping: ColumnMapping) -> None:
    """Raise MappingError listing every problem (unknown columns/targets, bad transforms,
    duplicate targets, missing required groups)."""
    problems: list[str] = []
    header_set = set(headers)
    seen_targets: set[str] = set()
    used_columns: dict[str, str] = {}
    for f in mapping.fields:
        tf = resolve_target(kind, f.target)
        if tf is None:
            problems.append(f"unknown target {f.target!r}")
            continue
        if f.target in seen_targets:
            problems.append(f"target {f.target!r} is mapped more than once")
        seen_targets.add(f.target)
        for col in f.source_columns:
            if col not in header_set:
                problems.append(f"column {col!r} is not in the file")
            elif col in used_columns:
                problems.append(f"column {col!r} is used by both {used_columns[col]!r} and {f.target!r}")
            else:
                used_columns[col] = f.target
        if len(f.source_columns) > 1 and not tf.multi_column:
            problems.append(f"target {f.target!r} takes a single column")
        if f.transform not in ALLOWED_TRANSFORMS[tf.value_type]:
            problems.append(f"transform {f.transform.value!r} does not fit {f.target!r} ({tf.value_type})")
        if f.transform is Transform.split_part and "index" not in f.params:
            problems.append(f"split_part on {f.target!r} needs params.index")
    for group in REQUIRED[kind]:
        if not group & seen_targets:
            problems.append(f"map at least one of: {', '.join(sorted(group))}")
    if problems:
        raise MappingError(problems)


def _cells(row: Mapping[str, Any], cols: list[str]) -> list[str]:
    out = []
    for c in cols:
        v = row.get(c)
        s = "" if v is None else str(v).strip()
        if s and s.lower() not in {"nan", "none", "null", "n/a", "-"}:
            out.append(s)
    return out


def apply_field(f: FieldMapping, row: Mapping[str, Any], *, default_region: str) -> Any:
    """Return the transformed value (None when empty). Raises ValueError on unparseable input."""
    cells = _cells(row, f.source_columns)
    if not cells:
        return None
    p = f.params
    match f.transform:
        case Transform.trim:
            return cells[0]
        case Transform.lowercase:
            return cells[0].lower()
        case Transform.coalesce:
            return cells[0]
        case Transform.concat:
            return str(p.get("sep", ", ")).join(dict.fromkeys(cells))  # de-dupe repeated parts
        case Transform.split_part:
            parts = [x.strip() for x in cells[0].split(str(p.get("sep", " ")))]
            idx = int(p["index"])
            return parts[idx] if -len(parts) <= idx < len(parts) and parts[idx] else None
        case Transform.parse_date:
            return normalize.parse_date(cells[0], dayfirst=bool(p.get("dayfirst", True)), fmt=p.get("format"))
        case Transform.parse_amount:
            return normalize.parse_amount(cells[0], decimal_sep=str(p.get("decimal_sep", ".")))
        case Transform.phone_e164:
            region = str(p.get("default_region", default_region))
            for c in cells:
                phone = normalize.normalize_phone(c, region)
                if phone:
                    return phone
            raise ValueError(f"no valid phone number in {cells!r}")
        case Transform.domain:
            return normalize.normalize_domain(cells[0])
        case Transform.coordinate:
            axis = "lat" if f.target.endswith("lat") else "lng"
            return normalize.parse_coordinate(cells[0], axis=axis)
    raise AssertionError(f.transform)


def apply_mapping(
    mapping: ColumnMapping, row: Mapping[str, Any], *, default_region: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """Map one source row. Returns (values, errors) keyed by target. A field that fails to parse
    is reported in errors and left out of values; the caller decides whether the row survives."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in mapping.fields:
        try:
            v = apply_field(f, row, default_region=default_region)
        except (ValueError, OverflowError, ArithmeticError) as exc:
            errors[f.target] = str(exc)[:200]
            continue
        if v is not None:
            values[f.target] = v
    return values, errors
