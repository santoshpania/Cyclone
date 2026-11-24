# Cyclone — schema design notes

Source of truth: [`schema.sql`](schema.sql) (becomes Alembic migration `0001`). This file explains *why*, and defines the JSONB contracts the SQL can't express.

## Core principle
No table, enum, or CHECK constraint contains an industry concept. Enums describe platform mechanics only (statuses, data sources, zone kinds). Industry semantics live in two places:

| Where | What |
|---|---|
| `discovery_profiles.compiled` | `DiscoveryProfileSpec`: which OSM tags and Google Places queries to run, what to enrich, how to score, how to pitch |
| `accounts.attributes` | Open key/value bag. Keys come from the active profile's `llm_extract` signals and the import mappings |

## Tables

| Table | Scope | Purpose |
|---|---|---|
| `workspaces`, `workspace_members` | tenant | Tenant root; Supabase `auth.users.id` membership + role |
| `discovery_profiles` | tenant | Versioned ICP spec. **Immutable once active** (trigger). Edits = new version. Scores, pitches and coverage all reference a `profile_id`, so results are reproducible |
| `osm_extracts`, `osm_features`, `osm_admin_boundaries` | **shared** | Geofabrik GCC extract loaded with osm2pgsql. Discovery = SQL over `tags` (`tags @> $1`) + `ST_Intersects` with the target zone. Admin boundaries seed `spatial_zones(kind='admin_area')` |
| `spatial_zones` | tenant | Target areas (drawn/uploaded/OSM boundary), admin districts, H3 grid cells (`h3_index` bigint, computed in Python) |
| `accounts` | tenant | One row per real-world business per workspace, customer or prospect. Match keys: `google_place_id`, `osm_ref` (unique), `phone_e164`, `website_domain` (indexed, **not** unique — chains share them), `name_norm` trigram + distance |
| `source_records` | tenant | Raw evidence per source (OSM, Places, registry, CSV row). Entity resolution input, field provenance, ToS expiry, PDPL/GDPR deletion trail |
| `match_reviews` | tenant | Ambiguous matches (fuzzy name + distance) waiting for a human decision |
| `import_jobs` | tenant | CSV/XLSX upload → proposed mapping (heuristics + Gemini) → **user-confirmed** mapping (CHECK blocks import without one). `header_fingerprint` lets a repeat export from the same ERP reuse its mapping |
| `historical_orders` | tenant | Drives `last_order_at`, `order_count`, `lifetime_value`, and `customer` vs `lapsed_customer` |
| `discovery_runs` | tenant | Estimate → confirm → run, with budget and actual cost |
| `provider_query_cache` | **shared** | `(provider, query_fingerprint, h3_index)` → list of place_ids / osm_refs. Stores identifiers only, which the terms allow. `saturated` = hit the 60-result cap → subdivide |
| `api_usage_ledger` | tenant | Every paid call. `UsageMeter.reserve()` checks it against the monthly and per-run budgets |
| `enrichments` | tenant | DNS / web / LLM / registry results, idempotent on `input_hash` |
| `account_pitches` | tenant | Per language × channel; `cited_signal_ids` required (no ungrounded claims) |
| `zone_coverage` | tenant | Snapshot per (zone, profile): counts, penetration, class, `data_confidence` |
| `coverage_plans`, `plan_territories`, `route_days`, `route_stops` | tenant | Plan → rep territory → day (polyline, chunked nav links) → ordered stops with visit status |

## Google Places data terms (decision: strict TTL)
- `place_id` is stored indefinitely (`accounts.google_place_id`, `provider_query_cache.result_keys`).
- Every other Places field is stored in `source_records` with `expires_at ≤ fetched_at + 30 days`, enforced by a CHECK constraint.
- When Google is the only source for an account field, `field_provenance` records the source and expiry. A nightly purge job nulls those fields once they expire.
- Exports and plan views re-hydrate expired fields through Place Details (cost shown in the pre-export estimate), or mark them "refresh required".
- OSM, registry and customer-CSV data has no expiry. OSM requires ODbL attribution on the map and in every export.

## Coverage classification
Per zone and profile:
- `penetration = active_customers / (active_customers + qualified_prospects)`, where qualified means `icp_score ≥ workspace.settings.coverage.min_score`.
- `data_confidence` (0–1) combines the number of sources present in the cell, OSM POI density relative to the region median, and the share of prospects found by more than one source.
- Class: `insufficient_data` if `data_confidence < settings.coverage.min_confidence`; otherwise `well_covered` (≥ high threshold), `under_covered`, or `virgin` (penetration < low threshold **and** prospects ≥ `min_prospects`). Defaults: 0.40 / 0.10 / 3 / 0.5.
- Lapsed customers count as 0.5 of an active customer in the numerator (configurable).

## Entity resolution order
Implemented in `backend/app/domain/entity_resolution.py` (pure) + `services/resolution.py` (DB).
1. Exact on `google_place_id` / `osm_ref` / `registry_ref` / `external_crm_id` → link.
2. Same `phone_e164` or `website_domain` and ≤ 300 m (or no coordinates but similar name) → link; same identifier but far apart or a dissimilar name → review (chains share numbers).
3. `similarity(name_norm) ≥ 0.6` and ≤ 150 m → score; auto-link at ≥ 0.85, else `match_reviews`.
4. No coordinates on either side (typical for invoices): exact normalised name and no conflicting identifier → link; near-identical name, or a conflicting phone/domain/ID → review.
5. Two or more equally strong name-only matches → review, never a silent pick.
6. Otherwise create a new account.

