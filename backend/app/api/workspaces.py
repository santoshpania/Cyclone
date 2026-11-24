from __future__ import annotations

import json
import re
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import AuthUser, current_user
from app.api.deps import Ws
from app.db.session import tenant_session

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CompanyProfile(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    offerings: list[str] = Field(default_factory=list, max_length=50)
    value_proposition: str = Field(default="", max_length=2000)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company_profile: CompanyProfile
    languages: list[str] = Field(default_factory=lambda: ["en", "ar"], min_length=1, max_length=10)
    home_currency: str = Field(default="AED", pattern=r"^[A-Z]{3}$")
    default_phone_region: str = Field(default="AE", pattern=r"^[A-Z]{2}$")

    @field_validator("languages")
    @classmethod
    def _bcp47(cls, v: list[str]) -> list[str]:
        for lang in v:
            if not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*", lang):
                raise ValueError(f"not a BCP-47 language tag: {lang!r}")
        return list(dict.fromkeys(v))


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    company_profile: CompanyProfile | None = None
    languages: list[str] | None = None
    home_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    default_phone_region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    settings: dict[str, Any] | None = None


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    company_profile: dict[str, Any]
    languages: list[str]
    home_currency: str
    default_phone_region: str
    settings: dict[str, Any]
    monthly_api_budget_usd: float
    role: str


_SELECT = """
SELECT w.id, w.name, w.company_profile, w.languages, w.home_currency, w.default_phone_region, w.settings,
       w.monthly_api_budget_usd, m.role
FROM workspaces w JOIN workspace_members m ON m.workspace_id = w.id AND m.user_id = :u
"""


def _out(r: Any) -> WorkspaceOut:
    return WorkspaceOut(
        id=r.id,
        name=r.name,
        company_profile=r.company_profile,
        languages=list(r.languages),
        home_currency=r.home_currency.strip(),
        default_phone_region=r.default_phone_region.strip(),
        settings=r.settings,
        monthly_api_budget_usd=float(r.monthly_api_budget_usd),
        role=r.role,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate, user: Annotated[AuthUser, Depends(current_user)]
) -> WorkspaceOut:
    ws_id = uuid4()
    async with tenant_session(ws_id, user.id) as s:  # RLS WITH CHECK needs app.workspace_id = new id
        await s.execute(
            text("""
            INSERT INTO workspaces (id, name, company_profile, languages, home_currency, default_phone_region)
            VALUES (:id, :name, CAST(:cp AS jsonb), :langs, :cur, :region)
        """),
            {
                "id": ws_id,
                "name": body.name,
                "cp": body.company_profile.model_dump_json(),
                "langs": body.languages,
                "cur": body.home_currency,
                "region": body.default_phone_region,
            },
        )
        await s.execute(
            text("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (:w, :u, 'owner')"),
            {"w": ws_id, "u": user.id},
        )
        row = (await s.execute(text(_SELECT + " WHERE w.id = :id"), {"u": user.id, "id": ws_id})).one()
    return _out(row)


async def _user_scoped(user: Annotated[AuthUser, Depends(current_user)]) -> Any:
    async with tenant_session(None, user.id) as s:
        yield user, s


@router.get("")
async def list_workspaces(
    ctx: Annotated[tuple[AuthUser, AsyncSession], Depends(_user_scoped)],
) -> list[WorkspaceOut]:
    user, s = ctx
    rows = await s.execute(text(_SELECT + " ORDER BY w.created_at"), {"u": user.id})
    return [_out(r) for r in rows]


@router.get("/{workspace_id}")
async def get_workspace(ws: Ws) -> WorkspaceOut:
    row = (
        await ws.session.execute(
            text(_SELECT + " WHERE w.id = :id"), {"u": ws.user.id, "id": ws.workspace_id}
        )
    ).one()
    return _out(row)


@router.patch("/{workspace_id}")
async def update_workspace(body: WorkspaceUpdate, ws: Ws) -> WorkspaceOut:
    ws.require("admin")
    data = body.model_dump(exclude_unset=True)
    sets: list[str] = []
    params: dict[str, Any] = {"id": ws.workspace_id}
    for k, v in data.items():
        if k in {"company_profile", "settings"}:
            sets.append(
                f"{k} = CAST(:{k} AS jsonb)"
                if k == "company_profile"
                else "settings = settings || CAST(:settings AS jsonb)"
            )
            params[k] = json.dumps(v)
        else:
            sets.append(f"{k} = :{k}")
            params[k] = v
    if sets:
        await ws.session.execute(text(f"UPDATE workspaces SET {', '.join(sets)} WHERE id = :id"), params)
    return await get_workspace(ws)
