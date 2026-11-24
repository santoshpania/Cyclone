"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";

/** OAuth / email-confirmation landing. The Supabase browser client exchanges the PKCE code
 * found in the URL; we wait for the session and move on. */
export function AuthCallback() {
  const { session, loading, supabase } = useAuth();
  const router = useRouter();
  // Rendered only in the browser (BrowserOnly suspends during prerender), so window is safe here.
  const [error, setError] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("error_description"),
  );

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code");
    if (code && supabase && !session) {
      void supabase.auth.exchangeCodeForSession(code).then(({ error: e }) => {
        if (e && !/already|used/i.test(e.message)) setError(e.message);
      });
    }
  }, [supabase, session]);

  useEffect(() => {
    if (!loading && session) {
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/workspaces");
    }
  }, [loading, session, router]);

  return <p className="text-sm text-muted-foreground">{error ? `Sign-in failed: ${error}` : "Signing you in…"}</p>;
}
