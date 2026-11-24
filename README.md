# Cyclone

Industry-agnostic AI platform for territory coverage, virgin-market discovery and sales copilot work.

You describe your products and ideal customer in plain language. Cyclone turns that into discovery rules for OpenStreetMap, Google Places and public registries. It enriches and scores the businesses it finds, maps them against your existing customers to show covered, under-covered and virgin territory, and builds balanced multi-day rep routes with exportable contact lists and AI-written pitches.

**Status:** Phase 1 (foundation + AI-assisted import of customer lists and order history) is built. See [`PLAN.md`](PLAN.md).

| Doc | What's in it |
|---|---|
| [`PLAN.md`](PLAN.md) | Phased roadmap with checkboxes, exit criteria and carried-over items |
| [`CLAUDE.md`](CLAUDE.md) | Architecture rules, API cost guardrails, data terms, testing conventions |
| [`docs/schema.sql`](docs/schema.sql) | PostgreSQL + PostGIS schema (symlink to migration 0001) |
| [`docs/schema.md`](docs/schema.md) | Schema rationale and JSONB contracts (`DiscoveryProfileSpec`, column mappings, matching rules) |
| [`docs/adr/`](docs/adr/) | Architecture decision records |

**Stack:** Next.js 16 · TypeScript · Tailwind v4 · FastAPI · PostgreSQL/PostGIS (Supabase in production) · procrastinate (Postgres job queue) · Gemini Flash · OR-Tools (Phase 4)

**Launch market:** UAE / GCC (English + Arabic).

## Run it locally

Requirements: Docker, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
cp .env.example backend/.env        # then edit; keep the DATABASE_URL password = APP_DB_PASSWORD
```

```bash
make db-up && make db-migrate
```

Run each of these in its own terminal:

```bash
make api
```

```bash
make worker
```

```bash
cd web && cp ../.env.example .env.local && pnpm install && pnpm dev
```

Without a Supabase project, use local dev sign-in: set `AUTH_DEV_BYPASS=true` in `backend/.env` and `NEXT_PUBLIC_AUTH_MODE=dev` in `web/.env.local`. The API refuses the bypass outside `ENVIRONMENT=development`.

Optional keys: `GEMINI_API_KEY` (AI column mapping for headers the heuristics can't place), `OPENCAGE_API_KEY` (geocoding addresses that have no coordinates).

## Tests

```bash
make test
```

```bash
make lint
```

Backend tests need a PostGIS server; set `CYCLONE_TEST_DATABASE_URL` (default `postgresql://postgres:postgres@127.0.0.1:5432/cyclone_test`). The suite creates and migrates that database itself.
