# Cyclone

Industry-agnostic AI platform for territory coverage, virgin-market discovery and sales copilot work.

You describe your products and ideal customer in plain language. Cyclone turns that into discovery rules for OpenStreetMap, Google Places and public registries. It enriches and scores the businesses it finds, maps them against your existing customers to show covered, under-covered and virgin territory, and builds balanced multi-day rep routes with exportable contact lists and AI-written pitches.

**Status:** design phase. No application code yet.

| Doc | What's in it |
|---|---|
| [`PLAN.md`](PLAN.md) | Phased roadmap with checkboxes and exit criteria |
| [`CLAUDE.md`](CLAUDE.md) | Architecture rules, API cost guardrails, data terms, testing conventions |
| [`docs/schema.sql`](docs/schema.sql) | PostgreSQL + PostGIS schema |
| [`docs/schema.md`](docs/schema.md) | Schema rationale and JSONB contracts (`DiscoveryProfileSpec`, column mappings) |
| [`docs/adr/`](docs/adr/) | Architecture decision records |

**Stack:** Next.js (App Router) · TypeScript · Tailwind · shadcn/ui · `@vis.gl/react-google-maps` · FastAPI · PostgreSQL/PostGIS on Supabase · Gemini Flash · OR-Tools

**Launch market:** UAE / GCC (English + Arabic).
