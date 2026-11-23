# ADR 0001 — Foundational decisions

Status: accepted · Date: 2026-11-23

## 1. Google Places data: strict TTL
**Decision.** `place_id` is stored indefinitely. Every other Places field lives in `source_records`, with `expires_at ≤ 30 days` enforced by a CHECK. A nightly purge clears copies on `accounts`. Exports re-hydrate expired fields through Place Details (cost estimated first) or mark them "refresh required".
**Why.** Google Maps Platform terms restrict caching Places content other than place IDs. Permanent storage plus CSV export would risk key suspension, and legal exposure for a SaaS reselling the data.
**Cost.** Re-hydration spend at export time, and Google-only fields can go stale in the UI. Mitigated by preferring OSM, registry and CSV values when they exist.

## 2. OSM: Geofabrik extracts in PostGIS, not public Overpass
**Decision.** Load the GCC extract with `osm2pgsql` into shared `osm_features` / `osm_admin_boundaries`, refreshed weekly. Profile `osm_filters` compile to parameterised SQL over `tags jsonb`. An Overpass QL compiler is kept only as a fallback for areas outside the loaded extracts.
**Why.** The public Overpass usage policy doesn't allow multi-tenant bulk querying. Local extracts cost $0 per query and have no rate limits.
**Cost.** A few GB of storage, an import job to operate, and data that's up to a week old.

## 3. Launch market: UAE / GCC
**Decision.** Defaults: languages en + ar (RTL UI), phone region AE, currency AED, configurable working week. The first registry adapter is a generic trade-license / free-zone directory CSV that the user supplies, imported through the column mapper. Government portals are not scraped.
**Why.** This is the user's go-to-market. Implications: street addressing is weak, so store geocode precision and prefer source coordinates. OSM business coverage is patchy, which is why `insufficient_data` exists as a coverage class.

## 4. Hosting & auth: Supabase
**Decision.** Supabase Postgres (PostGIS), Auth (FastAPI verifies JWTs via JWKS) and Storage. The backend uses a dedicated `app_backend` role with RLS forced, never `service_role`.
**Why.** Fewest vendors, native RLS, managed PostGIS.

## 5. Defaults (revisit if they cause pain)
| Area | Choice | Rationale |
|---|---|---|
| Job queue | procrastinate (Postgres, `SKIP LOCKED`) | No Redis to run; jobs are transactional with data |
| Spatial grid | H3 in Python, `bigint` column | No `h3-pg` extension dependency on managed hosts |
| Industry logic | LLM fills a validated spec; code-backed extractor enum | "Zero hardcoded industries" without executing LLM-written logic |
| Routing | OR-Tools VRP on a haversine × circuity matrix; Google Routes optional for display | `optimizeWaypointOrder` is single-vehicle and capped at 25 waypoints; multi-rep, multi-day is a VRP |
| Polygon drawing | terra-draw | Google Maps Drawing Library is deprecated/removed |
| Geocoder | Provider that allows permanent storage; Google as TTL'd fallback | Same storage restriction as Places |
| LLM | Gemini Flash via `google-genai`, model from `GEMINI_MODEL`, behind `LLMClient` | Structured output; swappable |
| API contract | FastAPI OpenAPI → `openapi-typescript` | One source of truth; CI drift check |

## Rejected
- **One `accounts` table with no `source_records`.** No provenance, no TTL enforcement, no review trail for merges.
- **LLM emitting raw Overpass QL or SQL.** Injection risk, unbounded queries, untestable.
- **Unique constraints on phone/domain.** Chains share them, so they're match keys only.
