"""Hand work to the queue, or run it in-process when RUN_TASKS_INLINE=true (tests, simple dev)."""

from __future__ import annotations

import contextlib
from uuid import UUID

from app.services.import_runner import run_import
from app.settings import get_settings


async def dispatch_import(workspace_id: UUID, job_id: UUID) -> None:
    if get_settings().run_tasks_inline:
        with contextlib.suppress(Exception):  # failure is recorded on the job row
            await run_import(workspace_id, job_id)
        return
    from app.workers.tasks import run_import_task

    await run_import_task.defer_async(workspace_id=str(workspace_id), job_id=str(job_id))
