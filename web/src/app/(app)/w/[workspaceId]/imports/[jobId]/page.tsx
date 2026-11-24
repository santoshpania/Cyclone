"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ImportStatus, KIND_LABEL } from "@/components/app/status";
import { useWorkspace } from "@/components/app/workspace-context";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, PageHeader, Select } from "@/components/ui/primitives";
import { ApiError, downloadFile, unwrap, useApi, type ImportJob, type ImportSchema } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import {
  IGNORE,
  KEEP_AS_ATTRIBUTE,
  allowedTransforms,
  localProblems,
  retarget,
  toColumnChoices,
  toMapping,
  type ColumnChoice,
} from "@/lib/mapping";
import { useAsync } from "@/lib/use-async";

const TRANSFORM_LABEL: Record<string, string> = {
  trim: "As is",
  concat: "Join columns",
  coalesce: "First non-empty",
  split_part: "Part of value",
  lowercase: "Lowercase",
  parse_date: "Date",
  parse_amount: "Amount",
  phone_e164: "Phone number",
  domain: "Website domain",
  coordinate: "Coordinate",
};

const STAT_LABEL: Record<string, string> = {
  rows_total: "Rows in file",
  rows_imported: "Imported",
  rows_failed: "Failed",
  rows_skipped_duplicate: "Already imported",
  accounts_created: "New accounts",
  accounts_matched: "Matched existing",
  reviews_created: "Possible duplicates",
  orders_inserted: "Orders added",
  geocoded: "Geocoded",
  geocode_failed: "Couldn't geocode",
};

function confidenceTone(c: number | null): "success" | "warning" | "danger" | "neutral" {
  if (c === null) return "neutral";
  if (c >= 0.85) return "success";
  if (c >= 0.65) return "warning";
  return "danger";
}

export default function ImportJobPage() {
  const { workspaceId, jobId } = useParams<{ workspaceId: string; jobId: string }>();
  const workspace = useWorkspace();
  const api = useApi();
  const { session } = useAuth();
  const path = { workspace_id: workspaceId, job_id: jobId };

  const job = useAsync(() => unwrap(api.GET("/workspaces/{workspace_id}/imports/{job_id}", { params: { path } })), [api, jobId]);
  const schema = useAsync(
    () => (job.data ? unwrap(api.GET("/meta/import-schema/{kind}", { params: { path: { kind: job.data.kind } } })) : Promise.resolve(undefined)),
    [api, job.data?.kind],
  );

  // After "confirm and import" the job stays `mapping_confirmed` until a worker picks it up,
  // then `importing`; poll through both.
  const [queued, setQueued] = useState(false);
  const status = job.data?.status;
  const polling = status === "importing" || (queued && status === "mapping_confirmed");
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(job.reload, 2000);
    return () => clearInterval(t);
  }, [polling, job.reload]);

  if (job.error) return <Alert tone="danger">{job.error.message}</Alert>;
  if (!job.data || !schema.data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const j = job.data;
  return (
    <>
      <div className="mb-2 text-sm">
        <Link className="text-muted-foreground hover:underline" href={`/w/${workspaceId}/imports`}>
          ← Imports
        </Link>
      </div>
      <PageHeader title={j.filename} description={`${KIND_LABEL[j.kind]} · ${j.row_count ?? 0} rows`}>
        <ImportStatus status={j.status} />
      </PageHeader>
      {queued && j.status === "mapping_confirmed" ? <Alert className="mb-6">Import queued — waiting for a worker…</Alert> : null}
      {j.status === "succeeded" || j.status === "failed" || j.status === "importing" ? (
        <Results
          job={j}
          onDownload={() =>
            session &&
            void downloadFile(session.authorization, `/workspaces/${workspaceId}/imports/${jobId}/errors`, `${j.filename}-errors.csv`)
          }
          onRemap={() => {
            setQueued(true);
            job.reload();
          }}
          editable={j.status === "failed"}
          schema={schema.data}
          region={workspace.default_phone_region}
          workspaceId={workspaceId}
        />
      ) : (
        <MappingEditor
          job={j}
          schema={schema.data}
          region={workspace.default_phone_region}
          workspaceId={workspaceId}
          onDone={() => {
            setQueued(true);
            job.reload();
          }}
        />
      )}
    </>
  );
}

function Results(props: {
  job: ImportJob;
  onDownload: () => void;
  onRemap: () => void;
  editable: boolean;
  schema: ImportSchema;
  region: string;
  workspaceId: string;
}) {
  const { job } = props;
  const stats = (job.stats ?? {}) as Record<string, number | string>;
  return (
    <div className="space-y-6">
      {job.status === "importing" ? <Alert>Importing… this page updates automatically.</Alert> : null}
      {job.status === "failed" && stats.error ? <Alert tone="danger">Import failed: {String(stats.error)}</Alert> : null}
      {job.status !== "importing" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(STAT_LABEL).map(([k, label]) =>
            stats[k] !== undefined ? (
              <Card key={k} className="p-4">
                <div className="text-2xl font-semibold tabular-nums">{String(stats[k])}</div>
                <div className="text-xs text-muted-foreground">{label}</div>
              </Card>
            ) : null,
          )}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {job.has_error_report ? (
          <Button variant="outline" onClick={props.onDownload}>
            Download rows that failed
          </Button>
        ) : null}
        {Number(stats.reviews_created ?? 0) > 0 ? (
          <Link className="inline-flex h-9 items-center rounded-md border border-border px-4 text-sm hover:bg-muted" href={`/w/${props.workspaceId}/reviews`}>
            Review possible duplicates
          </Link>
        ) : null}
      </div>
      {props.editable ? (
        <MappingEditor job={job} schema={props.schema} region={props.region} workspaceId={props.workspaceId} onDone={props.onRemap} />
      ) : null}
    </div>
  );
}

