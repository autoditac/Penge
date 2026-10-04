import { z } from "zod/v3";

import { ToolDataError } from "../errors.js";
import { redactText } from "../redact.js";
import type { ToolDefinition } from "../registry.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const StateSchema = z.enum(["active", "conflict", "disabled", "insufficient"]);

const InputSchema = z
  .object({
    state: StateSchema.optional(),
    merchant_id: z.string().regex(UUID).optional(),
    limit: z.number().int().min(1).max(50).default(25),
    offset: z.number().int().min(0).max(5000).default(0),
  })
  .strict();

const RuleSchema = z
  .object({
    rule_id: z.string().regex(UUID),
    merchant_id: z.string().regex(UUID),
    merchant_name: z.string().max(200),
    version: z.number().int().positive(),
    state: StateSchema,
    category_id: z.string().regex(UUID).nullable(),
    category_name: z.string().max(200).nullable(),
    treatment: z.string().max(30).nullable(),
    explanation: z.string().max(1000),
    created_at: z.string().datetime(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    total: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(50),
    offset: z.number().int().min(0).max(5000),
    rules: z.array(RuleSchema).max(50),
  })
  .strict();

const RowSchema = RuleSchema.omit({ created_at: true }).extend({
  version: z.coerce.number().int().positive(),
  created_at: z.union([z.date(), z.string()]),
  total_count: z.coerce.number().int().nonnegative(),
});

export type GetHouseholdRuleSummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdRuleSummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdRuleSummaryOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const RULE_SQL = `
  SELECT r.id::text AS rule_id, r.merchant_id::text AS merchant_id,
    left(m.name, 200) AS merchant_name, r.version, r.state,
    r.category_id::text AS category_id, left(c.name, 200) AS category_name,
    r.treatment, r.explanation, r.created_at, count(*) OVER()::int AS total_count
  FROM household_rule AS r
  INNER JOIN household_merchant AS m ON m.id = r.merchant_id
  LEFT JOIN household_category AS c ON c.id = r.category_id
  WHERE ($1::text IS NULL OR r.state = $1)
    AND ($2::uuid IS NULL OR r.merchant_id = $2)
  ORDER BY r.created_at DESC, r.id DESC
  LIMIT $3 OFFSET $4
`;

const RULE_COUNT_SQL = `
  SELECT count(*)::int AS total_count
  FROM household_rule AS r
  WHERE ($1::text IS NULL OR r.state = $1)
    AND ($2::uuid IS NULL OR r.merchant_id = $2)
`;

function instant(value: Date | string): string {
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("rule query returned an invalid timestamp");
  }
  return parsed.toISOString();
}

export function getHouseholdRuleSummaryTool(
  opts: GetHouseholdRuleSummaryOptions,
): ToolDefinition<GetHouseholdRuleSummaryInput, GetHouseholdRuleSummaryOutput> {
  return {
    name: "get_household_rule_summary",
    description:
      "Return bounded append-only household rule summaries without raw evidence payloads.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const filterParams = [args.state ?? null, args.merchant_id ?? null] as const;
      const countResult = await opts.runner.query(RULE_COUNT_SQL, filterParams);
      const total = z.coerce
        .number()
        .int()
        .nonnegative()
        .parse(countResult.rows[0]?.total_count ?? 0);
      const result = await opts.runner.query(RULE_SQL, [...filterParams, args.limit, args.offset]);
      const rows = result.rows.map((raw) => RowSchema.parse(raw));
      return {
        generated_at: (opts.now?.() ?? new Date()).toISOString(),
        total,
        limit: args.limit,
        offset: args.offset,
        rules: rows.map(({ total_count: _total, created_at, ...row }) => ({
          ...row,
          merchant_name: redactText(row.merchant_name),
          category_name: row.category_name === null ? null : redactText(row.category_name),
          explanation: redactText(row.explanation),
          created_at: instant(created_at),
        })),
      };
    },
  };
}
