/** Public runtime configuration (NEXT_PUBLIC_* is inlined at build time). */
export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
  /** "supabase" (default) or "dev" — local only, pairs with the backend's AUTH_DEV_BYPASS. */
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE ?? "supabase") as "supabase" | "dev",
};
