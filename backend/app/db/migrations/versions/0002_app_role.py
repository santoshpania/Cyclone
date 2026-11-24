"""app_backend role (RLS enforced) + grants; Supabase auth.users FK when present.

The role is created NOLOGIN. Deployment enables login with a secret password:
    ALTER ROLE app_backend LOGIN PASSWORD '<from secret manager>';

Revision ID: 0002
"""

from alembic import op  # noqa: F401

from app.db.migrations.sqlrun import fetch_all, run_sql  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
    CREATE ROLE app_backend NOLOGIN NOBYPASSRLS;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_backend;
-- Shared OSM reference data is written only by the import job (schema owner).
REVOKE INSERT, UPDATE, DELETE ON osm_extracts, osm_features, osm_admin_boundaries FROM app_backend;

DO $$ BEGIN
  IF to_regclass('auth.users') IS NOT NULL THEN
    ALTER TABLE workspace_members
      ADD CONSTRAINT workspace_members_user_fk FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
  END IF;
END $$;
"""

DOWNGRADE = """
ALTER TABLE workspace_members DROP CONSTRAINT IF EXISTS workspace_members_user_fk;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM app_backend;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_backend;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_backend;
REVOKE USAGE ON SCHEMA public FROM app_backend;
"""


def upgrade() -> None:
    run_sql(UPGRADE)


def downgrade() -> None:
    run_sql(DOWNGRADE)
