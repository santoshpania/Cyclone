"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { AccountStatus } from "@/components/app/status";
import { useWorkspace } from "@/components/app/workspace-context";
import { Button } from "@/components/ui/button";
import { Alert, Input, PageHeader, Select } from "@/components/ui/primitives";
import { unwrap, useApi } from "@/lib/api/client";
import { useAsync } from "@/lib/use-async";

const PAGE = 50;
type StatusFilter = "customer" | "lapsed_customer" | "prospect" | "disqualified" | "merged";

export default function AccountsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const workspace = useWorkspace();
  const api = useApi();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter | "">("");
  const [offset, setOffset] = useState(0);
  const page = useAsync(
    () =>
      unwrap(
        api.GET("/workspaces/{workspace_id}/accounts", {
          params: {
            path: { workspace_id: workspaceId },
            query: { q: query || undefined, status_filter: status || undefined, limit: PAGE, offset },
          },
        }),
      ),
    [api, workspaceId, query, status, offset],
  );
  const money = new Intl.NumberFormat(undefined, { style: "currency", currency: workspace.home_currency, maximumFractionDigits: 0 });

  return (
    <>
      <PageHeader title="Accounts" description={page.data ? `${page.data.total} accounts` : undefined} />
      <form
        className="mb-4 flex flex-wrap gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setQuery(q.trim());
        }}
      >
        <Input className="max-w-xs" placeholder="Search name, phone or customer ID" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select
          className="max-w-48"
          aria-label="Status"
          value={status}
          onChange={(e) => {
            setOffset(0);
            setStatus(e.target.value as StatusFilter | "");
          }}
        >
          <option value="">All (except merged)</option>
          <option value="customer">Customers</option>
          <option value="lapsed_customer">Lapsed customers</option>
          <option value="prospect">Prospects</option>
          <option value="merged">Merged duplicates</option>
        </Select>
        <Button type="submit" variant="outline">
          Search
        </Button>
      </form>
      {page.error ? <Alert tone="danger">{page.error.message}</Alert> : null}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Phone</th>
              <th className="px-4 py-2 font-medium">Website</th>
              <th className="px-4 py-2 font-medium">Location</th>
              <th className="px-4 py-2 text-right font-medium">Orders</th>
              <th className="px-4 py-2 text-right font-medium">Lifetime value</th>
              <th className="px-4 py-2 font-medium">Last order</th>
            </tr>
          </thead>
          <tbody>
            {page.data?.items.map((a) => (
              <tr key={a.id} className="border-t border-border">
                <td className="px-4 py-2" dir="auto">
                  <div className="font-medium">{a.display_name}</div>
                  {a.address ? <div className="max-w-72 truncate text-xs text-muted-foreground">{a.address}</div> : null}
                </td>
                <td className="px-4 py-2">
                  <AccountStatus status={a.status} />
                </td>
                <td className="px-4 py-2 tabular-nums whitespace-nowrap">{a.phone_e164 ?? "—"}</td>
                <td className="px-4 py-2">{a.website_domain ?? "—"}</td>
                <td className="px-4 py-2 text-xs text-muted-foreground">
                  {a.lat !== null && a.lng !== null ? `${a.lat.toFixed(4)}, ${a.lng.toFixed(4)}` : "Not located"}
                  {a.geocode_precision ? ` · ${a.geocode_precision}` : ""}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{a.order_count}</td>
                <td className="px-4 py-2 text-right tabular-nums">{a.lifetime_value !== null ? money.format(a.lifetime_value) : "—"}</td>
                <td className="px-4 py-2 whitespace-nowrap">{a.last_order_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {page.data && page.data.total > PAGE ? (
        <div className="mt-4 flex items-center gap-3 text-sm">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </Button>
          <span className="text-muted-foreground">
            {offset + 1}–{Math.min(offset + PAGE, page.data.total)} of {page.data.total}
          </span>
          <Button variant="outline" size="sm" disabled={offset + PAGE >= page.data.total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </Button>
        </div>
      ) : null}
    </>
  );
}
