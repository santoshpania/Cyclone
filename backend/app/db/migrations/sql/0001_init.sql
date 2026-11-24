-- =====================================================================
-- Cyclone — PostgreSQL 16 + PostGIS schema (design v1)
-- Alembic migration 0001 (versions/0001_init.py executes this file). Target: Supabase Postgres.
-- docs/schema.sql is a symlink to this file.
--
-- Design rules (see docs/schema.md):
--  * No CHECK/enum contains an industry value. Enums describe platform
--    mechanics only (statuses, sources, kinds).
--  * All industry semantics live in discovery_profiles.compiled (JSONB,
--    Pydantic-validated DiscoveryProfileSpec) and accounts.attributes.
--  * Every tenant table carries workspace_id and is protected by RLS.
--  * Storage SRID 4326; metre distances via ::geography.
--  * Google Places content (except place_id) must expire (<=30 days).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

-- ── Tenancy ──────────────────────────────────────────────────────────
CREATE TABLE workspaces (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                   text NOT NULL,
  company_profile        jsonb NOT NULL DEFAULT '{}',   -- {company_name, offerings[], value_proposition}
  languages              text[] NOT NULL DEFAULT '{en,ar}',  -- BCP-47
  home_currency          char(3) NOT NULL DEFAULT 'AED',
  default_phone_region   char(2) NOT NULL DEFAULT 'AE',
  settings               jsonb NOT NULL DEFAULT '{}',   -- coverage thresholds, lapsed_after_months, working_days
  monthly_api_budget_usd numeric(10,2) NOT NULL DEFAULT 50,
  created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace_members (
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  user_id      uuid NOT NULL,       -- Supabase auth.users.id (FK added in Supabase migration)
  role         text NOT NULL CHECK (role IN ('owner','admin','manager','rep','viewer')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);

-- ── Discovery profiles (versioned; immutable once active) ────────────
CREATE TABLE discovery_profiles (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id        uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  version             int  NOT NULL,
  status              text NOT NULL CHECK (status IN ('draft','active','archived')),
  input               jsonb NOT NULL,   -- verbatim user input: icp_text, signals_text, offerings, languages, geo refs
  compiled            jsonb,            -- DiscoveryProfileSpec (docs/schema.md)
  spec_schema_version int,
  compiler            jsonb,            -- {model, prompt_sha, generated_at, warnings[], user_edits[]}
  created_by          uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  activated_at        timestamptz,
  UNIQUE (workspace_id, version),
  CHECK (status = 'draft' OR (compiled IS NOT NULL AND spec_schema_version IS NOT NULL))
);
CREATE UNIQUE INDEX discovery_profiles_one_active
  ON discovery_profiles (workspace_id) WHERE status = 'active';

-- Block edits to compiled spec once a profile leaves draft.
CREATE FUNCTION discovery_profiles_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' AND (NEW.compiled IS DISTINCT FROM OLD.compiled
                                OR NEW.input IS DISTINCT FROM OLD.input) THEN
    RAISE EXCEPTION 'discovery_profile % is %; create a new version instead', OLD.id, OLD.status;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER discovery_profiles_immutable BEFORE UPDATE ON discovery_profiles
  FOR EACH ROW EXECUTE FUNCTION discovery_profiles_immutable();

-- ── Shared OSM reference data (NOT tenant-scoped; from Geofabrik extracts) ──
CREATE TABLE osm_extracts (
  id                serial PRIMARY KEY,
  region            text NOT NULL,            -- e.g. 'gcc-states'
  source_url        text NOT NULL,
  extract_timestamp timestamptz NOT NULL,
  imported_at       timestamptz NOT NULL DEFAULT now(),
  feature_count     int,
  status            text NOT NULL CHECK (status IN ('importing','active','superseded','failed'))
);

CREATE TABLE osm_features (
  osm_ref    text PRIMARY KEY,                -- 'node/123' | 'way/456' | 'relation/789'
  extract_id int  NOT NULL REFERENCES osm_extracts,
  name       text,
  name_norm  text,
  tags       jsonb NOT NULL,
  geom       geometry(Point,4326) NOT NULL,   -- centroid for ways/relations
  footprint  geometry(Geometry,4326)
);
CREATE INDEX osm_features_tags_gin ON osm_features USING gin (tags jsonb_path_ops);
CREATE INDEX osm_features_geom_gist ON osm_features USING gist (geom);
CREATE INDEX osm_features_name_trgm ON osm_features USING gin (name_norm gin_trgm_ops);

CREATE TABLE osm_admin_boundaries (
  osm_ref     text PRIMARY KEY,
  extract_id  int  NOT NULL REFERENCES osm_extracts,
  name        text,
  name_ar     text,
  admin_level smallint,
  geom        geometry(MultiPolygon,4326) NOT NULL
);
CREATE INDEX osm_admin_boundaries_geom_gist ON osm_admin_boundaries USING gist (geom);

-- ── Spatial zones: target areas, admin districts, H3 grid cells ──────
CREATE TABLE spatial_zones (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('target_area','admin_area','grid_cell')),
  parent_id    uuid REFERENCES spatial_zones ON DELETE CASCADE,
  name         text,
  origin       text NOT NULL CHECK (origin IN ('user_drawn','osm_boundary','uploaded','generated')),
  external_ref text,                          -- osm_ref of boundary, registry district code
  h3_index     bigint,                        -- computed in Python (h3 lib)
  h3_res       smallint,
  geom         geometry(MultiPolygon,4326) NOT NULL,
  area_km2     double precision,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'grid_cell' OR (h3_index IS NOT NULL AND h3_res IS NOT NULL))
);
CREATE INDEX spatial_zones_geom_gist ON spatial_zones USING gist (geom);
CREATE INDEX spatial_zones_ws_kind ON spatial_zones (workspace_id, kind);
CREATE UNIQUE INDEX spatial_zones_ws_h3 ON spatial_zones (workspace_id, h3_index) WHERE h3_index IS NOT NULL;

