"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, use, type ReactNode } from "react";

import { Alert } from "@/components/ui/primitives";
import { unwrap, useApi, type Workspace } from "@/lib/api/client";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const ws = use(WorkspaceContext);
  if (!ws) throw new Error("useWorkspace must be used inside a workspace page");
  return ws;
}

const NAV = [
  { href: "imports", label: "Imports" },
  { href: "accounts", label: "Accounts" },
  { href: "reviews", label: "Duplicate reviews" },
];

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const pathname = usePathname();
  const api = useApi();
  const { data, error } = useAsync(
    () => unwrap(api.GET("/workspaces/{workspace_id}", { params: { path: { workspace_id: workspaceId } } })),
    [api, workspaceId],
  );
  if (error) return <Alert tone="danger">{error.message}</Alert>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading workspace…</p>;
  return (
    <WorkspaceContext value={data}>
      <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border pb-3">
        <span className="font-semibold" dir="auto">
          {data.name}
        </span>
        <nav className="flex gap-1">
          {NAV.map((n) => {
            const href = `/w/${workspaceId}/${n.href}`;
            const active = pathname.startsWith(href);
            return (
              <Link
                key={n.href}
                href={href}
                className={cn("rounded-md px-3 py-1.5 text-sm", active ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted")}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </WorkspaceContext>
  );
}
