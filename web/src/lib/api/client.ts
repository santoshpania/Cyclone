"use client";

import createClient, { type Middleware } from "openapi-fetch";
import { useMemo } from "react";

import { useAuth } from "@/lib/auth";
import { config } from "@/lib/config";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Workspace = Schemas["WorkspaceOut"];
export type ImportJob = Schemas["ImportJobOut"];
export type ColumnMapping = Schemas["ColumnMapping"];
export type FieldMapping = Schemas["FieldMapping"];
export type ImportSchema = Schemas["ImportSchemaOut"];
export type Account = Schemas["AccountOut"];
export type Review = Schemas["ReviewOut"];
export type ImportKind = ImportJob["kind"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(ApiError.describe(detail) ?? `Request failed (${status})`);
  }

  static describe(detail: unknown): string | null {
    if (!detail || typeof detail !== "object") return null;
    const d = (detail as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "problems" in d) return (d as { problems: string[] }).problems.join("; ");
    if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? "").filter(Boolean).join("; ");
    return null;
  }

  get problems(): string[] {
    const d = (this.detail as { detail?: { problems?: string[] } } | null)?.detail;
    return d?.problems ?? [this.message];
  }
}

export function makeApi(authorization: string | null) {
  const api = createClient<paths>({ baseUrl: config.apiUrl });
  const auth: Middleware = {
    onRequest({ request }) {
      if (authorization) request.headers.set("Authorization", authorization);
      return request;
    },
  };
  api.use(auth);
  return api;
}

export type Api = ReturnType<typeof makeApi>;

export function useApi(): Api {
  const { session } = useAuth();
  return useMemo(() => makeApi(session?.authorization ?? null), [session?.authorization]);
}

/** Unwrap an openapi-fetch result or throw ApiError. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (!response.ok || error !== undefined) throw new ApiError(response.status, error);
  return data as T;
}

/** Download an authenticated file (the API needs the Authorization header, so <a href> won't do). */
export async function downloadFile(authorization: string, path: string, filename: string): Promise<void> {
  const res = await fetch(`${config.apiUrl}${path}`, { headers: { Authorization: authorization } });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