-- ── Canonical business entities (customers + prospects) ─────────────
CREATE TABLE accounts (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id      uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  status            text NOT NULL CHECK (status IN ('customer','lapsed_customer','prospect','disqualified','merged')),
  merged_into_id    uuid REFERENCES accounts,
  display_name      text NOT NULL,
  name_norm         text NOT NULL,
  address           text,
  geom              geometry(Point,4326),
  geocode           jsonb,              -- {provider, precision, confidence, storable_until}
  phone_e164        text,
  website_domain    citext,
  google_place_id   text,               -- storable indefinitely
  osm_ref           text,
  registry_ref      text,
  external_crm_id   text,
  attributes        jsonb NOT NULL DEFAULT '{}',   -- open bag; keys declared by the profile
  field_provenance  jsonb NOT NULL DEFAULT '{}',   -- {"phone_e164": {"source":"google_places","expires_at":"..."}}
  icp_score         smallint CHECK (icp_score BETWEEN 0 AND 100),
  icp_confidence    numeric(3,2) CHECK (icp_confidence BETWEEN 0 AND 1),
  scored_profile_id uuid REFERENCES discovery_profiles,
  score_breakdown   jsonb,
  scored_at         timestamptz,
  last_order_at     date,
  order_count       int NOT NULL DEFAULT 0,
  lifetime_value    numeric(14,2),
  assigned_rep      uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'merged') = (merged_into_id IS NOT NULL))
);
CREATE INDEX accounts_geom_gist  ON accounts USING gist (geom);
CREATE INDEX accounts_geog_gist  ON accounts USING gist ((geom::geography));
CREATE INDEX accounts_name_trgm  ON accounts USING gin (name_norm gin_trgm_ops);
CREATE UNIQUE INDEX accounts_ws_place ON accounts (workspace_id, google_place_id)
  WHERE google_place_id IS NOT NULL AND status <> 'merged';
CREATE UNIQUE INDEX accounts_ws_osm   ON accounts (workspace_id, osm_ref)
  WHERE osm_ref IS NOT NULL AND status <> 'merged';
