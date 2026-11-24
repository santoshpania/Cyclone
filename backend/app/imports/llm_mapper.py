"""Second-pass column mapper: Gemini places the columns the heuristics couldn't.

The model chooses from the allowed targets and the transform enum only. Its output is
validated, capped in confidence, and always shown to the user for confirmation.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.adapters.llm.base import LLMClient, LLMResult
from app.imports.mapping import ColumnMapping, FieldMapping
from app.imports.targets import (
    ALLOWED_TRANSFORMS,
    ImportKind,
    Transform,
    resolve_target,
    target_index,
)

PROMPT_NAME = "import_column_mapping_v1"
MAX_LLM_CONFIDENCE = 0.9
SAMPLES_PER_COLUMN = 5


class LLMParam(BaseModel):
    key: str
    value: str


class LLMColumnSuggestion(BaseModel):
    column: str
    target: str | None = Field(
        description="A target name from the list, 'attributes.<snake_case>' to keep it, or null to ignore"
    )
    transform: Transform | None = None
    params: list[LLMParam] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=200)


class LLMMappingResponse(BaseModel):
    suggestions: list[LLMColumnSuggestion]


def build_prompt(
    kind: ImportKind,
    headers: list[str],
    unresolved: list[str],
    already_mapped: ColumnMapping,
    sample_rows: list[dict[str, str]],
    *,
    include_samples: bool,
    default_region: str,
) -> str:
    targets = [
        {
            "name": t.name,
            "label": t.label,
            "type": t.value_type,
            "transforms": sorted(x.value for x in ALLOWED_TRANSFORMS[t.value_type]),
            "multi_column": t.multi_column,
        }
        for t in target_index(kind).values()
    ]
    taken = {f.target: f.source_columns for f in already_mapped.fields}
    columns = []
    for col in unresolved:
        entry: dict[str, object] = {"column": col}
        if include_samples:
            vals = [r.get(col, "") for r in sample_rows if r.get(col, "")][:SAMPLES_PER_COLUMN]
            entry["sample_values"] = [v[:80] for v in vals]
        columns.append(entry)
    return (
        "You map spreadsheet columns from a business's ERP/CRM export onto a fixed import schema.\n"
        f"Import kind: {kind}. Default phone region: {default_region}.\n"
        "Rules:\n"
        "- Choose `target` ONLY from the target list, or use 'attributes.<snake_case_name>' to keep a column "
        "that holds useful business information not covered by a target, or null for junk/internal columns.\n"
        "- Choose `transform` ONLY from that target's allowed transforms.\n"
        "- Do not assign a target that is already mapped unless it is multi_column.\n"
        "- params are key/value strings, e.g. parse_date: dayfirst=true or format=%d/%m/%Y; "
        "parse_amount: decimal_sep=','; split: sep=' ', index=0.\n"
        "- Columns may be in English or Arabic. Be conservative: low confidence if unsure.\n\n"
        f"Targets: {json.dumps(targets, ensure_ascii=False)}\n"
        f"Already mapped: {json.dumps(taken, ensure_ascii=False)}\n"
        f"All headers in file order: {json.dumps(headers, ensure_ascii=False)}\n"
        f"Columns to map: {json.dumps(columns, ensure_ascii=False)}\n"
    )


def merge_suggestions(
    kind: ImportKind,
    headers: list[str],
    base: ColumnMapping,
    result: LLMResult[LLMMappingResponse],
    unresolved: list[str],
) -> ColumnMapping:
    """Fold validated LLM suggestions into the heuristic mapping. Invalid suggestions are
    dropped with a warning, never trusted."""
    fields = [f.model_copy() for f in base.fields]
    by_target = {f.target: f for f in fields}
    used = {c for f in fields for c in f.source_columns}
    warnings = list(base.warnings)
    placed: set[str] = set()
    for s in result.value.suggestions:
        if s.column not in unresolved or s.column in used:
            continue
        if s.target is None:
            continue
        tf = resolve_target(kind, s.target)
        if tf is None:
            warnings.append(f"ignored AI suggestion for {s.column!r}: unknown target {s.target!r}")
            continue
        transform = s.transform or tf.default_transform
        if transform not in ALLOWED_TRANSFORMS[tf.value_type]:
            transform = tf.default_transform
        params = {p.key: _coerce(p.value) for p in s.params}
        conf = round(min(s.confidence, MAX_LLM_CONFIDENCE), 2)
        existing = by_target.get(s.target)
        if existing is not None:
            if not tf.multi_column:
                warnings.append(f"AI suggested {s.column!r} → {s.target!r}, which is already mapped")
                continue
            existing.source_columns = sorted([*existing.source_columns, s.column], key=headers.index)
            existing.confidence = min(existing.confidence, conf)
        else:
            fm = FieldMapping(
                target=s.target,
                source_columns=[s.column],
                transform=transform,
                params=params,
                confidence=conf,
                origin="llm",
                reason=s.reason,
            )
            fields.append(fm)
            by_target[s.target] = fm
        used.add(s.column)
        placed.add(s.column)
    unmapped = [c for c in base.unmapped if c not in placed]
    return ColumnMapping(fields=fields, unmapped=unmapped, warnings=warnings)


def _coerce(v: str) -> object:
    low = v.strip().lower()
    if low in {"true", "false"}:
        return low == "true"
    if low.lstrip("-").isdigit():
        return int(low)
    return v


async def suggest(
    client: LLMClient,
    kind: ImportKind,
    headers: list[str],
    unresolved: list[str],
    base: ColumnMapping,
    sample_rows: list[dict[str, str]],
    *,
    include_samples: bool,
    default_region: str,
) -> tuple[ColumnMapping, LLMResult[LLMMappingResponse]]:
    prompt = build_prompt(
        kind,
        headers,
        unresolved,
        base,
        sample_rows,
        include_samples=include_samples,
        default_region=default_region,
    )
    result = await client.generate(PROMPT_NAME, prompt, LLMMappingResponse, max_output_tokens=2000)
    return merge_suggestions(kind, headers, base, result, unresolved), result
