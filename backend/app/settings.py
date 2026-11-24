"""Runtime configuration. All values come from environment variables (see ../.env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # Postgres. Plain libpq URLs (postgresql://...). The app connects as `app_backend`
    # (RLS enforced); migrations connect as the schema owner.
    database_url: str = "postgresql://app_backend:app_backend@localhost:5432/cyclone"
    migrations_database_url: str = "postgresql://postgres:postgres@localhost:5432/cyclone"
    # Supabase's transaction pooler (port 6543) cannot use prepared statements.
    db_disable_prepared_statements: bool = False

    # Auth (Supabase). Either JWKS (asymmetric signing keys) or the legacy HS256 secret.
    supabase_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"
    # Local-only convenience: accept `Authorization: Dev <uuid>`. Refused outside development.
    auth_dev_bypass: bool = False

    # Uploads
    storage_backend: Literal["local", "supabase"] = "local"
    storage_local_root: str = ".storage"
    supabase_service_role_key: SecretStr | None = None  # used ONLY for Storage, never for DB access
    storage_bucket: str = "imports"
    max_upload_mb: int = 50

    # LLM
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-flash-latest"
    llm_send_sample_values: bool = True  # False → the column mapper sends headers only

    # Geocoding
    opencage_api_key: SecretStr | None = None
    google_maps_server_key: SecretStr | None = None
    geocode_country_codes: str = "ae"

    # Workers
    run_tasks_inline: bool = False  # tests / single-process dev: run jobs in the API process

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @model_validator(mode="after")
    def _guard_dev_bypass(self) -> Settings:
        if self.auth_dev_bypass and self.environment == "production":
            raise ValueError("AUTH_DEV_BYPASS must never be enabled in production")
        return self

    @staticmethod
    def _driver_url(url: str, driver: str) -> str:
        scheme, rest = url.split("://", 1)
        return f"postgresql+{driver}://{rest}" if scheme in {"postgres", "postgresql"} else url

    @property
    def database_url_async(self) -> str:
        return self._driver_url(self.database_url, "asyncpg")

    @property
    def migrations_url_sync(self) -> str:
        return self._driver_url(self.migrations_database_url, "psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
