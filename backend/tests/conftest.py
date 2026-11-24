"""Test setup. DB tests run against a real PostGIS database (never SQLite):
CYCLONE_TEST_DATABASE_URL must point at a server where the given user can create databases.
The suite creates `<db>`, migrates it, and connects the app as `app_backend` so RLS is live."""

from __future__ import annotations

import csv
import io
import os
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest

OWNER_URL = os.environ.get(
    "CYCLONE_TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/cyclone_test"
)
APP_PASSWORD = "app_backend_test"
JWT_SECRET = "test-jwt-secret-at-least-32-characters-long"
FIXTURES = Path(__file__).parent / "fixtures" / "imports"

_scheme, _rest = OWNER_URL.split("://", 1)
_creds, _hostdb = _rest.split("@", 1)
_host, _dbname = _hostdb.rsplit("/", 1)
APP_URL = f"postgresql://app_backend:{APP_PASSWORD}@{_host}/{_dbname}"
ADMIN_URL = f"{_scheme}://{_creds}@{_host}/postgres"

_storage = tempfile.mkdtemp(prefix="cyclone-test-storage-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": APP_URL,
        "MIGRATIONS_DATABASE_URL": OWNER_URL,
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "RUN_TASKS_INLINE": "true",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_ROOT": _storage,
        "AUTH_DEV_BYPASS": "false",
    }
)
for key in ("GEMINI_API_KEY", "OPENCAGE_API_KEY", "GOOGLE_MAPS_SERVER_KEY"):
    os.environ.pop(key, None)

from app.settings import get_settings  # noqa: E402

get_settings.cache_clear()


def migrate(owner_url: str, revision: str = "head", *, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", owner_url.replace("postgresql://", "postgresql+psycopg://", 1))
    (command.downgrade if down else command.upgrade)(cfg, revision)


def recreate_database(name: str) -> str:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    return f"{_scheme}://{_creds}@{_host}/{name}"


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    url = recreate_database(_dbname)
    migrate(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"ALTER ROLE app_backend LOGIN PASSWORD '{APP_PASSWORD}'")
    yield url


@pytest.fixture
def owner_conn(database: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database, autocommit=True) as conn:
        yield conn


@pytest.fixture
async def db(database: str) -> AsyncIterator[str]:
    """Clean slate per test (TRUNCATE cascades from workspaces to every tenant table)."""
    from app.adapters.geocoding import set_geocoders
    from app.adapters.llm import set_llm_client
    from app.db.session import dispose_engine

    yield database
    set_llm_client(None)
    set_geocoders(None)
    await dispose_engine()
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("TRUNCATE workspaces, api_usage_ledger, provider_query_cache CASCADE")


def token_for(
    user_id: UUID, *, email: str = "user@example.test", secret: str = JWT_SECRET, exp_in: int = 3600
) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "aud": "authenticated",
            "exp": int(time.time()) + exp_in,
            "role": "authenticated",
        },
        secret,
        algorithm="HS256",
    )


class ApiUser:
    def __init__(self, client: Any, user_id: UUID):
        self.client, self.id = client, user_id
        self.headers = {"Authorization": f"Bearer {token_for(user_id)}"}

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.client.get(url, headers=self.headers, **kw)

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.client.post(url, headers=self.headers, **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.client.put(url, headers=self.headers, **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.client.patch(url, headers=self.headers, **kw)

    async def create_workspace(self, name: str = "Test Co", budget: float | None = None) -> str:
        r = await self.post("/workspaces", json={"name": name, "company_profile": {"company_name": name}})
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    async def upload(self, ws: str, filename: str, data: bytes, kind: str) -> dict[str, Any]:
        r = await self.post(
            f"/workspaces/{ws}/imports", files={"file": (filename, data)}, data={"kind": kind}
        )
        assert r.status_code == 201, r.text
        return dict(r.json())

    async def confirm_and_run(
        self, ws: str, job: dict[str, Any], mapping: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        m = mapping or job["proposed_mapping"]
        r = await self.put(f"/workspaces/{ws}/imports/{job['id']}/mapping", json=m)
        assert r.status_code == 200, r.text
        r = await self.post(f"/workspaces/{ws}/imports/{job['id']}/run")
        assert r.status_code == 202, r.text
        r = await self.get(f"/workspaces/{ws}/imports/{job['id']}")
        return dict(r.json())


@pytest.fixture
async def client(db: str) -> AsyncIterator[Any]:
    import httpx

    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def alice(client: Any) -> ApiUser:
    return ApiUser(client, uuid4())


@pytest.fixture
def bob(client: Any) -> ApiUser:
    return ApiUser(client, uuid4())


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def odoo_xlsx() -> bytes:
    """The Odoo-style export as a real .xlsx (built at test time; no binary fixtures in git)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    with open(FIXTURES / "odoo_contacts_rows.csv", encoding="utf-8") as f:
        for row in csv.reader(f):
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
