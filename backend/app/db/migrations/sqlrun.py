"""Run raw multi-statement SQL through the driver connection, bypassing placeholder parsing
(PL/pgSQL `RAISE '... %'` and the pg_trgm `%` operator would otherwise be misread)."""

from typing import Any

from alembic import op


def run_sql(sql: str) -> Any:
    return op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def fetch_all(sql: str) -> list[tuple[Any, ...]]:
    return list(run_sql(sql).fetchall())
