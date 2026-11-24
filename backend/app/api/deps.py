"""Request-scoped DB session with tenant context, and workspace membership checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import AuthUser, current_user
from app.db.session import tenant_session

ROLE_RANK = {"viewer": 0, "rep": 1, "manager": 2, "admin": 3, "owner": 4}


@dataclass
class WorkspaceContext:
    workspace_id: UUID
    user: AuthUser
    role: str
    session: AsyncSession

    def require(self, min_role: str) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires {min_role} role")


async def user_session(
    user: Annotated[AuthUser, Depends(current_user)],
) -> AsyncIterator[tuple[AuthUser, AsyncSession]]:
    """Session scoped to the user only (no workspace selected): sees their memberships."""
    async with tenant_session(None, user.id) as s:
        yield user, s


async def workspace_ctx(
    workspace_id: Annotated[UUID, Path()],
    user: Annotated[AuthUser, Depends(current_user)],
) -> AsyncIterator[WorkspaceContext]:
    async with tenant_session(workspace_id, user.id) as s:
        role = (
            await s.execute(
                text("SELECT role FROM workspace_members WHERE workspace_id = :w AND user_id = :u"),
                {"w": workspace_id, "u": user.id},
            )
        ).scalar_one_or_none()
        if role is None:
            # Same response whether the workspace exists or not.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        yield WorkspaceContext(workspace_id, user, role, s)


Ws = Annotated[WorkspaceContext, Depends(workspace_ctx)]
