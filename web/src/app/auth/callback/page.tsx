import { Suspense } from "react";

import { BrowserOnly } from "@/lib/auth";

import { AuthCallback } from "./callback";

export default function CallbackPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Signing you in…</p>}>
        <BrowserOnly>
          <AuthCallback />
        </BrowserOnly>
      </Suspense>
    </main>
  );
}