CREATE INDEX accounts_ws_phone  ON accounts (workspace_id, phone_e164);      -- match key, not unique (chains)
CREATE INDEX accounts_ws_domain ON accounts (workspace_id, website_domain);  -- match key, not unique (chains)
CREATE INDEX accounts_ws_status_score ON accounts (workspace_id, status, icp_score DESC);

-- ── Imports & sales history ──────────────────────────────────────────
CREATE TABLE import_jobs (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id       uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  kind               text NOT NULL CHECK (kind IN ('accounts','orders','registry')),
  filename           text NOT NULL,
  storage_uri        text NOT NULL,           -- Supabase Storage path
  header_fingerprint text NOT NULL,           -- reuse confirmed mappings for same export shape
  headers            text[] NOT NULL,
  sample_rows        jsonb NOT NULL,
  row_count          int,
  proposed_mapping   jsonb,                   -- AI/heuristic proposal
  confirmed_mapping  jsonb,                   -- user-confirmed; required before import
  confirmed_by       uuid,
  confirmed_at       timestamptz,
  status             text NOT NULL CHECK (status IN ('uploaded','mapping_proposed','mapping_confirmed',
                                                     'importing','succeeded','failed')),
  stats              jsonb,
  error_report_uri   text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (status NOT IN ('importing','succeeded') OR confirmed_mapping IS NOT NULL)
);
CREATE INDEX import_jobs_ws_fp ON import_jobs (workspace_id, header_fingerprint);

CREATE TABLE historical_orders (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id      uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  account_id        uuid NOT NULL REFERENCES accounts ON DELETE CASCADE,
  import_job_id     uuid REFERENCES import_jobs ON DELETE SET NULL,
  external_order_id text,
  order_date        date NOT NULL,
  amount            numeric(14,2),
  currency          char(3),
  line_items        jsonb,
  raw               jsonb NOT NULL,
  UNIQUE (workspace_id, external_order_id)
);
CREATE INDEX historical_orders_account_date ON historical_orders (account_id, order_date DESC);

-- ── Discovery runs & cost guardrails ─────────────────────────────────
CREATE TABLE discovery_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id    uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  profile_id      uuid NOT NULL REFERENCES discovery_profiles,
  zone_id         uuid NOT NULL REFERENCES spatial_zones,
  sources         text[] NOT NULL,            -- subset of {osm, google_places, registry}
  status          text NOT NULL CHECK (status IN ('estimating','awaiting_confirmation','running',
                                                  'succeeded','failed','cancelled')),
  budget_usd      numeric(10,2) NOT NULL,
  est_cost_usd    numeric(10,4),
  actual_cost_usd numeric(10,4),
  stats           jsonb,
  created_by      uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz
);

