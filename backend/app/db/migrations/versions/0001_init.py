"""Initial schema (sql/0001_init.sql, symlinked as docs/schema.sql).

Revision ID: 0001
"""

from pathlib import Path

from alembic import op  # noqa: F401

from app.db.migrations.sqlrun import fetch_all, run_sql  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parent.parent / "sql" / "0001_init.sql"

TABLES = [
    "route_stops",
    "route_days",
    "plan_territories",
    "coverage_plans",
    "zone_coverage",
    "account_pitches",
    "enrichments",
    "api_usage_ledger",
    "provider_query_cache",
    "match_reviews",
    "source_records",
    "discovery_runs",
    "historical_orders",
    "import_jobs",
    "accounts",
    "spatial_zones",
    "osm_admin_boundaries",
    "osm_features",
    "osm_extracts",
    "discovery_profiles",
    "workspace_members",
    "workspaces",
]


def upgrade() -> None:
    run_sql(SQL.read_text())


def downgrade() -> None:
    for t in TABLES:
        run_sql(f"DROP TABLE IF EXISTS {t} CASCADE")
    run_sql("DROP FUNCTION IF EXISTS discovery_profiles_immutable()")
