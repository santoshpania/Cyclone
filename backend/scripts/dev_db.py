"""Migrate the database and enable login for the app role (local dev / CI).

Production: run `alembic upgrade head` against Supabase as the owner, then set the
app_backend password from your secret manager:  ALTER ROLE app_backend LOGIN PASSWORD '...';
"""

import os
import subprocess
import sys

import psycopg
from psycopg import sql

from app.settings import get_settings

password = os.environ.get("APP_DB_PASSWORD")
if not password:
    sys.exit("Set APP_DB_PASSWORD (must match the password in DATABASE_URL)")
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
with psycopg.connect(get_settings().migrations_database_url, autocommit=True) as conn:
    conn.execute(sql.SQL("ALTER ROLE app_backend LOGIN PASSWORD {}").format(sql.Literal(password)))
print("database migrated; app_backend can log in")