-- Raw per-source evidence: entity resolution, provenance, ToS TTLs, PDPL/GDPR deletion.
CREATE TABLE source_records (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id     uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  account_id       uuid REFERENCES accounts ON DELETE SET NULL,
  source           text NOT NULL CHECK (source IN ('osm','google_places','registry','csv_import','manual')),
  source_key       text NOT NULL,             -- place_id | osm_ref | license no | import row hash
  discovery_run_id uuid REFERENCES discovery_runs ON DELETE SET NULL,
  import_job_id    uuid REFERENCES import_jobs ON DELETE SET NULL,
  payload          jsonb NOT NULL,
  geom             geometry(Point,4326),
  match            jsonb,                     -- {method, score, matched_on[]}
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz,
  UNIQUE (workspace_id, source, source_key),
  -- Google Maps Platform terms: Places content other than place_id may not be kept long-term.
  CHECK (source <> 'google_places'
         OR (expires_at IS NOT NULL AND expires_at <= fetched_at + interval '30 days'))
);
CREATE INDEX source_records_expiry ON source_records (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX source_records_account ON source_records (account_id);
CREATE INDEX source_records_geom_gist ON source_records USING gist (geom);

CREATE TABLE match_reviews (               -- ambiguous entity-resolution pairs for human review
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id         uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  source_record_id     uuid NOT NULL REFERENCES source_records ON DELETE CASCADE,
  candidate_account_id uuid NOT NULL REFERENCES accounts ON DELETE CASCADE,
  score                numeric(4,3) NOT NULL,
  evidence             jsonb NOT NULL,       -- {name_sim, distance_m, phone_eq, domain_eq}
  status               text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
  decided_by           uuid,
  decided_at           timestamptz,
  UNIQUE (source_record_id, candidate_account_id)
);

CREATE TABLE provider_query_cache (
  id                bigserial PRIMARY KEY,
  provider          text NOT NULL CHECK (provider IN ('google_places_text','overpass')),
  query_fingerprint text NOT NULL,           -- sha256(normalised textQuery|includedType|lang|region|field_mask)
  h3_index          bigint NOT NULL,
  h3_res            smallint NOT NULL,
  result_keys       text[] NOT NULL,         -- place_ids / osm_refs ONLY (storable identifiers)
  result_count      int NOT NULL,
  saturated         boolean NOT NULL,        -- hit the 60-result cap → subdivide cell
  fetched_at        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz NOT NULL,
  UNIQUE (provider, query_fingerprint, h3_index)
);
-- Shared across workspaces on purpose: it stores only identifiers, and a shared cache
-- is the main lever for Places cost. Readable by backend role; never exposed via API.

CREATE TABLE api_usage_ledger (
  id               bigserial PRIMARY KEY,
  workspace_id     uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  discovery_run_id uuid REFERENCES discovery_runs ON DELETE SET NULL,
  provider         text NOT NULL,            -- google_places | google_routes | gemini | geocoder
  sku              text NOT NULL,
  units            int NOT NULL CHECK (units > 0),
  est_cost_usd     numeric(10,5) NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX api_usage_ledger_ws_time ON api_usage_ledger (workspace_id, created_at);

-- ── Enrichment, scoring, pitches ─────────────────────────────────────
CREATE TABLE enrichments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  account_id   uuid NOT NULL REFERENCES accounts ON DELETE CASCADE,
  profile_id   uuid REFERENCES discovery_profiles,   -- null for profile-independent kinds (dns, web)
  kind         text NOT NULL CHECK (kind IN ('dns','web','llm_qualification','registry')),
  status       text NOT NULL CHECK (status IN ('succeeded','failed','skipped')),
  input_hash   text NOT NULL,                        -- idempotency + LLM cache key
  result       jsonb,
  error        text,
  cost_usd     numeric(10,5),
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz,
  UNIQUE (account_id, kind, input_hash)
);
CREATE INDEX enrichments_latest ON enrichments (account_id, kind, fetched_at DESC);

CREATE TABLE account_pitches (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id     uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  account_id       uuid NOT NULL REFERENCES accounts ON DELETE CASCADE,
  profile_id       uuid NOT NULL REFERENCES discovery_profiles,
  language         text NOT NULL,
  channel          text NOT NULL CHECK (channel IN ('visit','call','email','message')),
  subject          text,
  body             text NOT NULL,
  cited_signal_ids text[] NOT NULL,          -- every claim must trace to stored evidence
  model            text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, profile_id, language, channel)
);

-- ── Coverage snapshots ──────────────────────────────────────────────
CREATE TABLE zone_coverage (
  zone_id                 uuid NOT NULL REFERENCES spatial_zones ON DELETE CASCADE,
  profile_id              uuid NOT NULL REFERENCES discovery_profiles ON DELETE CASCADE,
  workspace_id            uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  active_customers        int NOT NULL,
  lapsed_customers        int NOT NULL,
  icp_prospects           int NOT NULL,
  weighted_prospect_score numeric NOT NULL,
  penetration             numeric CHECK (penetration BETWEEN 0 AND 1), -- active / (active + qualified prospects)
  coverage_class          text NOT NULL CHECK (coverage_class IN ('well_covered','under_covered','virgin','insufficient_data')),
  data_confidence         numeric(3,2) NOT NULL CHECK (data_confidence BETWEEN 0 AND 1),
  sources_present         text[] NOT NULL,
  computed_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (zone_id, profile_id)
);
CREATE INDEX zone_coverage_ws_class ON zone_coverage (workspace_id, profile_id, coverage_class);

