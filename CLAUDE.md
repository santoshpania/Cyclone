# CLAUDE.md — Cyclone

**Cyclone** is the codename for this product. Use it for package names (`cyclone-web`, `cyclone-backend`), the DB name (`cyclone`) and service names.

Industry-agnostic territory coverage, virgin-market discovery and sales copilot. A workspace describes its ICP in plain language. Gemini compiles that into a validated `DiscoveryProfileSpec`. Workers discover businesses (OSM extracts, Google Places, registry CSVs), enrich and score them, compare them with the customer base on a coverage map, and generate multi-day rep routes.

Read first: `PLAN.md` (roadmap), `docs/schema.sql` + `docs/schema.md` (data model and JSONB contracts), `docs/adr/` (decisions).

## Repo layout
```
web/                       Next.js 16 App Router, TS strict, Tailwind v4, hand-written shadcn-style UI
  AGENTS.md                Next.js 16 differs from older versions: read node_modules/next/dist/docs/ first
  openapi.json             exported backend contract (generated; CI fails on drift)
  src/lib/api/schema.d.ts  generated types (do not edit; `make gen-api`)
  src/lib/auth.tsx         single module-level auth store (Supabase, or dev mode)
backend/
  app/api/                 FastAPI routers (thin: auth, validation, enqueue)
  app/domain/              pure logic: normalisers, entity resolution (later: scoring, coverage, balancing)
  app/imports/             import pipeline pieces: reader, targets/transforms, heuristics, LLM mapper
  app/services/            DB orchestration: import runner, resolution writes, rollups, reviews, UsageMeter
  app/catalogs/            bundled reference data (header synonyms, legal forms, MX providers, tech
                           fingerprints; Phase 2 adds Places types + OSM taginfo via scripts/catalogs/)
  app/config/pricing.yaml  per-SKU cost estimates used by UsageMeter (verify before production)
  app/adapters/            the ONLY modules that do network I/O: llm, geocoding, storage (later: osm,
                           google_places, google_routes, dns, web)
  app/workers/             procrastinate tasks (Postgres-backed queue) + dispatch
  app/db/                  session (sets app.workspace_id / app.user_id), Alembic migrations;
                           migrations/sql/0001_init.sql is the schema (docs/schema.sql symlinks to it)
  scripts/                 dev_db.py, export_openapi.py, catalogs/refresh_*.py
  tests/                   unit/, integration/ (real PostGIS), fixtures/imports/
docs/                      schema.sql (symlink), schema.md, adr/
docker-compose.yml         local PostGIS (Supabase in production)
```

## Commands
```bash
make db-up && make db-migrate               # local PostGIS, migrations, enable app_backend login
make api / make worker / make web           # API on :8000, queue worker, web on :3000
make test                                   # backend (not live) + web unit tests
make lint                                   # ruff, ruff format, mypy strict, eslint, tsc, industry-terms check
make gen-api                                # regenerate web/openapi.json + typed client after API changes
cd backend && uv run pytest -m live         # opt-in: real Gemini/Places, needs keys, costs money
```
Local sign-in without Supabase: `AUTH_DEV_BYPASS=true` (backend, development only) + `NEXT_PUBLIC_AUTH_MODE=dev` (web).

## Non-negotiable architecture rules
1. **Zero industry hardcoding.** No industry names, OSM tag values, Places types, keywords or pitch wording in `backend/app/` or `web/src/` outside `backend/app/catalogs/`. Industry examples belong only in `tests/fixtures/` and docs. CI runs `scripts/check_no_industry_terms.sh`.
2. **The LLM composes, code executes.** Every Gemini output is parsed into a Pydantic model (structured output with a response schema), then validated against the catalogs. Never execute LLM-generated SQL, Overpass QL, regex or code. LLM confidence is capped below heuristic certainty and every AI mapping needs user confirmation. Queries are built only by code (Phase 2: `app/profile/compilers/`), with parameter binding.
3. **Profiles are immutable once active.** Changes create a new version. Anything derived (scores, pitches, coverage, plans) stores the `profile_id` it was computed with.
4. **Tenancy through RLS.** Every tenant table has `workspace_id`, and RLS is enabled and forced. The API connects as the `app_backend` role (never `service_role`) and sets `app.workspace_id` / `app.user_id` in every transaction via `app/db/session.py` (`tenant_session`). Shared tables (`osm_*`, `provider_query_cache`) hold no tenant data and `app_backend` cannot write the `osm_*` ones. Use SQLAlchemy Core with explicit SQL (`text()`); there are no ORM models.
5. **Spatial conventions.** Store SRID 4326. Compute distances in metres with `::geography`. H3 is computed in Python (`h3`) and stored as `bigint`. Use `ST_DWithin` and never `ST_Distance < x` in WHERE clauses.
6. **Provenance.** Raw source payloads go only to `source_records`. Any field written to `accounts` records its source (and expiry, if any) in `field_provenance`.
7. **Layering.** `domain/` is pure and synchronous-testable. Adapters return typed DTOs. Routers never call adapters directly; long work is enqueued.
8. **Determinism.** Scoring, coverage classification, territory balancing and route solving are deterministic given their inputs (seeded solvers). The LLM only produces specs, mappings, qualification answers and pitch text.
9. **Locale.** UAE/GCC first: default languages `en` and `ar` (RTL support in the UI), phone region `AE`, currency `AED`. Every user-facing generated string is stored per language.

