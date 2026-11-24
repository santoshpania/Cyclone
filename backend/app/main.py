"""FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts, imports, workspaces
from app.db.session import dispose_engine
from app.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.run_tasks_inline:
        yield
    else:
        from app.workers.app import app as queue

        async with queue.open_async():
            yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    api = FastAPI(title="Cyclone API", version="0.1.0", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api.include_router(workspaces.router)
    api.include_router(imports.router)
    api.include_router(imports.meta_router)
    api.include_router(accounts.router)

    @api.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return api


app = create_app()