-- ── Coverage plans & routes ─────────────────────────────────────────
CREATE TABLE coverage_plans (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  profile_id   uuid NOT NULL REFERENCES discovery_profiles,
  name         text NOT NULL,
  params       jsonb NOT NULL,   -- {reps[{id,base_point}], start_date, days, working_days, work_minutes,
                                 --  service_minutes, min_score, include_lapsed, use_google_routes}
  status       text NOT NULL CHECK (status IN ('queued','solving','ready','failed','archived')),
  summary      jsonb,
  created_by   uuid,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE plan_territories (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id     uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  plan_id          uuid NOT NULL REFERENCES coverage_plans ON DELETE CASCADE,
  label            text NOT NULL,
  rep_id           uuid,
  geom             geometry(MultiPolygon,4326),
  stop_count       int NOT NULL,
  est_work_minutes int NOT NULL
);

CREATE TABLE route_days (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id     uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  plan_id          uuid NOT NULL REFERENCES coverage_plans ON DELETE CASCADE,
  territory_id     uuid NOT NULL REFERENCES plan_territories ON DELETE CASCADE,
  day_index        smallint NOT NULL,
  planned_date     date,
  start_geom       geometry(Point,4326),
  end_geom         geometry(Point,4326),
  encoded_polyline text,
  distance_m       int,
  duration_s       int,
  nav_links        text[] NOT NULL DEFAULT '{}',   -- chunked Google Maps URLs (waypoint limits)
  solver           jsonb,                           -- {engine, matrix_source, objective, runtime_ms}
  UNIQUE (territory_id, day_index)
);

CREATE TABLE route_stops (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id         uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
  route_day_id         uuid NOT NULL REFERENCES route_days ON DELETE CASCADE,
  account_id           uuid NOT NULL REFERENCES accounts,
  stop_order           smallint NOT NULL,
  eta                  time,
  service_minutes      smallint NOT NULL,
  travel_s_from_prev   int,
  distance_m_from_prev int,
  status               text NOT NULL DEFAULT 'planned'
                         CHECK (status IN ('planned','visited','skipped','rescheduled')),
  visit_notes          text,
  UNIQUE (route_day_id, stop_order)
);
CREATE INDEX route_stops_account ON route_stops (account_id);

-- ── Row-level security ───────────────────────────────────────────────
-- Backend connects as a dedicated role (NOT Supabase service_role, which bypasses RLS)
-- and runs `SET LOCAL app.workspace_id = '<uuid>'` at the start of every transaction.
-- Unset setting → current_setting(..., true) is NULL → no rows visible (fail closed).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'discovery_profiles','spatial_zones','accounts','import_jobs',
    'historical_orders','discovery_runs','source_records','match_reviews','api_usage_ledger',
    'enrichments','account_pitches','zone_coverage','coverage_plans','plan_territories',
    'route_days','route_stops']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
                      USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
                      WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

-- Membership lookups happen before a workspace is selected, so workspaces and
-- workspace_members also admit rows belonging to the authenticated user
-- (app.user_id, set by the backend from the verified Supabase JWT).
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members FORCE ROW LEVEL SECURITY;
CREATE POLICY member_access ON workspace_members
  USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
         OR user_id = nullif(current_setting('app.user_id', true), '')::uuid)
  WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid);

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_access ON workspaces
  USING (id = nullif(current_setting('app.workspace_id', true), '')::uuid
         OR id IN (SELECT workspace_id FROM workspace_members
                   WHERE user_id = nullif(current_setting('app.user_id', true), '')::uuid))
  WITH CHECK (id = nullif(current_setting('app.workspace_id', true), '')::uuid);
-- Creating a workspace: the backend generates the id, sets app.workspace_id to it,
-- then inserts the workspace and the owner membership in one transaction.
