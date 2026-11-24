import { Suspense } from "react";

import { BrowserOnly } from "@/lib/auth";

import { LoginForm } from "./login-form";

export default function LoginPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <BrowserOnly>
          <LoginForm />
        </BrowserOnly>
      </Suspense>
    </main>
  );
}
