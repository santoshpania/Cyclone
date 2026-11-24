/**
 * The API stores mappings per *target* (one target ← one or more columns). The review screen
 * edits per *column*. These pure helpers convert between the two.
 */
import type { ColumnMapping, FieldMapping, ImportSchema } from "@/lib/api/client";

export const IGNORE = "__ignore__";
export const KEEP_AS_ATTRIBUTE = "__attribute__";

export type ColumnChoice = {
  column: string;
  target: string; // a target name, "attributes.<key>", or IGNORE
  transform: FieldMapping["transform"];
  params: Record<string, unknown>;
  confidence: number | null;
  origin: FieldMapping["origin"] | null;
  reason: string | null;
};

type Target = ImportSchema["targets"][number];

export function attributeKey(header: string): string {
  let key = header.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48) || "column";
  if (!/^[a-z]/.test(key)) key = `col_${key}`.slice(0, 48);
  return `attributes.${key}`;
}

export function toColumnChoices(headers: string[], mapping: ColumnMapping | null | undefined): ColumnChoice[] {
  const byColumn = new Map<string, FieldMapping>();
  for (const f of mapping?.fields ?? []) for (const c of f.source_columns) byColumn.set(c, f);
  return headers.map((column) => {
    const f = byColumn.get(column);
    return f
      ? {
          column,
          target: f.target,
          transform: f.transform,
          params: (f.params ?? {}) as Record<string, unknown>,
          confidence: f.confidence ?? null,
          origin: f.origin ?? null,
          reason: f.reason ?? null,
        }
      : { column, target: IGNORE, transform: "trim", params: {}, confidence: null, origin: null, reason: null };
  });
}

/** Columns that share a multi-column target are combined in file order. */
export function toMapping(choices: ColumnChoice[], warnings: string[] = []): ColumnMapping {
  const fields = new Map<string, FieldMapping>();
  const unmapped: string[] = [];
  for (const c of choices) {
    if (c.target === IGNORE) {
      unmapped.push(c.column);
      continue;
    }
    const existing = fields.get(c.target);
    if (existing) {
      existing.source_columns.push(c.column);
      existing.confidence = Math.min(existing.confidence ?? 1, c.confidence ?? 1);
      if (existing.origin !== c.origin) existing.origin = "user";
      continue;
    }
    fields.set(c.target, {
      target: c.target,
      source_columns: [c.column],
      transform: c.transform,
      params: c.params,
      confidence: c.confidence ?? 1,
      origin: c.origin ?? "user",
      reason: c.reason,
    });
  }
  return { fields: [...fields.values()], unmapped, warnings };
}

/** Choosing a new target resets the transform to that target's default. */
export function retarget(choice: ColumnChoice, target: string, schema: ImportSchema, defaultRegion: string): ColumnChoice {
  if (target === IGNORE) return { ...choice, target, origin: "user", confidence: 1 };
  if (target === KEEP_AS_ATTRIBUTE) target = attributeKey(choice.column);
  const t = schema.targets.find((x) => x.name === target);
  const transform = (t?.default_transform ?? "trim") as FieldMapping["transform"];
  const params: Record<string, unknown> = transform === "phone_e164" ? { default_region: defaultRegion } : {};
  return { ...choice, target, transform, params, origin: "user", confidence: 1, reason: null };
}

export function allowedTransforms(target: string, schema: ImportSchema): string[] {
  const t: Target | undefined = schema.targets.find((x) => x.name === target);
  if (t) return t.allowed_transforms;
  if (target.startsWith("attributes.")) return ["trim", "concat", "coalesce", "lowercase"];
  return [];
}

/** Problems the UI can catch before asking the server. */
export function localProblems(choices: ColumnChoice[], schema: ImportSchema): string[] {
  const problems: string[] = [];
  const counts = new Map<string, number>();
  for (const c of choices) if (c.target !== IGNORE) counts.set(c.target, (counts.get(c.target) ?? 0) + 1);
  for (const [target, n] of counts) {
    const t = schema.targets.find((x) => x.name === target);
    if (n > 1 && t && !t.multi_column) problems.push(`"${t.label}" can only come from one column`);
  }
  for (const group of schema.required_groups) {
    if (!group.some((g) => counts.has(g))) {
      const labels = group.map((g) => schema.targets.find((t) => t.name === g)?.label ?? g);
      problems.push(`Map a column to ${labels.join(" or ")}`);
    }
  }
  return problems;
}
