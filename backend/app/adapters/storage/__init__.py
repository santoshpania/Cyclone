"""Upload storage: local directory (dev/tests) or Supabase Storage (private bucket)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx

from app.settings import get_settings


class Storage(Protocol):
    async def put(self, path: str, data: bytes, content_type: str) -> str: ...
    async def get(self, path: str) -> bytes: ...


def _safe(path: str) -> str:
    parts = [p for p in path.split("/") if p not in {"", ".", ".."}]
    if not parts:
        raise ValueError("empty storage path")
    return "/".join(parts)


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    async def put(self, path: str, data: bytes, content_type: str) -> str:
        target = self.root / _safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return _safe(path)

    async def get(self, path: str) -> bytes:
        return (self.root / _safe(path)).read_bytes()


class SupabaseStorage:
    """The service-role key is used for Storage only — DB access always goes through app_backend."""

    def __init__(self, base_url: str, service_key: str, bucket: str):
        self._base = base_url.rstrip("/") + "/storage/v1/object"
        self._bucket = bucket
        self._headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    async def put(self, path: str, data: bytes, content_type: str) -> str:
        p = _safe(path)
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self._base}/{self._bucket}/{p}",
                content=data,
                headers={**self._headers, "Content-Type": content_type, "x-upsert": "true"},
            )
            r.raise_for_status()
        return p

    async def get(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{self._base}/authenticated/{self._bucket}/{_safe(path)}", headers=self._headers)
            r.raise_for_status()
            return r.content


def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "supabase":
        if not (s.supabase_url and s.supabase_service_role_key):
            raise RuntimeError("STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseStorage(
            s.supabase_url, s.supabase_service_role_key.get_secret_value(), s.storage_bucket
        )
    return LocalStorage(s.storage_local_root)
