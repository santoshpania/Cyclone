"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Alert, Badge, Card, PageHeader } from "@/components/ui/primitives";
import { unwrap, useApi } from "@/lib/api/client";
import { useAsync } from "@/lib/use-async";

export default function WorkspacesPage() {
  const api = useApi();
  const { data, error, loading } = useAsync(() => unwrap(api.GET("/workspaces")), [api]);

  return (
    <>
      <PageHeader title="Workspaces" description="Each workspace has its own customers, ICP and territories.">
        <Link href="/workspaces/new" className={buttonVariants()}>
          New workspace
        </Link>
      </PageHeader>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      {loading && !data ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      {data && data.length === 0 ? (
        <Card className="text-center">
          <p className="mb-4 text-muted-foreground">You don&apos;t have a workspace yet.</p>
          <Link href="/workspaces/new" className={buttonVariants()}>
            Create your first workspace
          </Link>
        </Card>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((w) => (
          <Link key={w.id} href={`/w/${w.id}/imports`} className="block">
            <Card className="h-full transition-colors hover:bg-muted">
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-semibold">{w.name}</h2>
                <Badge>{w.role}</Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground" dir="auto">
                {String((w.company_profile as { company_name?: string }).company_name ?? "")}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}
