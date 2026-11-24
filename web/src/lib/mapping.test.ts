import { describe, expect, it } from "vitest";

import type { ImportSchema } from "@/lib/api/client";

import { IGNORE, KEEP_AS_ATTRIBUTE, localProblems, retarget, toColumnChoices, toMapping } from "./mapping";

const schema: ImportSchema = {
  kind: "accounts",
  attribute_prefix: "attributes.",
  required_groups: [["display_name", "display_name_ar"]],
  targets: [
    { name: "display_name", label: "Business name", value_type: "text", default_transform: "trim", allowed_transforms: ["trim"], multi_column: false },
    { name: "display_name_ar", label: "Business name (Arabic)", value_type: "text", default_transform: "trim", allowed_transforms: ["trim"], multi_column: false },
    { name: "address", label: "Address", value_type: "text", default_transform: "concat", allowed_transforms: ["concat", "trim"], multi_column: true },
    { name: "phone", label: "Phone", value_type: "phone", default_transform: "phone_e164", allowed_transforms: ["phone_e164"], multi_column: true },
  ],
};

describe("mapping conversions", () => {
  const headers = ["Name", "Addr 1", "Addr 2", "Mobile", "TRN"];
  const mapping = {
    fields: [
      { target: "display_name", source_columns: ["Name"], transform: "trim" as const, params: {}, confidence: 0.95, origin: "heuristic" as const },
      { target: "address", source_columns: ["Addr 1", "Addr 2"], transform: "concat" as const, params: {}, confidence: 0.8, origin: "heuristic" as const },
    ],
    unmapped: ["Mobile", "TRN"],
    warnings: [],
  };

  it("round-trips per-target ⇄ per-column", () => {
    const choices = toColumnChoices(headers, mapping);
    expect(choices.map((c) => c.target)).toEqual(["display_name", "address", "address", IGNORE, IGNORE]);
    const back = toMapping(choices);
    expect(back.fields).toHaveLength(2);
    expect(back.fields[1]?.source_columns).toEqual(["Addr 1", "Addr 2"]);
    expect(back.unmapped).toEqual(["Mobile", "TRN"]);
  });

  it("retargeting sets the default transform and region for phones", () => {
    const [, , , mobile] = toColumnChoices(headers, mapping);
    const next = retarget(mobile!, "phone", schema, "AE");
    expect(next).toMatchObject({ target: "phone", transform: "phone_e164", params: { default_region: "AE" }, origin: "user" });
  });

  it("keep-as-attribute derives a snake_case key", () => {
    const trn = toColumnChoices(headers, mapping)[4]!;
    expect(retarget(trn, KEEP_AS_ATTRIBUTE, schema, "AE").target).toBe("attributes.trn");
  });

  it("flags duplicate single-column targets and missing required fields", () => {
    const choices = toColumnChoices(headers, mapping).map((c) => (c.column === "TRN" ? { ...c, target: "display_name" } : c));
    expect(localProblems(choices, schema)).toEqual(['"Business name" can only come from one column']);
    const none = toColumnChoices(headers, { fields: [], unmapped: headers, warnings: [] });
    expect(localProblems(none, schema)).toEqual(["Map a column to Business name or Business name (Arabic)"]);
  });
});
