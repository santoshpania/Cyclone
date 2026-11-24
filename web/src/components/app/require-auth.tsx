"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading, signOut } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !session) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }, [loading, session, router]);
  if (loading || !session) return <p className="p-8 text-sm text-muted-foreground">Checking your session…</p>;
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link href="/workspaces" className="font-semibold tracking-tight">
            Cyclone
          </Link>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span className="hidden sm:inline">{session.email}</span>
            <Button variant="ghost" size="sm" onClick={() => void signOut().then(() => router.replace("/login"))}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
