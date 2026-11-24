"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, PageHeader } from "@/components/ui/primitives";
import { unwrap, useApi, type Account } from "@/lib/api/client";
import { useAsync } from "@/lib/use-async";

function Side({ title, account }: { title: string; account: Account }) {
  const rows: [string, string | null][] = [
    ["Phone", account.phone_e164],
    ["Website", account.website_domain],
    ["Customer ID", account.external_crm_id],
    ["Address", account.address],
    ["Orders", String(account.order_count)],
  ];
  return (
    <div className="min-w-0 flex-1">
      <div className="mb-1 text-xs text-muted-foreground">{title}</div>
      <div className="mb-2 font-semibold" dir="auto">
        {account.display_name}
      </div>
      <dl className="space-y-1 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="w-24 shrink-0 text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words" dir="auto">
              {v ?? "—"}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function ReviewsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const api = useApi();
  const reviews = useAsync(
    () => unwrap(api.GET("/workspaces/{workspace_id}/match-reviews", { params: { path: { workspace_id: workspaceId } } })),
    [api, workspaceId],
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(id: string, decision: "accept" | "reject") {
    setBusy(id);
    setError(null);
    try {
      await unwrap(
        api.POST("/workspaces/{workspace_id}/match-reviews/{review_id}", {
          params: { path: { workspace_id: workspaceId, review_id: id } },
          body: { decision },
        }),
      );
      reviews.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Possible duplicates"
        description="Records that look like the same business but Cyclone wasn't sure. Merging keeps the existing account and moves orders and history onto it."
      />
      {error ? <Alert tone="danger" className="mb-4">{error}</Alert> : null}
      {reviews.error ? <Alert tone="danger">{reviews.error.message}</Alert> : null}
      {reviews.data?.length === 0 ? <p className="text-sm text-muted-foreground">Nothing to review.</p> : null}
      <div className="space-y-4">
        {reviews.data?.map((r) => {
          const ev = r.evidence as { matched_on?: string[]; conflicts?: string[]; distance_m?: number | null };
          return (
            <Card key={r.id}>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Badge tone={r.score >= 0.75 ? "warning" : "neutral"}>Match score {Math.round(r.score * 100)}%</Badge>
                {ev.matched_on?.map((m) => <Badge key={m} tone="info">same {m.replace("_e164", "")}</Badge>)}
                {ev.conflicts?.map((c) => <Badge key={c} tone="danger">different {c.replace("_e164", "").replace("_", " ")}</Badge>)}
                {typeof ev.distance_m === "number" ? <Badge>{Math.round(ev.distance_m)} m apart</Badge> : null}
              </div>
              <div className="flex flex-col gap-6 sm:flex-row">
                <Side title="Existing account (kept)" account={r.candidate} />
                <Side title="New record" account={r.incoming} />
              </div>
              <div className="mt-4 flex gap-3">
                <Button disabled={busy === r.id} onClick={() => void decide(r.id, "accept")}>
                  Same business — merge
                </Button>
                <Button variant="outline" disabled={busy === r.id} onClick={() => void decide(r.id, "reject")}>
                  Different businesses
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
