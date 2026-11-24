"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Alert, Card, Input, Label, PageHeader, Select, Textarea } from "@/components/ui/primitives";
import { unwrap, useApi } from "@/lib/api/client";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "Arabic" },
  { code: "hi", label: "Hindi" },
  { code: "ur", label: "Urdu" },
  { code: "fr", label: "French" },
];

export default function NewWorkspacePage() {
  const api = useApi();
  const router = useRouter();
  const [companyName, setCompanyName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [offerings, setOfferings] = useState("");
  const [valueProp, setValueProp] = useState("");
  const [languages, setLanguages] = useState<string[]>(["en", "ar"]);
  const [currency, setCurrency] = useState("AED");
  const [region, setRegion] = useState("AE");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const ws = await unwrap(
        api.POST("/workspaces", {
          body: {
            name: workspaceName.trim() || companyName.trim(),
            company_profile: {
              company_name: companyName.trim(),
              offerings: offerings.split("\n").map((s) => s.trim()).filter(Boolean),
              value_proposition: valueProp.trim(),
            },
            languages,
            home_currency: currency,
            default_phone_region: region,
          },
        }),
      );
      router.replace(`/w/${ws.id}/imports`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New workspace" description="Step 1 of 2 — tell Cyclone what you sell. You'll describe your ideal customer next." />
      <Card className="max-w-2xl">
        <form className="space-y-5" onSubmit={(e) => void submit(e)}>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="company">Company name</Label>
              <Input id="company" required dir="auto" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="wsname">Workspace name (optional)</Label>
              <Input id="wsname" dir="auto" placeholder="e.g. Dubai field sales" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="offerings">Products or services you sell (one per line)</Label>
            <Textarea id="offerings" dir="auto" rows={4} value={offerings} onChange={(e) => setOfferings(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vp">Value proposition</Label>
            <Textarea
              id="vp"
              dir="auto"
              rows={3}
              placeholder="Why do customers buy from you instead of someone else?"
              value={valueProp}
              onChange={(e) => setValueProp(e.target.value)}
            />
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Languages for pitches and the UI</legend>
            <div className="flex flex-wrap gap-4">
              {LANGUAGES.map((l) => (
                <label key={l.code} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={languages.includes(l.code)}
                    onChange={(e) =>
                      setLanguages((prev) => (e.target.checked ? [...prev, l.code] : prev.filter((x) => x !== l.code)))
                    }
                  />
                  {l.label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="currency">Currency</Label>
              <Select id="currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {["AED", "SAR", "QAR", "KWD", "OMR", "BHD", "INR", "USD", "EUR", "GBP"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="region">Default phone country</Label>
              <Select id="region" value={region} onChange={(e) => setRegion(e.target.value)}>
                {[["AE", "United Arab Emirates"], ["SA", "Saudi Arabia"], ["QA", "Qatar"], ["KW", "Kuwait"], ["OM", "Oman"],
                  ["BH", "Bahrain"], ["IN", "India"], ["GB", "United Kingdom"], ["US", "United States"]].map(([c, n]) => (
                  <option key={c} value={c}>
                    {n}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Button type="submit" disabled={busy || languages.length === 0}>
            {busy ? "Creating…" : "Create workspace"}
          </Button>
        </form>
      </Card>
    </>
  );
}
