"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ImportStatus, KIND_LABEL } from "@/components/app/status";
import { Button } from "@/components/ui/button";
import { Alert, Card, Label, PageHeader, Select } from "@/components/ui/primitives";
import { unwrap, useApi, type ImportKind } from "@/lib/api/client";
import { useAsync } from "@/lib/use-async";

export default function ImportsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const api = useApi();
  const router = useRouter();
  const jobs = useAsync(
    () => unwrap(api.GET("/workspaces/{workspace_id}/imports", { params: { path: { workspace_id: workspaceId } } })),
    [api, workspaceId],
  );
  const [kind, setKind] = useState<ImportKind>("accounts");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const job = await unwrap(
        api.POST("/workspaces/{workspace_id}/imports", {
          params: { path: { workspace_id: workspaceId } },
          body: { file: file as unknown as string, kind },
          bodySerializer: (body) => {
            const fd = new FormData();
            fd.append("file", body.file as unknown as Blob);
            fd.append("kind", body.kind);
            return fd;
          },
        }),
      );
      router.push(`/w/${workspaceId}/imports/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Imports"
        description="Upload customer lists and order history exactly as your ERP or CRM exports them. Cyclone proposes a column mapping; you confirm it."
      />
      <Card className="mb-8 max-w-2xl">
        <form className="flex flex-wrap items-end gap-4" onSubmit={(e) => void upload(e)}>
          <div className="min-w-48 flex-1 space-y-1.5">
            <Label htmlFor="kind">What&apos;s in the file?</Label>
            <Select id="kind" value={kind} onChange={(e) => setKind(e.target.value as ImportKind)}>
              <option value="accounts">Customer list</option>
              <option value="orders">Orders / invoices</option>
              <option value="registry">Licence registry (public data)</option>
            </Select>
          </div>
          <div className="min-w-56 flex-[2] space-y-1.5">
            <Label htmlFor="file">CSV or Excel file (max 50 MB)</Label>
            <input
              id="file"
              type="file"
              accept=".csv,.tsv,.txt,.xlsx,.xlsm"
              className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-sm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <Button type="submit" disabled={!file || busy}>
            {busy ? "Reading file…" : "Upload"}
          </Button>
        </form>
        {error ? (
          <Alert tone="danger" className="mt-4">
            {error}
          </Alert>
        ) : null}
      </Card>

      {jobs.error ? <Alert tone="danger">{jobs.error.message}</Alert> : null}
      {jobs.data && jobs.data.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Rows</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.id} className="border-t border-border hover:bg-muted/50">
                  <td className="px-4 py-2">
                    <Link className="font-medium underline-offset-4 hover:underline" href={`/w/${workspaceId}/imports/${j.id}`}>
                      {j.filename}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{KIND_LABEL[j.kind]}</td>
                  <td className="px-4 py-2 tabular-nums">{j.row_count ?? "—"}</td>
                  <td className="px-4 py-2">
                    <ImportStatus status={j.status} />
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{new Date(j.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : jobs.data ? (
        <p className="text-sm text-muted-foreground">No imports yet.</p>
      ) : null}
    </>
  );
}
