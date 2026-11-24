import { Suspense } from "react";

import { RequireAuth } from "@/components/app/require-auth";
import { BrowserOnly } from "@/lib/auth";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<p className="p-8 text-sm text-muted-foreground">Loading…</p>}>
      <BrowserOnly>
        <RequireAuth>{children}</RequireAuth>
      </BrowserOnly>
    </Suspense>
  );
}
