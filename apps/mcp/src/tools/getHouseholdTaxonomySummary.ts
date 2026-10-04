import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const InputSchema = z
  .object({
    parent_id: z.string().regex(UUID).nullable().optional(),
    include_archived: z.boolean().default(false),
    limit: z.number().int().min(1).max(50).default(25),
    offset: z.number().int().min(0).max(5000).default(0),
  })
  .strict();

const EntrySchema = z
  .object({
    category_id: z.string().regex(UUID),
    name: z.string().max(200),
    kind: z.enum(["expense", "income"]),
    parent_id: z.string().regex(UUID).nullable(),
    sort_order: z.number().int().nonnegative(),
    archived: z.boolean(),
    revision: z.number().int().positive(),
    allocation_count: z.number().int().nonnegative(),
    classified_transaction_count: z.number().int().nonnegative(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    total: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(50),
    offset: z.number().int().min(0).max(5000),
    entries: z.array(EntrySchema).max(50),
  })
  .strict();

const RowSchema = EntrySchema.extend({
  total_count: z.coerce.number().int().nonnegative(),
  allocation_count: z.coerce.number().int().nonnegative(),
  classified_transaction_count: z.coerce.number().int().nonnegative(),
  sort_order: z.coerce.number().int().nonnegative(),
  revision: z.coerce.number().int().positive(),
});

export type GetHouseholdTaxonomySummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdTaxonomySummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdTaxonomySummaryOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const TAXONOMY_SQL = `
  SELECT c.id::text AS category_id, c.name, c.kind, c.parent_id::text AS parent_id,
    c.sort_order, c.archived, c.revision,
    (SELECT count(*)::int FROM household_allocation a WHERE a.category_id = c.id)
      AS allocation_count,
    (SELECT count(DISTINCT a.transaction_id)::int
      FROM household_allocation a WHERE a.category_id = c.id)
      AS classified_transaction_count,
    count(*) OVER()::int AS total_count
  FROM household_category AS c
  WHERE ($1::uuid IS NULL OR c.parent_id = $1::uuid)
    AND ($2::boolean OR NOT c.archived)
  ORDER BY c.sort_order, c.name, c.id
  LIMIT $3 OFFSET $4
`;

const TAXONOMY_COUNT_SQL = `
  SELECT count(*)::int AS total_count
  FROM household_category AS c
  WHERE ($1::uuid IS NULL OR c.parent_id = $1::uuid)
    AND ($2::boolean OR NOT c.archived)
`;

export function getHouseholdTaxonomySummaryTool(
  opts: GetHouseholdTaxonomySummaryOptions,
): ToolDefinition<GetHouseholdTaxonomySummaryInput, GetHouseholdTaxonomySummaryOutput> {
  return {
    name: "get_household_taxonomy_summary",
    description:
      "Return a bounded household category summary with stable IDs and usage counts; never source transactions or provider payloads.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const filterParams = [args.parent_id ?? null, args.include_archived] as const;
      const countResult = await opts.runner.query(TAXONOMY_COUNT_SQL, filterParams);
      const total = z.coerce
        .number()
        .int()
        .nonnegative()
        .parse(countResult.rows[0]?.total_count ?? 0);
      const result = await opts.runner.query(TAXONOMY_SQL, [
        ...filterParams,
        args.limit,
        args.offset,
      ]);
      const rows = result.rows.map((raw) => RowSchema.parse(raw));
      return {
        generated_at: (opts.now?.() ?? new Date()).toISOString(),
        total,
        limit: args.limit,
        offset: args.offset,
        entries: rows.map(({ total_count: _total, ...row }) => row),
      };
    },
  };
}
