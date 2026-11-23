# PLAN.md — Implementation roadmap

Each phase ends with **exit criteria**, and the next phase doesn't start until they pass. Decisions: `docs/adr/0001-foundational-decisions.md`. Data model: `docs/schema.sql`.

---

## Phase 1 — Foundation, schema, AI-assisted import

### Scaffolding
- [ ] Monorepo: `web/` (pnpm, Next.js App Router, TS strict, Tailwind, shadcn/ui) and `backend/` (uv, FastAPI, SQLAlchemy 2 async + asyncpg + GeoAlchemy2, Alembic, procrastinate)
- [ ] `supabase/` local stack (`supabase start`); `.env.example`; `Makefile` (`dev`, `test`, `lint`, `osm-import`)
- [ ] GitHub Actions CI: ruff, mypy, pytest (`not live`) against PostGIS, web typecheck/lint/test, OpenAPI client drift check, `check_no_industry_terms.sh`
- [ ] Structured logging with PII redaction; request IDs

### Auth & tenancy
- [ ] Supabase Auth in `web/` (email + Google OAuth); FastAPI verifies the Supabase JWT via JWKS
- [ ] `app_backend` DB role (not `service_role`); `db/session.py` runs `SET LOCAL app.workspace_id` per transaction
- [ ] SECURITY DEFINER functions: `create_workspace()`, `my_workspaces()`
- [ ] Workspace wizard step 1: company name, offerings, value proposition, languages (default en+ar), currency (AED)

### Schema
- [ ] Alembic `0001` from `docs/schema.sql` (+ FK `workspace_members.user_id → auth.users`)
- [ ] Guard tests: RLS isolation (including unset setting), active-profile immutability, Places `expires_at` CHECK, mapping-required CHECK
- [ ] Migration upgrade/downgrade test

### Reference catalogs
- [ ] `catalogs/places_types.json` (Places API Table A types) + refresh script
- [ ] `catalogs/osm_taginfo.json` (keys/values with usage counts for POI keys) + refresh script
- [ ] `catalogs/mx_providers.json`, `catalogs/tech_fingerprints.json` (seed; used in Phase 3)

### Import & AI column mapper
- [ ] Upload CSV/XLSX (≤50 MB) to Supabase Storage → `import_jobs` (headers, 20 sample rows, `header_fingerprint`)
- [ ] Reuse: if a confirmed mapping exists for the same fingerprint, propose it directly (no LLM call)
- [ ] Heuristic pass: header synonyms (en + ar) and value sniffing (phone, URL, date, amount, lat/lng)
- [ ] Gemini pass for unresolved columns only → `{target, source_columns[], transform(enum), params, confidence}`; low confidence → flagged
- [ ] Mapping review UI: column → target dropdowns, transform preview on sample rows, confirm
- [ ] Normalisers: `name_norm` (case, punctuation, legal suffixes like LLC/FZE/FZCO/Est. as a catalog, Arabic diacritics), E.164 (`phonenumbers`, region AE), domain (`tldextract`), locale-aware dates and amounts
- [ ] Row-level error report (CSV download) and import stats

### Geocoding & entity resolution
- [ ] Geocoder adapter: primary provider whose terms allow permanent storage; Google Geocoding fallback with TTL; store `geocode.precision`; batch + cache
- [ ] Accept lat/lng columns directly when present (common in UAE ERPs and field apps)
- [ ] Entity resolution v1 (rules in `docs/schema.md`): exact IDs → phone/domain + ≤300 m → trigram ≥0.6 + ≤150 m → auto-merge ≥0.85, else `match_reviews`
- [ ] Match review UI (accept/reject, side by side)

### Sales history
- [ ] Orders import (same mapper, `kind=orders`); creates or links accounts by customer key
- [ ] Rollups: `last_order_at`, `order_count`, `lifetime_value`; status `customer` vs `lapsed_customer` (`settings.lapsed_after_months`, default 12)

**Exit criteria**
- Two differently shaped exports (e.g. a Tally-style and a Zoho/Odoo-style customer list, plus one invoice export) import with ≥95% of rows mapped and no manual reformatting
- Planted duplicates are surfaced (auto-merged or queued)
- All guard tests pass in CI

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
