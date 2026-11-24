"""Propose a column mapping for an upload: reuse → heuristics → LLM (only for what's left)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import get_llm_client
from app.adapters.llm.base import LLMError, estimate_tokens
from app.imports import heuristics, llm_mapper
from app.imports.mapping import ColumnMapping, MappingError, validate_mapping
from app.imports.targets import ImportKind
from app.services.usage_meter import BudgetExceeded, UsageMeter
from app.settings import get_settings


async def previous_confirmed(
    session: AsyncSession, kind: ImportKind, fingerprint: str, headers: list[str]
) -> ColumnMapping | None:
    row = await session.execute(
        text("""
        SELECT confirmed_mapping FROM import_jobs
        WHERE kind = :k AND header_fingerprint = :fp AND confirmed_mapping IS NOT NULL
        ORDER BY confirmed_at DESC LIMIT 1
    """),
        {"k": kind, "fp": fingerprint},
    )
    raw = row.scalar_one_or_none()
    if raw is None:
        return None
    mapping = ColumnMapping.model_validate(raw)
    # Same fingerprint ignores case/order, so re-point columns at this file's exact header spelling.
    by_fold = {h.strip().lower(): h for h in headers}
    for f in mapping.fields:
        f.source_columns = [by_fold.get(c.strip().lower(), c) for c in f.source_columns]
        f.origin, f.confidence = "reused", 1.0
    mapping.unmapped = [h for h in headers if h not in {c for f in mapping.fields for c in f.source_columns}]
    try:
        validate_mapping(kind, headers, mapping)
    except MappingError:
        return None
    mapping.warnings = ["Reused the mapping you confirmed for a previous file with the same columns."]
    return mapping


async def propose_mapping(
    session: AsyncSession,
    workspace_id: UUID,
    kind: ImportKind,
    headers: list[str],
    sample_rows: list[dict[str, str]],
    fingerprint: str,
    default_region: str,
) -> ColumnMapping:
    reused = await previous_confirmed(session, kind, fingerprint, headers)
    if reused is not None:
        return reused

    h = heuristics.propose(kind, headers, sample_rows, default_region=default_region)
    mapping = h.mapping
    if not h.unresolved and not h.missing_required:
        return mapping

    client = get_llm_client()
    if client is None:
        mapping.warnings.append(
            "AI column mapping is off (no GEMINI_API_KEY); unmatched columns need manual mapping."
        )
        return mapping

    settings = get_settings()
    prompt = llm_mapper.build_prompt(
        kind,
        headers,
        h.unresolved,
        mapping,
        sample_rows,
        include_samples=settings.llm_send_sample_values,
        default_region=default_region,
    )
    meter = UsageMeter(session, workspace_id)
    try:
        await meter.reserve("gemini", "flash_input_token", estimate_tokens(prompt))
        await meter.reserve("gemini", "flash_output_token", 2000)
        mapping, _ = await llm_mapper.suggest(
            client,
            kind,
            headers,
            h.unresolved,
            mapping,
            sample_rows,
            include_samples=settings.llm_send_sample_values,
            default_region=default_region,
        )
    except BudgetExceeded as exc:
        mapping.warnings.append(f"AI column mapping skipped: {exc}.")
    except LLMError as exc:
        mapping.warnings.append(
            f"AI column mapping failed ({exc.__class__.__name__}); map remaining columns manually."
        )
    return mapping
