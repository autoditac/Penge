import { z } from "zod/v3";

import { redactTextBounded } from "../redact.js";
import type { ToolDefinition } from "../registry.js";
import type { HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const IdentityKindSchema = z.enum(["stable", "processor", "marketplace", "mixed", "unknown"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const InputSchema = z
  .object({
    query: z.string().min(2).max(120).optional(),
    include_archived: z.boolean().default(false),
    limit: z.number().int().min(1).max(50).default(25),
    offset: z.number().int().min(0).max(5000).default(0),
  })
  .strict();

const MerchantSchema = z
  .object({
    merchant_id: z.string().regex(UUID),
    name: z.string().max(200),
    identity_kind: IdentityKindSchema,
    confirmed: z.boolean(),
    archived: z.boolean(),
    revision: z.number().int().positive(),
    rule_version: z.number().int().nonnegative(),
    alias_count: z.number().int().nonnegative(),
    active_rule_count: z.number().int().nonnegative(),
    classified_transaction_count: z.number().int().nonnegative(),
    reference: z
      .object({
        source: z.string().max(200),
        key: z.string().max(200),
        version: z.string().max(200),
      })
      .strict()
      .nullable(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    total: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(50),
    offset: z.number().int().min(0).max(5000),
    merchants: z.array(MerchantSchema).max(50),
  })
  .strict();

const RowSchema = z
  .object({
    merchant_id: z.string().regex(UUID),
    name: z.string(),
    identity_kind: IdentityKindSchema,
    confirmed: z.boolean(),
    archived: z.boolean(),
    revision: z.coerce.number().int().positive(),
    rule_version: z.coerce.number().int().nonnegative(),
    alias_count: z.coerce.number().int().nonnegative(),
    active_rule_count: z.coerce.number().int().nonnegative(),
    classified_transaction_count: z.coerce.number().int().nonnegative(),
    reference_source: z.string().nullable(),
    reference_key: z.string().nullable(),
    reference_version: z.string().nullable(),
    total_count: z.coerce.number().int().nonnegative(),
  })
  .strict();

export type GetHouseholdMerchantSummaryInput = z.infer<typeof InputSchema>;
export type GetHouseholdMerchantSummaryOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdMerchantSummaryOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const MERCHANT_SQL = `
  SELECT m.id::text AS merchant_id, left(m.name, 200) AS name, m.identity_kind,
    m.confirmed, m.archived, m.revision, m.rule_version,
    (SELECT count(*)::int FROM household_merchant_alias a WHERE a.merchant_id = m.id)
      AS alias_count,
    (SELECT count(*)::int FROM household_rule r
      WHERE r.merchant_id = m.id AND r.version = m.rule_version
        AND r.state = 'active') AS active_rule_count,
    (SELECT count(*)::int FROM household_classification c
      WHERE c.merchant_id = m.id) AS classified_transaction_count,
    m.reference_source, m.reference_key, m.reference_version,
    count(*) OVER()::int AS total_count
  FROM household_merchant AS m
  WHERE ($1::boolean OR NOT m.archived)
    AND ($2::text IS NULL OR position(lower($2) in lower(m.name)) > 0)
  ORDER BY m.name, m.id
  LIMIT $3 OFFSET $4
`;

const MERCHANT_COUNT_SQL = `
  SELECT count(*)::int AS total_count
  FROM household_merchant AS m
  WHERE ($1::boolean OR NOT m.archived)
    AND ($2::text IS NULL OR position(lower($2) in lower(m.name)) > 0)
`;

export function getHouseholdMerchantSummaryTool(
  opts: GetHouseholdMerchantSummaryOptions,
): ToolDefinition<GetHouseholdMerchantSummaryInput, GetHouseholdMerchantSummaryOutput> {
  return {
    name: "get_household_merchant_summary",
    description:
      "Return bounded household merchant identity, alias, rule, and classification counts without source payloads.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const filterParams = [
        args.include_archived,
        args.query?.toLocaleLowerCase("en") ?? null,
      ] as const;
      const countResult = await opts.runner.query(MERCHANT_COUNT_SQL, filterParams);
      const total = z.coerce
        .number()
        .int()
        .nonnegative()
        .parse(countResult.rows[0]?.total_count ?? 0);
      const result = await opts.runner.query(MERCHANT_SQL, [
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
        merchants: rows.map(
          ({
            total_count: _total,
            reference_source,
            reference_key,
            reference_version,
            ...row
          }) => ({
            ...row,
            name: redactTextBounded(row.name, 200),
            reference:
              reference_source === null || reference_key === null || reference_version === null
                ? null
                : {
                    source: reference_source,
                    key: reference_key,
                    version: reference_version,
                  },
          }),
        ),
      };
    },
  };
}
