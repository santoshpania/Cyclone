from __future__ import annotations

from uuid import UUID

from app.services.import_runner import run_import
from app.workers.app import app


@app.task(name="run_import", queue="imports", retry=False)
async def run_import_task(workspace_id: str, job_id: str) -> None:
    # Failures are recorded on import_jobs.status/stats; the user re-runs after fixing the mapping.
    await run_import(UUID(workspace_id), UUID(job_id))
