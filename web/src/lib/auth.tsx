"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { use, useSyncExternalStore, type ReactNode } from "react";
import { browser } from "react-dom";

import { config } from "@/lib/config";

export type Session = { userId: string; email: string | null; authorization: string };
type Snapshot = { session: Session | null; loading: boolean };

export type AuthState = Snapshot & {
  supabase: SupabaseClient | null;
  signOut: () => Promise<void>;
  /** Dev mode only: act as the given user id (backend must run with AUTH_DEV_BYPASS). */
  devSignIn: (userId: string) => void;
};

const DEV_KEY = "cyclone.devUserId";
const SERVER_SNAPSHOT: Snapshot = { session: null, loading: true };

/**
 * One auth store for the whole app. Next.js keeps previously visited routes mounted (hidden),
 * so per-route React state would disagree about who is signed in; a module-level store
 * read through useSyncExternalStore keeps every tree in sync.
 */
let snapshot: Snapshot = SERVER_SNAPSHOT;
let started = false;
let client: SupabaseClient | null = null;
const listeners = new Set<() => void>();

function emit(next: Snapshot) {
  snapshot = next;
  for (const l of listeners) l();
}

export function supabaseClient(): SupabaseClient | null {
  if (config.authMode === "dev") return null;
  if (!config.supabaseUrl || !config.supabaseAnonKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set");
  }
  client ??= createBrowserClient(config.supabaseUrl, config.supabaseAnonKey);
  return client;
}

function toSession(s: { user: { id: string; email?: string | null }; access_token: string } | null): Session | null {
  return s ? { userId: s.user.id, email: s.user.email ?? null, authorization: `Bearer ${s.access_token}` } : null;
}

function devSession(): Session | null {
  const id = window.localStorage.getItem(DEV_KEY);
  return id ? { userId: id, email: "dev@localhost", authorization: `Dev ${id}` } : null;
}

function start() {
  if (started || typeof window === "undefined") return;
  started = true;
  if (config.authMode === "dev") {
    snapshot = { session: devSession(), loading: false };
    return;
  }
  const sb = supabaseClient();
  if (!sb) return;
  void sb.auth.getSession().then(({ data }) => emit({ session: toSession(data.session), loading: false }));
  sb.auth.onAuthStateChange((_event, s) => emit({ session: toSession(s), loading: false }));
}

function subscribe(listener: () => void): () => void {
  start();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Snapshot {
  start();
  return snapshot;
}

const actions = {
  signOut: async () => {
    const sb = config.authMode === "dev" ? null : supabaseClient();
    if (sb) await sb.auth.signOut();
    window.localStorage.removeItem(DEV_KEY);
    emit({ session: null, loading: false });
  },
  devSignIn: (userId: string) => {
    window.localStorage.setItem(DEV_KEY, userId);
    emit({ session: devSession(), loading: false });
  },
};

export function useAuth(): AuthState {
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => SERVER_SNAPSHOT);
  return { ...snap, supabase: typeof window === "undefined" ? null : supabaseClient(), ...actions };
}

/** Render children only in the browser (they read browser storage / window). Suspends during prerender. */
export function BrowserOnly({ children }: { children: ReactNode }) {
  use(browser("Reads the auth session and URL from the browser."));
  return children;
}
