"""procrastinate app (Postgres-backed queue). Run a worker with:
uv run procrastinate --app=app.workers.app.app worker
"""

from __future__ import annotations

import procrastinate

from app.settings import get_settings

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().database_url),
    import_paths=["app.workers.tasks"],
)
