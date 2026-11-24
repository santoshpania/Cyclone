"""Mandatory guard tests (CLAUDE.md). Do not delete."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import tenant_session
from app.services.usage_meter import BudgetExceeded, UsageMeter
from tests.conftest import APP_URL, migrate, recreate_database


def _seed_two_workspaces(conn: psycopg.Connection[Any]) -> tuple[str, str]:
    a, b = str(uuid4()), str(uuid4())
    conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, 'A'), (%s, 'B')", (a, b))
    conn.execute(
        "INSERT INTO accounts (workspace_id, status, display_name, name_norm) VALUES (%s, 'prospect', 'x', 'x')",
        (a,),
    )
    return a, b


async def test_rls_isolation_including_unset_setting(db: str, owner_conn: psycopg.Connection[Any]) -> None:
    a, b = _seed_two_workspaces(owner_conn)
    async with tenant_session(None) as s:
        assert (await s.execute(text("SELECT count(*) FROM accounts"))).scalar_one() == 0
        assert (await s.execute(text("SELECT count(*) FROM workspaces"))).scalar_one() == 0
    async with tenant_session(uuid4()) as s:
        assert (await s.execute(text("SELECT count(*) FROM accounts"))).scalar_one() == 0
    async with tenant_session(b) as s:  # type: ignore[arg-type]
        assert (await s.execute(text("SELECT count(*) FROM accounts"))).scalar_one() == 0
    async with tenant_session(a) as s:  # type: ignore[arg-type]
        assert (await s.execute(text("SELECT count(*) FROM accounts"))).scalar_one() == 1


async def test_rls_blocks_cross_tenant_writes(db: str, owner_conn: psycopg.Connection[Any]) -> None:
    a, b = _seed_two_workspaces(owner_conn)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as s:  # type: ignore[arg-type]
            await s.execute(
                text(
                    "INSERT INTO accounts (workspace_id, status, display_name, name_norm) "
                    "VALUES (:b, 'prospect', 'y', 'y')"
                ),
                {"b": b},
            )


def test_app_role_cannot_bypass_rls_or_write_shared_osm(db: str) -> None:
    with psycopg.connect(APP_URL) as conn:
        row = conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert row == (False, False)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO osm_extracts (region, source_url, extract_timestamp, status) "
                "VALUES ('x', 'y', now(), 'active')"
            )


def test_active_profile_is_immutable(owner_conn: psycopg.Connection[Any], db: str) -> None:
    ws = str(uuid4())
    owner_conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, 'A')", (ws,))
    pid = owner_conn.execute(
        "INSERT INTO discovery_profiles (workspace_id, version, status, input, compiled, spec_schema_version) "
        "VALUES (%s, 1, 'active', '{}', '{}', 1) RETURNING id",
        (ws,),
    ).fetchone()[0]  # type: ignore[index]
    with pytest.raises(psycopg.errors.RaiseException, match="create a new version"):
        owner_conn.execute("UPDATE discovery_profiles SET compiled = '{\"x\": 1}' WHERE id = %s", (pid,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        owner_conn.execute(
            "INSERT INTO discovery_profiles (workspace_id, version, status, input, compiled, spec_schema_version) "
            "VALUES (%s, 2, 'active', '{}', '{}', 1)",
            (ws,),
        )


@pytest.mark.parametrize("expires", [None, "now() + interval '60 days'"])
def test_google_places_records_must_expire(
    owner_conn: psycopg.Connection[Any], db: str, expires: str | None
) -> None:
    ws = str(uuid4())
    owner_conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, 'A')", (ws,))
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_conn.execute(
            f"INSERT INTO source_records (workspace_id, source, source_key, payload, expires_at) "
            f"VALUES (%s, 'google_places', 'p', '{{}}', {expires or 'NULL'})",
            (ws,),
        )
    owner_conn.execute(  # within 30 days is fine
        "INSERT INTO source_records (workspace_id, source, source_key, payload, expires_at) "
        "VALUES (%s, 'google_places', 'ok', '{}', now() + interval '29 days')",
        (ws,),
    )


def test_import_cannot_run_without_confirmed_mapping(owner_conn: psycopg.Connection[Any], db: str) -> None:
    ws = str(uuid4())
    owner_conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, 'A')", (ws,))
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_conn.execute(
            "INSERT INTO import_jobs (workspace_id, kind, filename, storage_uri, header_fingerprint, headers, "
            "sample_rows, status) VALUES (%s, 'accounts', 'f', 's', 'h', '{a}', '[]', 'importing')",
            (ws,),
        )


async def test_budget_exceeded_raises_before_any_spend(db: str, owner_conn: psycopg.Connection[Any]) -> None:
    ws = uuid4()
    owner_conn.execute(
        "INSERT INTO workspaces (id, name, monthly_api_budget_usd) VALUES (%s, 'A', 0.01)", (ws,)
    )
    async with tenant_session(ws) as s:
        meter = UsageMeter(s, ws)
        assert await meter.reserve("geocoder", "opencage_request", 10) == Decimal("0.0050")
        with pytest.raises(BudgetExceeded):
            await meter.reserve("geocoder", "opencage_request", 20)
        assert await meter.month_spend() == Decimal("0.0050")
    run_meter_ws = uuid4()
    owner_conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, 'B')", (run_meter_ws,))
    async with tenant_session(run_meter_ws) as s:
        with pytest.raises(BudgetExceeded, match="run budget"):
            await UsageMeter(s, run_meter_ws, run_budget_usd=Decimal("0.001")).reserve(
                "geocoder", "google_geocode", 1
            )


def test_migrations_downgrade_and_upgrade_cleanly(database: str) -> None:
    url = recreate_database("cyclone_test_migrations")
    migrate(url)
    migrate(url, "base", down=True)
    migrate(url)
    with psycopg.connect(url) as conn:
        tables = conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
        assert tables is not None and tables[0] >= 22
