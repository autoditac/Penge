import { z } from "zod/v3";
import { caseFold } from "unicode-case-folding";

import { ToolDataError } from "../errors.js";
import { redactTextBounded } from "../redact.js";
import type { ToolDefinition } from "../registry.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const InputSchema = z
  .object({
    query: z
      .string()
      .min(2)
      .max(100)
      .refine((value) => /[\p{L}\p{N}]/u.test(normalizeAlias(value)), {
        message: "query must contain at least one Unicode letter or number after normalization",
      }),
    category_prefix: z
      .string()
      .min(1)
      .max(100)
      .refine((value) => /[\p{L}\p{N}]/u.test(normalizeAlias(value)), {
        message:
          "category_prefix must contain at least one Unicode letter or number after normalization",
      })
      .optional(),
    limit: z.number().int().min(1).max(20).default(10),
    offset: z.number().int().min(0).max(1000).default(0),
  })
  .strict();

const ResultSchema = z
  .object({
    reference_id: z.string().regex(UUID),
    source_entity_id: z.string().max(200),
    label: z.string().max(256),
    aliases: z.array(z.string().max(256)).max(10),
    category_path: z.string().max(200),
    wikidata_id: z.string().max(16).nullable(),
    source_version: z.string().max(200),
    source_revision_at: z.string().datetime(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    query: z.string().min(2).max(100),
    total: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(20),
    offset: z.number().int().min(0).max(1000),
    results: z.array(ResultSchema).max(20),
  })
  .strict();

const RowSchema = ResultSchema.omit({
  label: true,
  aliases: true,
  source_revision_at: true,
}).extend({
  label: z.string(),
  aliases: z.array(z.string()),
  source_revision_at: z.union([z.date(), z.string()]),
  total_count: z.coerce.number().int().nonnegative(),
});

export type SearchMerchantReferenceInput = z.infer<typeof InputSchema>;
export type SearchMerchantReferenceOutput = z.infer<typeof OutputSchema>;

export interface SearchMerchantReferenceOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const SEARCH_SQL = `
  SELECT r.id::text AS reference_id, r.source_entity_id, r.label,
    coalesce((
      SELECT array_agg(a.alias ORDER BY a.alias)
      FROM (
        SELECT alias FROM merchant_reference_alias
        WHERE reference_id = r.id
        ORDER BY normalized_alias
        LIMIT 10
      ) AS a
    ), ARRAY[]::varchar[]) AS aliases,
    r.category_path, r.wikidata_id, r.source_version, r.source_revision_at,
    count(*) OVER()::int AS total_count
  FROM merchant_reference AS r
  INNER JOIN merchant_reference_generation AS generation ON generation.id = r.generation_id
  WHERE generation.status = 'active'
    AND generation.source_id = 'name-suggestion-index'
    AND ($2::text IS NULL OR position(lower($2) in lower(r.category_path)) = 1)
    AND (
      position(lower($1) in lower(r.label)) > 0
      OR EXISTS (
        SELECT 1 FROM merchant_reference_alias AS match_alias
        WHERE match_alias.reference_id = r.id
          AND position(lower($1) in match_alias.normalized_alias) > 0
      )
    )
  ORDER BY
    CASE WHEN lower(r.label) = lower($1) THEN 0
         WHEN position(lower($1) in lower(r.label)) = 1 THEN 1
         ELSE 2 END,
    r.label,
    r.id
  LIMIT $3 OFFSET $4
`;

const SEARCH_COUNT_SQL = `
  SELECT count(*)::int AS total_count
  FROM merchant_reference AS r
  INNER JOIN merchant_reference_generation AS generation ON generation.id = r.generation_id
  WHERE generation.status = 'active'
    AND generation.source_id = 'name-suggestion-index'
    AND ($2::text IS NULL OR position(lower($2) in lower(r.category_path)) = 1)
    AND (
      position(lower($1) in lower(r.label)) > 0
      OR EXISTS (
        SELECT 1 FROM merchant_reference_alias AS match_alias
        WHERE match_alias.reference_id = r.id
          AND position($1 in match_alias.normalized_alias) > 0
      )
    )
`;

function normalizeAlias(value: string): string {
  return caseFold(value.normalize("NFKC")).trim().replace(/\s+/g, " ");
}

function instant(value: Date | string): string {
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("merchant reference query returned an invalid timestamp");
  }
  return parsed.toISOString();
}

export function searchMerchantReferenceTool(
  opts: SearchMerchantReferenceOptions,
): ToolDefinition<SearchMerchantReferenceInput, SearchMerchantReferenceOutput> {
  return {
    name: "search_merchant_reference",
    description:
      "Search the active local NSI merchant-reference generation by label or alias with bounded output and no network access.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const filterParams = [
        normalizeAlias(args.query),
        args.category_prefix === undefined ? null : normalizeAlias(args.category_prefix),
      ] as const;
      const countResult = await opts.runner.query(SEARCH_COUNT_SQL, filterParams);
      const total = z.coerce
        .number()
        .int()
        .nonnegative()
        .parse(countResult.rows[0]?.total_count ?? 0);
      const result = await opts.runner.query(SEARCH_SQL, [
        ...filterParams,
        args.limit,
        args.offset,
      ]);
      const rows = result.rows.map((raw) => RowSchema.parse(raw));
      return {
        generated_at: (opts.now?.() ?? new Date()).toISOString(),
        query: redactTextBounded(args.query, 100),
        total,
        limit: args.limit,
        offset: args.offset,
        results: rows.map(({ total_count: _total, source_revision_at, ...row }) => ({
          ...row,
          label: redactTextBounded(row.label, 256),
          aliases: row.aliases.slice(0, 10).map((alias) => redactTextBounded(alias, 256)),
          source_revision_at: instant(source_revision_at),
        })),
      };
    },
  };
}