function MappingEditor(props: { job: ImportJob; schema: ImportSchema; region: string; workspaceId: string; onDone: () => void }) {
  const { job, schema, region, workspaceId } = props;
  const api = useApi();
  const path = { workspace_id: workspaceId, job_id: job.id };
  const initial = job.confirmed_mapping ?? job.proposed_mapping;
  const [choices, setChoices] = useState<ColumnChoice[]>(() => toColumnChoices(job.headers, initial));
  const [serverProblems, setServerProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const mapping = useMemo(() => toMapping(choices, initial?.warnings ?? []), [choices, initial?.warnings]);
  const problems = localProblems(choices, schema);

  const preview = useAsync(
    () => unwrap(api.POST("/workspaces/{workspace_id}/imports/{job_id}/preview", { params: { path }, body: mapping })),
    [api, JSON.stringify(mapping)],
  );

  async function confirmAndRun() {
    setBusy(true);
    setServerProblems([]);
    try {
      await unwrap(api.PUT("/workspaces/{workspace_id}/imports/{job_id}/mapping", { params: { path }, body: mapping }));
      await unwrap(api.POST("/workspaces/{workspace_id}/imports/{job_id}/run", { params: { path } }));
      props.onDone();
    } catch (err) {
      setServerProblems(err instanceof ApiError ? err.problems : [String(err)]);
    } finally {
      setBusy(false);
    }
  }

  const update = (i: number, next: ColumnChoice) => setChoices((prev) => prev.map((c, k) => (k === i ? next : c)));
  const previewRows = preview.data?.rows ?? [];
  const mappedTargets = mapping.fields.map((f) => f.target);

  return (
    <div className="space-y-6">
      {(initial?.warnings ?? []).map((w) => (
        <Alert key={w} tone="warning">
          {w}
        </Alert>
      ))}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Column in your file</th>
                <th className="px-4 py-2 font-medium">Sample values</th>
                <th className="px-4 py-2 font-medium">Maps to</th>
                <th className="px-4 py-2 font-medium">Read as</th>
                <th className="px-4 py-2 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {choices.map((c, i) => {
                const samples = job.sample_rows.map((r) => r[c.column]).filter(Boolean).slice(0, 3);
                const transforms = allowedTransforms(c.target, schema);
                return (
                  <tr key={c.column} className="border-t border-border align-top">
                    <td className="px-4 py-3 font-medium" dir="auto">
                      {c.column}
                    </td>
                    <td className="max-w-64 px-4 py-3 text-muted-foreground">
                      {samples.map((s, k) => (
                        <div key={k} className="truncate" dir="auto" title={s}>
                          {s}
                        </div>
                      ))}
                    </td>
                    <td className="px-4 py-3">
                      <Select
                        aria-label={`Target for ${c.column}`}
                        value={c.target.startsWith("attributes.") ? c.target : c.target}
                        onChange={(e) => update(i, retarget(c, e.target.value, schema, region))}
                      >
                        <option value={IGNORE}>— Don&apos;t import —</option>
                        {schema.targets.map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.label}
                          </option>
                        ))}
                        {c.target.startsWith("attributes.") ? (
                          <option value={c.target}>Keep as “{c.target.slice("attributes.".length)}”</option>
                        ) : (
                          <option value={KEEP_AS_ATTRIBUTE}>Keep as extra field</option>
                        )}
                      </Select>
                    </td>
                    <td className="px-4 py-3">
                      {c.target === IGNORE ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <Select
                          aria-label={`Transform for ${c.column}`}
                          value={c.transform}
                          onChange={(e) => update(i, { ...c, transform: e.target.value as ColumnChoice["transform"], origin: "user" })}
                        >
                          {transforms.map((t) => (
                            <option key={t} value={t}>
                              {TRANSFORM_LABEL[t] ?? t}
                            </option>
                          ))}
                        </Select>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {c.target !== IGNORE && c.confidence !== null ? (
                        <div className="space-y-1">
                          <Badge tone={confidenceTone(c.confidence)}>{Math.round(c.confidence * 100)}%</Badge>
                          <div className="text-xs text-muted-foreground">
                            {c.origin === "llm" ? "AI" : c.origin === "heuristic" ? "Matched header" : c.origin === "reused" ? "Reused" : "You"}
                          </div>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Preview (first rows after mapping)</h2>
        {preview.data?.problems.length ? (
          <Alert tone="warning" className="mb-3">
            {preview.data.problems.join(" · ")}
          </Alert>
        ) : null}
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-muted-foreground">
              <tr>
                {mappedTargets.map((t) => (
                  <th key={t} className="px-3 py-2 font-medium whitespace-nowrap">
                    {schema.targets.find((x) => x.name === t)?.label ?? t.replace("attributes.", "")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewRows.slice(0, 5).map((r, k) => (
                <tr key={k} className="border-t border-border">
                  {mappedTargets.map((t) => (
                    <td key={t} className="max-w-56 truncate px-3 py-2" dir="auto" title={r.errors[t] ?? r.values[t]}>
                      {r.errors[t] ? <span className="text-destructive">⚠ {r.errors[t]}</span> : (r.values[t] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {[...problems, ...serverProblems].length ? (
        <Alert tone="danger">
          <ul className="list-inside list-disc">
            {[...new Set([...problems, ...serverProblems])].map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
      <div className="flex items-center gap-3">
        <Button size="lg" disabled={busy || problems.length > 0} onClick={() => void confirmAndRun()}>
          {busy ? "Starting import…" : "Confirm mapping and import"}
        </Button>
        <span className="text-sm text-muted-foreground">Nothing is imported until you confirm.</span>
      </div>
    </div>
  );
}
