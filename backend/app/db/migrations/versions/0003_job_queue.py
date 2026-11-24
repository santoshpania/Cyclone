"""procrastinate job-queue schema (Postgres-backed queue, no Redis).

Revision ID: 0003
"""

from alembic import op  # noqa: F401
from procrastinate.schema import SchemaManager

from app.db.migrations.sqlrun import fetch_all, run_sql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(SchemaManager.get_schema())
    # Grant only on the queue's own objects; a blanket GRANT ON ALL TABLES would undo 0002's
    # read-only rule for the shared OSM tables (caught by test_guards).
    run_sql("""
        DO $$ DECLARE r record; BEGIN
          FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'procrastinate%' LOOP
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_backend', r.tablename);
          END LOOP;
          FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' AND sequencename LIKE 'procrastinate%' LOOP
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO app_backend', r.sequencename);
          END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # Drop everything procrastinate created in public: functions, tables, then enum/composite types.
    for (stmt,) in fetch_all(
        "SELECT 'DROP FUNCTION IF EXISTS ' || p.oid::regprocedure || ' CASCADE' FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate%'"
    ):
        run_sql(stmt)
    for (stmt,) in fetch_all(
        "SELECT 'DROP TABLE IF EXISTS ' || quote_ident(tablename) || ' CASCADE' FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename LIKE 'procrastinate%'"
    ):
        run_sql(stmt)
    for (stmt,) in fetch_all(
        "SELECT 'DROP TYPE IF EXISTS ' || quote_ident(t.typname) || ' CASCADE' FROM pg_type t "
        "JOIN pg_namespace n ON n.oid = t.typnamespace LEFT JOIN pg_class c ON c.oid = t.typrelid "
        "WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate%' "
        "AND (t.typtype = 'e' OR (t.typtype = 'c' AND c.relkind = 'c'))"
    ):
        run_sql(stmt)
