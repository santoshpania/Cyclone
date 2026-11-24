"""Execute a confirmed import: parse rows, normalise, geocode, resolve entities, load orders.

Idempotent: each row becomes a source_record keyed by a hash of its content, so re-running
the same job (or re-uploading the same file) does not create duplicates. Rows are processed in
chunks, each in its own transaction, so a large file doesn't hold one long transaction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.geocoding import MeteredGeocoder, configured_geocoders
from app.adapters.storage import get_storage
from app.db.session import tenant_session
from app.domain.normalize import normalize_domain, normalize_name
from app.imports.mapping import ColumnMapping, apply_mapping, validate_mapping
from app.imports.reader import read_table
from app.imports.targets import ImportKind
from app.services.orders import refresh_rollups
from app.services.resolution import AccountInput, resolve_and_write
from app.services.usage_meter import BudgetExceeded, UsageMeter

CHUNK = 500


@dataclass
class ImportStats:
    rows_total: int = 0
    rows_imported: int = 0
    rows_skipped_duplicate: int = 0
    rows_failed: int = 0
    accounts_created: int = 0
    accounts_matched: int = 0
    reviews_created: int = 0
    orders_inserted: int = 0
    geocoded: int = 0
    geocode_failed: int = 0
    geocode_skipped_budget: int = 0


class RowError(ValueError):
    pass


def row_key(row: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _json_default(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    raise TypeError(type(v))


def _address(values: dict[str, Any]) -> str | None:
    parts = [values.get("address"), values.get("city"), values.get("country")]
    joined = ", ".join(str(p) for p in parts if p)
    return joined or None


def _attributes(values: dict[str, Any]) -> dict[str, Any]:
    attrs = {k.removeprefix("attributes."): v for k, v in values.items() if k.startswith("attributes.")}
    for k in ("email", "display_name_ar", "activity", "city", "country"):
        if values.get(k):
            attrs[k] = values[k]
    return attrs


async def _account_input(
    values: dict[str, Any],
    *,
    kind: ImportKind,
    status: str,
    geocoder: MeteredGeocoder | None,
    stats: ImportStats,
) -> AccountInput:
    name = values.get("display_name") or values.get("customer_name") or values.get("display_name_ar")
    if not name:
        raise RowError("no business name")
    norm = normalize_name(str(name))
    if not norm:
        raise RowError(f"business name {name!r} is empty after normalisation")
    domain = values.get("website") or normalize_domain(values.get("email"), from_email=True)
    lat, lng = values.get("lat"), values.get("lng")
    geocode: dict[str, Any] | None = None
    if lat is not None and lng is not None:
        if lat == 0 and lng == 0:
            lat = lng = None
        else:
            geocode = {
                "provider": "source_file",
                "precision": "source",
                "confidence": 1.0,
                "storable_until": None,
            }
    address = _address(values)
    if lat is None and address and geocoder is not None:
        try:
            r = await geocoder.geocode(address)
        except BudgetExceeded:
            stats.geocode_skipped_budget += 1
            r = None
        if r:
            lat, lng, geocode = r.lat, r.lng, r.as_json()
            stats.geocoded += 1
        else:
            stats.geocode_failed += 1
    return AccountInput(
        display_name=str(name),
        name_norm=norm,
        status=status,
        address=address,
        lat=lat,
        lng=lng,
        geocode=geocode,
        phone_e164=values.get("phone"),
        website_domain=domain,
        external_crm_id=values.get("external_crm_id") or values.get("customer_key"),
        registry_ref=values.get("registry_ref"),
        attributes=_attributes(values) if kind != "orders" else {},
        provenance_source="registry" if kind == "registry" else "csv_import",
    )


async def _insert_source_record(
    session: AsyncSession, workspace_id: UUID, job_id: UUID, source: str, key: str, payload: dict[str, Any]
) -> UUID | None:
    row = await session.execute(
        text("""
        INSERT INTO source_records (workspace_id, source, source_key, import_job_id, payload)
        VALUES (:w, :s, :k, :j, CAST(:p AS jsonb))
        ON CONFLICT (workspace_id, source, source_key) DO NOTHING RETURNING id
    """),
        {
            "w": workspace_id,
            "s": source,
            "k": key,
            "j": job_id,
            "p": json.dumps(payload, ensure_ascii=False, default=_json_default),
        },
    )
    sid = row.scalar_one_or_none()
    return UUID(str(sid)) if sid else None


async def _process_row(
    session: AsyncSession,
    workspace_id: UUID,
    job_id: UUID,
    kind: ImportKind,
    mapping: ColumnMapping,
    row: dict[str, str],
    region: str,
    geocoder: MeteredGeocoder | None,
    stats: ImportStats,
    touched: set[UUID],
) -> None:
    values, errors = apply_mapping(mapping, row, default_region=region)
    critical = {"display_name", "customer_name", "order_date", "amount"} & errors.keys()
    if critical:
        raise RowError("; ".join(f"{k}: {errors[k]}" for k in sorted(critical)))
    key = row_key(row)
    source = "registry" if kind == "registry" else "csv_import"
    payload = {"row": row, "values": values, "field_errors": errors}
    sid = await _insert_source_record(session, workspace_id, job_id, source, key, payload)
    if sid is None:
        stats.rows_skipped_duplicate += 1
        return

    if kind == "orders":
        if not values.get("order_date"):
            raise RowError("order_date: missing")
        acc_input = await _account_input(values, kind=kind, status="customer", geocoder=geocoder, stats=stats)
    elif kind == "accounts":
        acc_input = await _account_input(values, kind=kind, status="customer", geocoder=geocoder, stats=stats)
    else:  # registry: kept as evidence only; Phase 2 matches it against discovered businesses
        stats.rows_imported += 1
        return

    outcome = await resolve_and_write(session, workspace_id, sid, acc_input)
    stats.accounts_created += outcome.created
    stats.accounts_matched += not outcome.created
    stats.reviews_created += len(outcome.decision.reviews)

    if kind == "orders":
        order_id = values.get("external_order_id") or f"row:{key[:32]}"
        res = await session.execute(
            text("""
            INSERT INTO historical_orders (workspace_id, account_id, import_job_id, external_order_id, order_date,
                                           amount, currency, raw)
            VALUES (:w, :a, :j, :o, :d, :amt, :cur, CAST(:raw AS jsonb))
            ON CONFLICT (workspace_id, external_order_id) DO NOTHING RETURNING id
        """),
            {
                "w": workspace_id,
                "a": outcome.account_id,
                "j": job_id,
                "o": str(order_id),
                "d": values["order_date"],
                "amt": values.get("amount"),
                "cur": (str(values["currency"]).upper()[:3] if values.get("currency") else None),
                "raw": json.dumps(row, ensure_ascii=False),
            },
        )
        stats.orders_inserted += res.scalar_one_or_none() is not None
        touched.add(outcome.account_id)
    stats.rows_imported += 1


async def run_import(workspace_id: UUID, job_id: UUID) -> ImportStats:
    stats = ImportStats()
    async with tenant_session(workspace_id) as s:
        job = (
            await s.execute(
                text("""
            SELECT j.kind, j.filename, j.storage_uri, j.headers, j.confirmed_mapping, w.default_phone_region,
                   coalesce((w.settings->>'lapsed_after_months')::int, 12) AS lapsed_months
            FROM import_jobs j JOIN workspaces w ON w.id = j.workspace_id WHERE j.id = :id FOR UPDATE OF j
        """),
                {"id": job_id},
            )
        ).one()
        if job.confirmed_mapping is None:
            raise ValueError("mapping not confirmed")
        await s.execute(text("UPDATE import_jobs SET status = 'importing' WHERE id = :id"), {"id": job_id})
    kind: ImportKind = job.kind
    mapping = ColumnMapping.model_validate(job.confirmed_mapping)
    region = str(job.default_phone_region).strip()
    failed: list[dict[str, str]] = []
    touched: set[UUID] = set()
    try:
        table = read_table(job.filename, await get_storage().get(job.storage_uri))
        validate_mapping(kind, table.headers, mapping)
        stats.rows_total = len(table.rows)
        chain = configured_geocoders()
        from app.settings import get_settings

        country_codes = get_settings().geocode_country_codes
        for start in range(0, len(table.rows), CHUNK):
            async with tenant_session(workspace_id) as s:
                geocoder = (
                    MeteredGeocoder(UsageMeter(s, workspace_id), chain, country_codes) if chain else None
                )
                for row in table.rows[start : start + CHUNK]:
                    try:
                        async with s.begin_nested():  # one bad row doesn't poison the chunk
                            await _process_row(
                                s, workspace_id, job_id, kind, mapping, row, region, geocoder, stats, touched
                            )
                    except RowError as exc:
                        stats.rows_failed += 1
                        failed.append({**row, "_error": str(exc)})
        if touched or kind == "orders":
            async with tenant_session(workspace_id) as s:
                await refresh_rollups(s, list(touched), lapsed_after_months=int(job.lapsed_months))
        report_uri = (
            await _write_error_report(workspace_id, job_id, table.headers, failed) if failed else None
        )
        async with tenant_session(workspace_id) as s:
            await s.execute(
                text("""
                UPDATE import_jobs SET status = 'succeeded', stats = CAST(:st AS jsonb), error_report_uri = :r
                WHERE id = :id
            """),
                {"id": job_id, "st": json.dumps(asdict(stats)), "r": report_uri},
            )
    except Exception as exc:
        async with tenant_session(workspace_id) as s:
            await s.execute(
                text("""
                UPDATE import_jobs SET status = 'failed', stats = CAST(:st AS jsonb) WHERE id = :id
            """),
                {"id": job_id, "st": json.dumps({**asdict(stats), "error": str(exc)[:500]})},
            )
        raise
    return stats


async def _write_error_report(
    workspace_id: UUID, job_id: UUID, headers: list[str], rows: list[dict[str, str]]
) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[*headers, "_error"], extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    data = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel shows Arabic correctly
    return await get_storage().put(f"{workspace_id}/imports/{job_id}/errors.csv", data, "text/csv")