## API cost guardrails
- **Field masks.** Defined only in `adapters/google_places/field_masks.py` as named tiers: `DISCOVERY_IDS` (`places.id,nextPageToken`), `DETAILS_BASIC`, `DETAILS_CONTACT`. Never use `*`. The client raises if a request has no `X-Goog-FieldMask`, or a mask outside the tier list.
- **Two-step Places discovery.** IDs-only Text Search per H3 cell → dedup against `accounts` and `source_records` → Place Details only for new IDs that pass pre-filters. The contact tier is used only when `enrichment_plan.places_contact_fields` is true.
- **Spatial query cache.** Look up `provider_query_cache(provider, query_fingerprint, h3_index)` before every Text Search call; a fresh hit means no API call. Text Search caps at 60 results, so a saturated cell is split into its H3 children, down to `MAX_H3_RES`. Default cache TTL is 30 days.
- **Budgets.** Every paid call (Places, Routes, Gemini, geocoder) goes through `UsageMeter.reserve(workspace, sku, units)`. It checks `api_usage_ledger` against the workspace's monthly budget and the run budget, and raises `BudgetExceeded`. Each discovery run needs an estimate plus explicit user confirmation. SKU prices live in `app/config/pricing.yaml`; re-verify them against Google's current price list whenever they're edited.
- **OSM.** Run discovery against local `osm_features` ($0). The Overpass fallback allows one concurrent request, sets `[timeout:]` and `[maxsize:]`, backs off on 429/504, and sends a generic User-Agent.
- **Gemini.** Cache results by `input_hash`. Make one qualification call per account that batches all of the profile's `llm_*` signals. Cap web text at ~8k characters per page and 3 pages. Generate pitches lazily (on view, export or plan). The model comes from the `GEMINI_MODEL` env var.
- **Routes.** OR-Tools handles optimisation over a haversine × circuity matrix. Google Routes `computeRoutes` sits behind `use_google_routes`, is used only for final per-day polylines, and takes ≤25 intermediate waypoints.
- **Web crawling.** Respect robots.txt, make one request at a time per domain, cap responses at 2 MB, use a 10 s timeout, and follow at most 5 redirects.

## Data terms
- **Google Maps Platform.** Store `place_id` indefinitely. Every other Places field is kept only in `source_records`, with `expires_at ≤ 30 days` (DB CHECK). The nightly `purge_expired_google_fields` task clears copies on `accounts`. Exports re-hydrate expired fields or mark them "refresh required". Never put Places content on a non-Google map.
- **OSM (ODbL).** Show "© OpenStreetMap contributors" on the map and in every CSV/XLSX export.
- **Personal data (UAE PDPL / GDPR).** Sole-trader phones and emails count as personal data. `DELETE /accounts/{id}` must cascade through `source_records`, `enrichments` and `account_pitches`.

## Testing conventions
- **Backend.** pytest + pytest-asyncio. DB tests run against real PostGIS (`CYCLONE_TEST_DATABASE_URL`, default `postgresql://postgres:postgres@127.0.0.1:5432/cyclone_test`; CI uses the `postgis/postgis:16-3.4` service); never SQLite. The suite recreates and migrates the test database once, connects the app as `app_backend` so RLS is live, and truncates tenant data after each test (imports span several transactions, so rollback-per-test can't isolate them). Jobs run inline (`RUN_TASKS_INLINE=true`).
- **No network in tests.** `pytest-socket` blocks sockets by default. HTTP is mocked with `respx`, using recorded fixtures in `tests/fixtures/<provider>/`. Gemini goes through `FakeLLM`, which returns fixture JSON keyed by prompt name.
- **Mandatory guard tests.** These must not be deleted:
  - A Places request without a field mask raises.
  - A fresh cache hit makes zero HTTP calls.
  - A saturated cell subdivides.
  - Going over budget raises `BudgetExceeded` before any HTTP call.
  - A cross-workspace read returns 0 rows under RLS, including when `app.workspace_id` is unset.
  - A google_places `source_record` without `expires_at` is rejected.
  - Updating an active profile fails.
  - `app_backend` is not superuser, cannot bypass RLS, and cannot write shared OSM tables.
  - An import cannot run without a confirmed column mapping.
- **Golden ICP evals** (`-m live`, run before merging prompt changes). At least 5 unrelated ICPs (e.g. dental clinics, boutique hotels, warehouses, mid-market cybersecurity buyers, car workshops) must compile to valid specs with no validator errors. Snapshot diffs are reviewed by hand.
- **Domain logic.** Table-driven unit tests for scoring (unknown vs false), entity resolution (near-duplicate fixtures in English and Arabic transliteration), coverage classification and territory balance.
- **Migrations.** Each one has an upgrade/downgrade test against an empty DB.
- **Web.** Vitest + React Testing Library for components and pure helpers (e.g. `src/lib/mapping.ts`); Playwright for import, configurator and map flows, with Google Maps mocked and `--trace off` by default. Typecheck (`next typegen && tsc`), lint (React Compiler rules on) and `next build` must be clean.
- **Coverage.** New code in `domain/` and `profile/` needs tests in the same PR.

## Conventions
- Python 3.12+, `uv`, ruff (format + lint) and mypy in strict mode for `app/`. The backend is an installable package (hatchling) so CLI entry points like the procrastinate worker can import `app`. TypeScript strict, no `any` in `src/lib`.
- Commits: conventional commits (`feat:`, `fix:`, `chore:`…). One concern per PR.
- Secrets only through env vars (`.env.example` lists names, never values). Never log API keys, phone numbers or emails at INFO.
- Tick off `PLAN.md` checkboxes in the same PR that completes the item.
