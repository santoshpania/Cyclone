# PLAN.md — Cyclone implementation roadmap

Each phase ends with **exit criteria**, and the next phase doesn't start until they pass. Decisions: `docs/adr/0001-foundational-decisions.md`. Data model: `docs/schema.sql`.

---

## Phase 1 — Foundation, schema, AI-assisted import

Status: built on branch `phase-1/foundation`. Exit criteria met in the automated suite (see below). Open items are listed under **Carried over**.

### Scaffolding
- [x] Monorepo: `web/` (pnpm, Next.js 16 App Router, TS strict, Tailwind v4, shadcn-style components written by hand — the shadcn registry wasn't reachable) and `backend/` (uv, FastAPI, SQLAlchemy 2 async Core + asyncpg, Alembic, procrastinate). *Changed:* no GeoAlchemy2/ORM models; PostGIS via explicit SQL.
- [x] `.env.example`; `Makefile` (`db-up`, `db-migrate`, `api`, `worker`, `web`, `test`, `lint`, `gen-api`); `docker-compose.yml` with PostGIS. *Changed:* local DB is plain PostGIS via compose instead of `supabase start` (Supabase CLI couldn't be installed here); Supabase is used for Auth/Storage/production DB.
- [x] GitHub Actions CI: ruff, ruff format, mypy, pytest against PostGIS service, web lint/typecheck/test/build, OpenAPI client drift check, `check_no_industry_terms.sh` *(workflow written; not yet run on GitHub)*
- [ ] Structured logging with PII redaction; request IDs

### Auth & tenancy
- [x] Supabase Auth in `web/` (email/password + Google OAuth, PKCE callback); FastAPI verifies the Supabase JWT via JWKS or the legacy HS256 secret. Dev-only bypass (`AUTH_DEV_BYPASS` + `NEXT_PUBLIC_AUTH_MODE=dev`), refused in production. *Not yet tested against a live Supabase project.*
- [x] `app_backend` DB role (NOLOGIN in migration, NOBYPASSRLS, read-only on shared OSM tables); `tenant_session` sets `app.workspace_id` / `app.user_id` per transaction
- [x] ~~SECURITY DEFINER functions~~ *Replaced:* RLS policies on `workspaces`/`workspace_members` also admit the authenticated user's rows; workspace creation sets `app.workspace_id` to the new id in the same transaction. No definer functions needed.
- [x] Workspace wizard step 1: company name, offerings, value proposition, languages (default en+ar), currency (AED), phone region

### Schema
- [x] Alembic `0001` executes `migrations/sql/0001_init.sql` (`docs/schema.sql` is a symlink); `0002` app role + `auth.users` FK when present; `0003` job queue
- [x] Guard tests: RLS isolation (including unset setting and cross-tenant writes), role cannot bypass RLS or write OSM tables, active-profile immutability, Places `expires_at` CHECK, mapping-required CHECK, budget exceeded before spend
- [x] Migration upgrade/downgrade test

### Reference catalogs
- [ ] `catalogs/places_types.json` — refresh script written (`backend/scripts/catalogs/refresh_places_types.py`); **not run**: developers.google.com unreachable from this environment. Needed before Phase 2 validators.
- [ ] `catalogs/osm_taginfo.json` — refresh script written (`refresh_taginfo.py`); **not run**: taginfo.openstreetmap.org unreachable. Needed before Phase 2 validators.
- [x] `catalogs/mx_providers.json`, `catalogs/tech_fingerprints.json` (seed; used in Phase 3)
- [x] Added: `header_synonyms.json` (en + ar + common ERP labels), `legal_forms.json`, `public_mail_domains.json`

### Import & AI column mapper
- [x] Upload CSV/XLSX (≤50 MB; encodings incl. cp1256 Arabic; delimiter sniffing; duplicate headers) to Storage (Supabase or local) → `import_jobs` (headers, 20 sample rows, `header_fingerprint`)
- [x] Reuse: a confirmed mapping for the same fingerprint is proposed directly (no LLM call)
- [x] Heuristic pass: header synonyms (en + ar) and value sniffing (phone, email, URL, date); date headers with non-date values are vetoed
- [x] Gemini pass for unresolved columns only (structured output), metered via `UsageMeter`; invalid suggestions dropped, confidence capped at 0.9; sample values can be withheld (`LLM_SEND_SAMPLE_VALUES=false`). *Tested with FakeLLM only — no live Gemini call made yet.*
- [x] Mapping review UI: per-column target + transform dropdowns, confidence/origin badges, live preview of transformed sample rows (server-side `POST …/preview`), confirm & import
- [x] Normalisers: `name_norm` (case, punctuation, legal forms incl. Arabic ذ.م.م, diacritics/letter folding), E.164 (`phonenumbers`), domain (`tldextract`, offline snapshot; mailbox domains ignored), day-first dates + Excel serials, amounts (currency symbols, Arabic-Indic digits, decimal comma)
- [x] Row-level error report (CSV with BOM for Excel/Arabic) and import stats

### Geocoding & entity resolution
- [x] Geocoder chain: OpenCage (permanent storage) → Google fallback with 30-day `storable_until`; precision stored; per-run cache; metered. *Only exercised with mocked HTTP.*
- [x] Accept lat/lng columns directly when present
- [x] Entity resolution v1 (rules in `docs/schema.md`), plus name-only matching for records without coordinates (invoices) and an ambiguity guard
- [x] Match review UI (side by side, accept = merge, reject = keep both)

### Sales history
- [x] Orders import (same mapper, `kind=orders`); links by customer ID or name, creates accounts for unknown customers
- [x] Rollups: `last_order_at`, `order_count`, `lifetime_value`; `customer` vs `lapsed_customer` (`settings.lapsed_after_months`, default 12)

**Exit criteria**
- [x] Two differently shaped exports (Tally-style CSV, Odoo-style XLSX) plus a Zoho-style invoice export import with ≥95% of rows mapped and no manual reformatting (`test_phase1_exit_criteria`)
- [x] Planted duplicates are auto-linked or queued for review; no duplicate accounts created
- [x] All guard tests pass (backend: 90 tests against PostGIS; web: unit tests, lint, typecheck, production build; browser smoke test of the full import flow through the real queue worker)

### Carried over from Phase 1
- [ ] Structured logging + request IDs
- [ ] Run both catalog refresh scripts where the hosts are reachable, and commit the output
- [ ] First live check against a real Supabase project (JWKS, Google OAuth redirect, Storage bucket) and a real Gemini key
- [ ] Nightly purge of expired Google-provenance fields (needed once Google geocoding/Places data is stored — Phase 2)
- [ ] Playwright e2e in CI (the smoke flow is in `web/e2e/import-smoke.mjs`; CI needs API + worker + web running)

---

## Phase 2 — AI ICP configurator & multi-source discovery

### Profile spec
- [ ] `DiscoveryProfileSpec` v1 Pydantic models + JSON Schema export (contract in `docs/schema.md`)
- [ ] Extractor registry with per-extractor param models
- [ ] Validators: taginfo allowlist, Places type table, op whitelist, weight normalisation, size limits; warnings vs errors

### Configurator
- [ ] Wizard: ICP text, qualifying signals/pain points, offerings, languages
- [ ] Geography picker: search OSM admin boundaries (local `osm_admin_boundaries`), draw polygons (terra-draw on Google Maps), upload GeoJSON/KML
- [ ] Target area → H3 cells (`spatial_zones kind=grid_cell`), with adaptive resolution by area size
- [ ] Customer grounding: match a sample of existing customers to OSM/Places types and pass that distribution to the planner as evidence; show "your customers are mostly X, you described Y"
- [ ] Planner prompt (Gemini structured output) → spec → validator warnings → editable chips UI (segments, tags, queries, signals, weights) → activate as a new version
- [ ] Golden eval suite (`-m live`): ≥5 unrelated ICPs compile cleanly

### OSM source ($0)
- [ ] Geofabrik GCC extract → `osm2pgsql` flex style (POI-bearing keys + `boundary=administrative`) → `osm_features`, `osm_admin_boundaries`; weekly refresh with swap of the `active` extract
- [ ] Compiler: `osm_filters` → parameterised SQL (`tags @> $1`, `tags ? $key`, prefix `LIKE`) + `ST_Intersects(zone)`
- [ ] Overpass QL compiler + throttled adapter as fallback for areas outside loaded extracts

### Google Places source
- [ ] Field-mask tiers + client that refuses unmasked requests
- [ ] IDs-only Text Search per H3 cell (`locationRestriction` rectangle = cell bbox), pagination up to 60, saturation → subdivide, `provider_query_cache`
- [ ] Dedup against accounts/source_records → Place Details hydration only for new IDs; `expires_at = fetched_at + 30d`
- [ ] `purge_expired_google_fields` nightly task

### Registry source
- [ ] Registry CSV import via the column mapper (`kind=registry`): license no, trade name (en/ar), activity, address/area, phone
- [ ] Matching to existing accounts/OSM/Places by name + phone + area; activity filter from `segments[].registry_activity_keywords`
- [ ] Registry-only records become prospects only if they geocode at street precision or better

### Orchestration & cost
- [ ] `UsageMeter` + `pricing.yaml`; monthly and per-run budget enforcement
- [ ] Discovery run: estimate (cells × queries × cache-miss rate) → user confirms → run → stats; idempotent and resumable per cell
- [ ] Pins-only map preview: customers vs prospects, to check the core idea early

**Exit criteria**
- Three unrelated ICPs in three UAE areas run end to end with zero code changes
- Actual cost lands within ±20% of the estimate
- Re-running an identical discovery run makes 0 paid Places calls
- An OSM-only run costs $0

---

## Phase 3 — Adaptive enrichment, ICP scoring, multilingual pitches

### Enrichers
- [ ] DNS (async dnspython): MX, SPF, DMARC, MX provider classification via catalog; per-resolver timeouts
- [ ] Web: httpx with robots.txt, size/time/redirect caps, one request per domain at a time; page selection = homepage + `path_hints` + sitemap; trafilatura text (en + ar); header/HTML tech fingerprints
- [ ] Only run what `enrichment_plan` asks for; idempotent on `input_hash`; respect `expires_at`

### Qualification & scoring
- [ ] LLM qualification: a response schema built dynamically from the profile's `llm_*` signals; one call per account; each answer must include an evidence quote + source URL, or `unknown`
- [ ] Deterministic scoring engine: weighted signals, disqualifiers, unknown ≠ false, `icp_confidence`, `score_breakdown`
- [ ] Re-score on profile version change from stored enrichments (no re-fetch unless the spec needs new evidence)
- [ ] Lookalike boost (optional signal `order_recency`/customer similarity) using existing high-LTV customers

### Pitches
- [ ] Pitch generator per language × channel (visit, call, email, message); grounded only on stored evidence; `cited_signal_ids` required; validator rejects uncited claims
- [ ] Arabic output review checklist + RTL rendering in the UI
- [ ] Lazy generation (on view, export or plan) with caching

### Workers & UI
- [ ] Retries with backoff, per-domain rate limits, dead-letter queue, cost per lead metric
- [ ] Lead list: filters, score + confidence, breakdown, evidence links, pitch tabs per language

**Exit criteria**
- On a 200-lead sample, top-10 precision against a human ranking of 30 leads is ≥70%
- Cost per enriched lead is measured and within budget
- Zero pitches with uncited claims in the eval set

---

## Phase 4 — Coverage heatmap, virgin territory, route planner, export

### Map
- [ ] `@vis.gl/react-google-maps` map with AdvancedMarkers + markerclusterer: green = customer, grey = lapsed, red/amber = prospect by score band
- [ ] Server-side bbox + zoom queries (paginate, then cluster); handle 20k+ points
- [ ] OSM attribution overlay

### Coverage & virgin territory
- [ ] Coverage job → `zone_coverage` per H3 cell and admin district (rules in `docs/schema.md`), including `insufficient_data`
- [ ] Heat layer: Google Maps Data layer polygons coloured by class / penetration; deck.gl `H3HexagonLayer` only if >5k cells
- [ ] Virgin-territory scanner: rank contiguous virgin/under-covered clusters by Σ(prospect score × confidence); "why" panel
- [ ] Threshold settings UI per workspace

### Coverage plan generator
- [ ] Params: reps (base location, working days, hours), start date, days, service minutes, min score, include lapsed
- [ ] Territory partitioning: capacitated, workload-balanced clustering (service time + estimated travel) → `plan_territories`
- [ ] Per-day routing: OR-Tools VRP per territory (start/end at rep base, time limit per day), seeded and deterministic → `route_days`, `route_stops`
- [ ] Optional Google Routes `computeRoutes` for final day polylines/ETAs (≤25 waypoints, `use_google_routes` flag, metered)
- [ ] Google Maps navigation deep links per day, split into chunks to respect waypoint limits
- [ ] Plan view: territory colours, day selector, ordered stop list, mark visited/skipped (feeds back into coverage)

### Export
- [ ] CSV + XLSX (openpyxl): Company, Address, Lat, Lng, Phone, Website, ICP Score, Confidence, Enrichment Insights, AI Pitch (per language), Territory, Day, Stop #, Nav link
- [ ] Pre-export estimate for re-hydrating expired Google fields; otherwise mark "refresh required"
- [ ] ODbL attribution row/sheet; Arabic text encoded correctly (UTF-8 BOM for CSV)

**Exit criteria**
- 500 leads, 3 reps, 5 days → plan in <60 s, workload imbalance ≤15%
- Export opens cleanly in Excel (including Arabic)
- Nav links open in Google Maps on Android and iOS

---

## Backlog (not scheduled)
- [ ] CRM push/sync (HubSpot, Pipedrive, Zoho CRM, Salesforce)
- [ ] Workspace cost dashboard (ledger by SKU and run)
- [ ] OSRM self-hosted matrix for better travel times
- [ ] Mobile rep view (PWA) with check-in + notes
- [ ] PDPL/GDPR data-subject request workflow
- [ ] Additional OSM extracts / regions
