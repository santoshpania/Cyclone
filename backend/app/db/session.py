"""Database access. Every transaction runs with `app.workspace_id` / `app.user_id` set, so
Postgres row-level security does the tenant isolation (CLAUDE.md rule 4)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _factory
    if _engine is None:
        s = get_settings()
        connect_args: dict[str, Any] = {}
        if s.db_disable_prepared_statements:
            connect_args["statement_cache_size"] = 0
        _engine = create_async_engine(s.database_url_async, pool_pre_ping=True, connect_args=connect_args)
        _factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _factory = None, None


async def set_tenant(session: AsyncSession, workspace_id: UUID | None, user_id: UUID | None) -> None:
    """Scope the current transaction. Empty string = unset (policies then match nothing)."""
    await session.execute(
        text("SELECT set_config('app.workspace_id', :w, true), set_config('app.user_id', :u, true)"),
        {"w": str(workspace_id) if workspace_id else "", "u": str(user_id) if user_id else ""},
    )


@asynccontextmanager
async def tenant_session(
    workspace_id: UUID | None, user_id: UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """One transaction, committed on success, rolled back on error."""
    get_engine()
    assert _factory is not None
    async with _factory() as session, session.begin():
        await set_tenant(session, workspace_id, user_id)
        yield session
