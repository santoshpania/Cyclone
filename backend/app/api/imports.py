from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text

from app.adapters.storage import get_storage
from app.api.deps import Ws
from app.imports.mapping import ColumnMapping, MappingError, validate_mapping
from app.imports.reader import UnreadableFile, header_fingerprint, read_table
from app.imports.targets import ALLOWED_TRANSFORMS, REQUIRED, TARGETS, ImportKind
from app.services.mapping_proposer import propose_mapping
from app.settings import get_settings
from app.workers.dispatch import dispatch_import

router = APIRouter(prefix="/workspaces/{workspace_id}/imports", tags=["imports"])
meta_router = APIRouter(prefix="/meta", tags=["meta"])

ALLOWED_EXT = (".csv", ".txt", ".tsv", ".xlsx", ".xlsm")


class ImportJobOut(BaseModel):
    id: UUID
    kind: ImportKind
    filename: str
    status: str
    headers: list[str]
    sample_rows: list[dict[str, str]]
    row_count: int | None
    proposed_mapping: ColumnMapping | None
    confirmed_mapping: ColumnMapping | None
    stats: dict[str, Any] | None
    has_error_report: bool
    created_at: datetime


_COLS = """id, kind, filename, status, headers, sample_rows, row_count, proposed_mapping, confirmed_mapping,
           stats, error_report_uri IS NOT NULL AS has_error_report, created_at"""


def _out(r: Any) -> ImportJobOut:
    return ImportJobOut(
        id=r.id,
        kind=r.kind,
        filename=r.filename,
        status=r.status,
        headers=list(r.headers),
        sample_rows=r.sample_rows,
        row_count=r.row_count,
        proposed_mapping=ColumnMapping.model_validate(r.proposed_mapping) if r.proposed_mapping else None,
        confirmed_mapping=ColumnMapping.model_validate(r.confirmed_mapping) if r.confirmed_mapping else None,
        stats=r.stats,
        has_error_report=r.has_error_report,
        created_at=r.created_at,
    )


async def _get(ws: Ws, job_id: UUID) -> Any:
    row = (
        await ws.session.execute(text(f"SELECT {_COLS} FROM import_jobs WHERE id = :id"), {"id": job_id})
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "import not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    ws: Ws,
    file: Annotated[UploadFile, File()],
    kind: Annotated[ImportKind, Form()],
) -> ImportJobOut:
    """Upload a CSV/XLSX export. The file is parsed and a column mapping is proposed;
    nothing is imported until the mapping is confirmed."""
    ws.require("manager")
    settings = get_settings()
    filename = (file.filename or "upload.csv").rsplit("/", 1)[-1][:200]
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"upload one of: {', '.join(ALLOWED_EXT)}"
        )
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"file is larger than {settings.max_upload_mb} MB"
        )
    try:
        table = read_table(filename, data)
    except UnreadableFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    job_id = uuid4()
    uri = await get_storage().put(
        f"{ws.workspace_id}/imports/{job_id}/{filename}",
        data,
        file.content_type or "application/octet-stream",
    )
    fp = header_fingerprint(table.headers)
    region = (
        (
            await ws.session.execute(
                text("SELECT default_phone_region FROM workspaces WHERE id = :w"), {"w": ws.workspace_id}
            )
        )
        .scalar_one()
        .strip()
    )
    mapping = await propose_mapping(
        ws.session, ws.workspace_id, kind, table.headers, table.sample, fp, region
    )
    await ws.session.execute(
        text("""
        INSERT INTO import_jobs (id, workspace_id, kind, filename, storage_uri, header_fingerprint, headers,
                                 sample_rows, row_count, proposed_mapping, status)
        VALUES (:id, :w, :k, :fn, :uri, :fp, :h, CAST(:s AS jsonb), :n, CAST(:pm AS jsonb), 'mapping_proposed')
    """),
        {
            "id": job_id,
            "w": ws.workspace_id,
            "k": kind,
            "fn": filename,
            "uri": uri,
            "fp": fp,
            "h": table.headers,
            "s": json.dumps(table.sample, ensure_ascii=False),
            "n": len(table.rows),
            "pm": mapping.model_dump_json(),
        },
    )
    return _out(await _get(ws, job_id))


@router.get("")
async def list_imports(ws: Ws, limit: int = 50) -> list[ImportJobOut]:
    rows = await ws.session.execute(
        text(f"SELECT {_COLS} FROM import_jobs ORDER BY created_at DESC LIMIT :l"),
        {"l": min(max(limit, 1), 200)},
    )
    return [_out(r) for r in rows]


@router.get("/{job_id}")
async def get_import(ws: Ws, job_id: UUID) -> ImportJobOut:
    return _out(await _get(ws, job_id))


@router.put("/{job_id}/mapping")
async def confirm_mapping(ws: Ws, job_id: UUID, body: ColumnMapping) -> ImportJobOut:
    """Confirm (and optionally edit) the mapping. Required before the import can run."""
    ws.require("manager")
    job = await _get(ws, job_id)
    if job.status not in {"mapping_proposed", "mapping_confirmed", "failed"}:
        raise HTTPException(status.HTTP_409_CONFLICT, f"import is {job.status}")
    try:
        validate_mapping(job.kind, list(job.headers), body)
    except MappingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"problems": exc.problems}) from exc
    mapped = {c for f in body.fields for c in f.source_columns}
    body.unmapped = [h for h in job.headers if h not in mapped]
    await ws.session.execute(
        text("""
        UPDATE import_jobs SET confirmed_mapping = CAST(:m AS jsonb), confirmed_by = :u, confirmed_at = now(),
               status = 'mapping_confirmed' WHERE id = :id
    """),
        {"m": body.model_dump_json(), "u": ws.user.id, "id": job_id},
    )
    return _out(await _get(ws, job_id))


@router.post("/{job_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run(ws: Ws, job_id: UUID, background: BackgroundTasks) -> ImportJobOut:
    """Queue the import. It starts after this request's transaction has committed."""
    ws.require("manager")
    job = await _get(ws, job_id)
    if job.status not in {"mapping_confirmed", "failed"} or job.confirmed_mapping is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "confirm the column mapping first")
    background.add_task(dispatch_import, ws.workspace_id, job_id)
    return _out(job)


@router.get("/{job_id}/errors", response_class=Response)
async def error_report(ws: Ws, job_id: UUID) -> Response:
    uri = (
        await ws.session.execute(
            text("SELECT error_report_uri FROM import_jobs WHERE id = :id"), {"id": job_id}
        )
    ).scalar_one_or_none()
    if not uri:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no error report")
    data = await get_storage().get(uri)
    return Response(
        data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import-{job_id}-errors.csv"'},
    )


class TargetOut(BaseModel):
    name: str
    label: str
    value_type: str
    default_transform: str
    allowed_transforms: list[str]
    multi_column: bool


class ImportSchemaOut(BaseModel):
    kind: ImportKind
    targets: list[TargetOut]
    required_groups: list[list[str]]
    attribute_prefix: Literal["attributes."] = "attributes."


@meta_router.get("/import-schema/{kind}")
async def import_schema(kind: ImportKind) -> ImportSchemaOut:
    return ImportSchemaOut(
        kind=kind,
        targets=[
            TargetOut(
                name=t.name,
                label=t.label,
                value_type=t.value_type,
                default_transform=t.default_transform.value,
                allowed_transforms=sorted(x.value for x in ALLOWED_TRANSFORMS[t.value_type]),
                multi_column=t.multi_column,
            )
            for t in TARGETS[kind]
        ],
        required_groups=[sorted(g) for g in REQUIRED[kind]],
    )
