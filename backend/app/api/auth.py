"""Supabase JWT verification → the caller's user id. The JWT is verified here; the database
then enforces tenancy through RLS using that id."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.settings import Settings, get_settings


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _decode(token: str, s: Settings) -> dict[str, object]:
    options: Any = {"require": ["exp", "sub"]}
    if s.supabase_jwt_secret is not None:
        return jwt.decode(
            token,
            s.supabase_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=s.supabase_jwt_audience,
            options=options,
        )
    if not s.supabase_url:
        raise RuntimeError("Set SUPABASE_URL (JWKS) or SUPABASE_JWT_SECRET to verify tokens")
    key = _jwks_client(
        s.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    ).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        key.key,
        algorithms=["RS256", "ES256", "EdDSA"],
        audience=s.supabase_jwt_audience,
        options=options,
    )


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"}
    )
    if not authorization:
        raise unauthorized
    scheme, _, token = authorization.partition(" ")
    if scheme == "Dev" and settings.auth_dev_bypass and settings.environment == "development":
        try:
            return AuthUser(id=UUID(token.strip()), email="dev@localhost")
        except ValueError:
            raise unauthorized from None
    if scheme.lower() != "bearer" or not token:
        raise unauthorized
    try:
        claims = await asyncio.to_thread(_decode, token, settings)
        return AuthUser(
            id=UUID(str(claims["sub"])), email=str(claims["email"]) if claims.get("email") else None
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        raise unauthorized from None