A "review" outcome still creates the new account (nothing is lost); accepting the review merges it into the candidate, moving source records and orders, and marks it `merged`.

## RLS for membership lookups
Tenant tables match `workspace_id = app.workspace_id`. `workspaces` and `workspace_members` also admit rows for the authenticated user (`app.user_id`), so the API can list a user's workspaces before one is selected. Creating a workspace sets `app.workspace_id` to the new id first, so the `WITH CHECK` passes inside the same transaction.

## `DiscoveryProfileSpec` v1
Pydantic model in `backend/app/profile/spec.py`; this JSON is the contract. Gemini fills it; validators check it; the user can edit it before activation.

```json
{
  "schema_version": 1,
  "icp_summary": "Independent dental clinics and pharmacies with 1–10 locations",
  "segments": [{
    "id": "seg_1",
    "label": "Dental clinics",
    "osm_filters": [
      {"all": [{"key": "amenity", "op": "=", "value": "dentist"}]},
      {"all": [{"key": "healthcare", "op": "=", "value": "dentist"}]}
    ],
    "places_queries": [
      {"text_query": "dental clinic", "included_type": "dentist", "strict_type_filtering": true}
    ],
    "registry_activity_keywords": ["dental", "orthodont"]
  }],
  "exclusions": {"name_keywords": ["hospital"], "places_types": ["hospital"]},
  "enrichment_plan": {
    "dns": true,
    "web": {"enabled": true, "max_pages": 3, "path_hints": ["/about", "/services"]},
    "llm_qualification": true,
    "registry": false,
    "places_contact_fields": true
  },
  "signals": [
    {"id": "high_volume", "label": "High review volume", "source": "places",
     "extractor": "numeric_threshold", "params": {"field": "userRatingCount", "gte": 100}, "weight": 15},
    {"id": "no_dmarc", "label": "No DMARC record", "source": "dns",
     "extractor": "dns_record_absent", "params": {"record": "dmarc"}, "weight": 10},
    {"id": "multi_branch", "label": "Multiple branches", "source": "web",
     "extractor": "llm_boolean", "params": {"question": "Does the business operate more than one location?"}, "weight": 20}
  ],
  "disqualifiers": [
    {"source": "places", "extractor": "field_equals",
     "params": {"field": "businessStatus", "value": "CLOSED_PERMANENTLY"}}
  ],
  "pitch": {"languages": ["en", "ar"], "channels": ["visit", "message"], "tone": "consultative", "guidance": "..."}
}
```
*(The dental example is test-fixture data, not code.)*

### Validation rules
- `osm_filters[].key` must be in the bundled taginfo snapshot allowlist. Values used fewer than N times in the region raise a warning, not an error.
- `op` ∈ `=`, `!=`, `~` (prefix only; no free regex), `exists`.
- `places_queries[].included_type` must be in the bundled Places type table.
- `signals[].extractor` must be in the extractor registry. `params` are validated by that extractor's own Pydantic model.
- Weights are normalised to 100. At most 12 signals and 8 segments per profile (cost and quality bound).

### Extractor registry (the only "hardcoded" logic: platform primitives)
| Extractor | Sources | Params |
|---|---|---|
| `numeric_threshold` | places, registry, orders | `field`, `gte`/`lte` |
| `field_equals` / `field_in` | any | `field`, `value(s)` |
| `keyword_present` | web | `keywords[]`, `languages[]` |
| `dns_record_present` / `dns_record_absent` | dns | `record` ∈ mx, spf, dmarc |
| `mx_provider_in` | dns | `providers[]` (from bundled MX catalog) |
| `tech_detected` | web | `technologies[]` (from bundled fingerprint catalog) |
| `llm_boolean` | web | `question` |
| `llm_scale` | web | `question`, `scale` 1–5 |
| `llm_extract` | web | `attribute_key`, `type` ∈ int, text, enum, `options[]` |
| `order_recency` | orders | `months` |
| `registry_field_match` | registry | `field`, `value(s)` |

**Unknown is not false.** A signal with no evidence contributes 0 to the score and lowers `icp_confidence`. It is not scored as a negative.

## Column-mapping contract (`import_jobs.*_mapping`)
```json
{"fields": [
  {"target": "display_name", "source_columns": ["Customer Name"], "transform": "trim", "confidence": 0.98},
  {"target": "address", "source_columns": ["Addr1","Area","Emirate"], "transform": "concat", "params": {"sep": ", "}, "confidence": 0.9},
  {"target": "phone_e164", "source_columns": ["Mobile"], "transform": "phone_e164", "params": {"default_region": "AE"}, "confidence": 0.95},
  {"target": "attributes.segment", "source_columns": ["Cust Group"], "transform": "trim", "confidence": 0.6}
], "unmapped": ["Internal Code"]}
```
Transforms are an enum: `trim`, `concat`, `split_part`, `parse_date`, `parse_amount`, `phone_e164`, `domain`, `lowercase`, `coalesce`, `coordinate`. Gemini picks from them and never writes code. Each field also records `origin` (`reused`, `heuristic`, `llm`, `user`) and `confidence`; LLM confidence is capped at 0.9.

Import statuses: `uploaded` → `mapping_proposed` → `mapping_confirmed` → `importing` → `succeeded` | `failed`. A CHECK blocks `importing`/`succeeded` without a confirmed mapping.
