# cyclone-web

Next.js 16 front end for Cyclone. See the root [README](../README.md) for setup and [AGENTS.md](AGENTS.md) before changing framework code: this Next.js version differs from older ones.

- `pnpm dev` / `pnpm build` / `pnpm start`
- `pnpm test` (Vitest), `pnpm lint`, `pnpm typecheck`
- `pnpm gen:api` regenerates `src/lib/api/schema.d.ts` from `openapi.json` (run `make gen-api` at the root to refresh both)
