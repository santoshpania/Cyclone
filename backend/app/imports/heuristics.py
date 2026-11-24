"""First-pass column mapper: header synonyms + value sniffing. Free, deterministic, and good
enough for most exports; only what it can't place goes to the LLM."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.domain import normalize
from app.imports.mapping import ColumnMapping, FieldMapping
from app.imports.targets import REQUIRED, ImportKind, Transform, target_index

_CATALOG = Path(__file__).resolve().parent.parent / "catalogs" / "header_synonyms.json"
ACCEPT = 0.6  # below this a column is "unresolved" and goes to the LLM pass


@lru_cache
def _synonyms() -> dict[str, set[str]]:
    raw = json.loads(_CATALOG.read_text(encoding="utf-8"))
    return {k: {_norm_header(s) for s in v} for k, v in raw.items() if not k.startswith("_")}


def _norm_header(h: str) -> str:
    return normalize.fold_text(h).replace(" no ", " number ").removesuffix(" no").strip()


@dataclass
class Guess:
    target: str
    confidence: float
    reason: str


@dataclass
class HeuristicResult:
    mapping: ColumnMapping
    unresolved: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)


def _header_guesses(kind: ImportKind, header: str) -> list[Guess]:
    h = _norm_header(header)
    if not h:
        return []
    tokens = set(h.split())
    allowed = target_index(kind)
    out: list[Guess] = []
    for target, syns in _synonyms().items():
        if target not in allowed:
            continue
        if h in syns:
            out.append(Guess(target, 0.95, "header matches a known label"))
            continue
        # multi-word synonym contained in header, e.g. "Customer Name (Billing)"
        best = max((len(s) for s in syns if " " in s and s in h), default=0)
        if best:
            out.append(Guess(target, 0.8, "header contains a known label"))
        elif tokens & {s for s in syns if " " not in s and len(s) > 3}:
            out.append(Guess(target, 0.65, "header shares a keyword with a known label"))
    return out


_URL = re.compile(r"^(https?://)?(www\.)?[\w-]+(\.[\w-]+)+(/.*)?$", re.I)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ratio(values: list[str], pred: object) -> float:
    vals = [v for v in values if v.strip()]
    if not vals:
        return 0.0
    ok = 0
    for v in vals:
        with contextlib.suppress(ValueError, OverflowError, ArithmeticError):
            ok += bool(pred(v))  # type: ignore[operator]
    return ok / len(vals)


def _value_guesses(kind: ImportKind, values: list[str], region: str) -> list[Guess]:
    allowed = target_index(kind)
    out: list[Guess] = []
    if "email" in allowed and _ratio(values, _EMAIL.match) >= 0.8:
        out.append(Guess("email", 0.75, "values look like email addresses"))
    elif "website" in allowed and _ratio(values, lambda v: _URL.match(v) and "@" not in v) >= 0.8:
        out.append(Guess("website", 0.7, "values look like web addresses"))
    if "phone" in allowed and _ratio(values, lambda v: normalize.normalize_phone(v, region)) >= 0.8:
        digits_only = _ratio(values, lambda v: re.fullmatch(r"[\d\s+()\-/]{7,}", v))
        if digits_only >= 0.8:
            out.append(Guess("phone", 0.7, "values look like phone numbers"))
    if (
        "order_date" in allowed
        and _ratio(values, lambda v: re.search(r"\d", v) and normalize.parse_date(v)) >= 0.9
    ):
        out.append(Guess("order_date", 0.6, "values look like dates"))
    return out


def _sample_values(rows: list[dict[str, str]], header: str) -> list[str]:
    return [str(r.get(header) or "") for r in rows][:50]


def propose(
    kind: ImportKind, headers: list[str], sample_rows: list[dict[str, str]], *, default_region: str
) -> HeuristicResult:
    targets = target_index(kind)
    candidates: dict[str, list[Guess]] = {}
    for h in headers:
        guesses = _header_guesses(kind, h)
        values = _sample_values(sample_rows, h)
        for vg in _value_guesses(kind, values, default_region):
            match = next((g for g in guesses if g.target == vg.target), None)
            if match:
                match.confidence = min(0.99, match.confidence + 0.05)
                match.reason += "; " + vg.reason
            else:
                guesses.append(vg)
        # Value check can veto: a "date" header whose values don't parse is not a date.
        if (
            any(g.target == "order_date" for g in guesses)
            and values
            and _ratio(values, lambda v: normalize.parse_date(v)) < 0.5
        ):
            guesses = [g for g in guesses if g.target != "order_date"]
        candidates[h] = sorted(guesses, key=lambda g: -g.confidence)

    # Assign greedily by confidence; single-column targets go to the best column only.
    assigned: dict[str, list[tuple[str, Guess]]] = {}
    taken: set[str] = set()
    flat = sorted(
        ((h, g) for h, gs in candidates.items() for g in gs if g.confidence >= ACCEPT),
        key=lambda x: (-x[1].confidence, headers.index(x[0])),
    )
    for h, g in flat:
        if h in taken:
            continue
        tf = targets[g.target]
        if g.target in assigned and not tf.multi_column:
            continue
        assigned.setdefault(g.target, []).append((h, g))
        taken.add(h)

    fields: list[FieldMapping] = []
    for target, cols in assigned.items():
        tf = targets[target]
        cols.sort(key=lambda x: headers.index(x[0]))  # keep file order for concat
        transform = tf.default_transform
        if len(cols) > 1 and tf.value_type in {"text", "email"} and transform is not Transform.concat:
            transform = Transform.coalesce
        fields.append(
            FieldMapping(
                target=target,
                source_columns=[h for h, _ in cols],
                transform=transform,
                params={"default_region": default_region} if transform is Transform.phone_e164 else {},
                confidence=round(min(g.confidence for _, g in cols), 2),
                origin="heuristic",
                reason=cols[0][1].reason,
            )
        )
    unresolved = [h for h in headers if h not in taken]
    mapped_targets = {f.target for f in fields}

    missing = [" or ".join(sorted(g)) for g in REQUIRED[kind] if not g & mapped_targets]
    return HeuristicResult(
        mapping=ColumnMapping(fields=fields, unmapped=list(unresolved)),
        unresolved=unresolved,
        missing_required=missing,
    )
