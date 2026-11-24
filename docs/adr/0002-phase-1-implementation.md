# ADR 0002 — Decisions made while building Phase 1

Status: accepted · Date: 2026-11-24

These came up during implementation and change or refine ADR 0001.

## 1. SQLAlchemy Core with explicit SQL, no ORM models
PostGIS functions, RLS-aware writes and `ON CONFLICT` upserts read more clearly as SQL than as GeoAlchemy2 ORM expressions. Queries use `text()` with bound parameters. Nullable parameters are always `CAST(:x AS type)`, because asyncpg can't infer types for `:x IS NULL`.

## 2. Membership via RLS policies, not SECURITY DEFINER functions
`workspaces` and `workspace_members` also admit rows where `user_id = app.user_id`. Creating a workspace sets `app.workspace_id` to the new id inside the same transaction. This avoids definer functions, which run as the owner and are easy to get wrong on Supabase.

## 3. Migration 0001 executes the schema file
`backend/app/db/migrations/sql/0001_init.sql` is the source of truth, and `docs/schema.sql` is a symlink to it. The file is run through the raw driver connection, because psycopg would otherwise read the `%` in PL/pgSQL `RAISE` and the pg_trgm operator as placeholders. Grants are scoped per object: a blanket `GRANT … ON ALL TABLES` in migration 0003 silently re-granted writes on the shared OSM tables, and the guard test caught it.

## 4. Local DB is plain PostGIS (docker compose), not `supabase start`
Production remains Supabase (Postgres, Auth, Storage). Locally, auth can run in a dev-bypass mode (`Authorization: Dev <uuid>`) that the API refuses outside `ENVIRONMENT=development`. Supabase Auth and Storage still need a first live check.

## 5. Tests use a real PostGIS server via env var, not Testcontainers
The suite recreates and migrates `cyclone_test`, then connects as `app_backend` so RLS is exercised in every DB test. Imports span several transactions, so isolation is by `TRUNCATE … CASCADE` after each test rather than by rollback.

## 6. Name-only matching for records without coordinates
Invoice exports usually carry only a customer name. Scoring "exact name, no coordinates" as review-level meant every order created a duplicate account. Now an exact normalised name with no conflicting identifier links; a conflicting phone, domain or ID, or two equally good candidates, goes to review.

## 7. Web: client-rendered app area, one auth store
Next.js 16 keeps previously visited routes mounted (hidden). Per-route auth providers therefore disagreed about who was signed in, so sign-in appeared to do nothing. Auth is a single module-level store read through `useSyncExternalStore`. Browser-only subtrees sit behind `use(browser())` inside `<Suspense>`, per the Next 16 docs. The API verifies every JWT, so the web app does no server-side session handling and has no `proxy.ts`.

## 8. The backend is an installable package
Hatchling build with an editable install, so CLI entry points (the procrastinate worker) can import `app` without `PYTHONPATH` tricks.
