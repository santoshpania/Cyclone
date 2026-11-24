import { Badge } from "@/components/ui/primitives";

const IMPORT_STATUS: Record<string, { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info" }> = {
  uploaded: { label: "Uploaded", tone: "neutral" },
  mapping_proposed: { label: "Review mapping", tone: "warning" },
  mapping_confirmed: { label: "Ready to import", tone: "info" },
  importing: { label: "Importing…", tone: "info" },
  succeeded: { label: "Imported", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

export function ImportStatus({ status }: { status: string }) {
  const s = IMPORT_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

const ACCOUNT_STATUS: Record<string, { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info" }> = {
  customer: { label: "Customer", tone: "success" },
  lapsed_customer: { label: "Lapsed", tone: "warning" },
  prospect: { label: "Prospect", tone: "info" },
  disqualified: { label: "Disqualified", tone: "neutral" },
  merged: { label: "Merged", tone: "neutral" },
};

export function AccountStatus({ status }: { status: string }) {
  const s = ACCOUNT_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export const KIND_LABEL: Record<string, string> = {
  accounts: "Customer list",
  orders: "Orders / invoices",
  registry: "Licence registry",
};
