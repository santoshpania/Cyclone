"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Alert, Card, Input, Label } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { config } from "@/lib/config";

function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/workspaces";
}

export function LoginForm() {
  const { supabase, devSignIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "danger" | "success"; text: string } | null>(null);

  if (config.authMode === "dev") {
    return (
      <Card className="w-full max-w-sm space-y-4">
        <h1 className="text-xl font-semibold">Local dev sign-in</h1>
        <Alert tone="warning">
          Dev auth mode: no password. Only works when the API runs with AUTH_DEV_BYPASS in development.
        </Alert>
        <Button
          className="w-full"
          onClick={() => {
            devSignIn(window.localStorage.getItem("cyclone.devUserId") ?? crypto.randomUUID());
            router.replace(nextPath());
          }}
        >
          Continue as dev user
        </Button>
      </Card>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setMessage(null);
    const { error, data } =
      mode === "signin"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({
            email,
            password,
            options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
          });
    setBusy(false);
    if (error) return setMessage({ tone: "danger", text: error.message });
    if (data.session) router.replace(nextPath());
    else setMessage({ tone: "success", text: "Check your email to confirm your address, then sign in." });
  }

  async function google() {
    if (!supabase) return;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath())}` },
    });
    if (error) setMessage({ tone: "danger", text: error.message });
  }

  return (
    <Card className="w-full max-w-sm">
      <h1 className="mb-1 text-xl font-semibold">{mode === "signin" ? "Sign in to Cyclone" : "Create your account"}</h1>
      <p className="mb-6 text-sm text-muted-foreground">Use your work email.</p>
      <form className="space-y-4" onSubmit={(e) => void submit(e)}>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {message ? <Alert tone={message.tone}>{message.text}</Alert> : null}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <Button variant="outline" className="mt-3 w-full" onClick={() => void google()}>
        Continue with Google
      </Button>
      <button
        type="button"
        className="mt-4 w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
        onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
      >
        {mode === "signin" ? "New here? Create an account" : "Already have an account? Sign in"}
      </button>
    </Card>
  );
}
