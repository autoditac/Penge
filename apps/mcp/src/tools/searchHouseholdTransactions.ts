import { z } from "zod/v3";

import { ToolDataError } from "../errors.js";
import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const ProviderSchema = z.enum(["gls", "ebank", "lunar", "nordnet", "pfa", "growney"]);

const InputSchema = z
  .object({
    source: ProviderSchema.optional(),
    query: z.string().min(2).max(120).optional(),
    account_ids: z.array(z.string().regex(UUID)).max(20).optional(),
    date_range: z
      .object({ from: z.string().date(), to: z.string().date() })
      .strict()
      .refine((range) => range.from <= range.to, {
        message: "date_range.from must be on or before date_range.to",
        path: ["from"],
      })
      .refine(
        (range) =>
          (Date.parse(`${range.to}T00:00:00Z`) - Date.parse(`${range.from}T00:00:00Z`)) /
            86_400_000 <=
          366,
        { message: "date_range must contain at most 367 days" },
      ),
    limit: z.number().int().min(1).max(50).default(25),
    offset: z.number().int().min(0).max(5000).default(0),
  })
  .strict();

const TransactionItemSchema = z
  .object({
    stable_id: z.string().regex(UUID),
    source: ProviderSchema,
    account_id: z.string().regex(UUID),
    transaction_date: z.string().date(),
    description: z.string().max(240).nullable(),
    counterparty: z.string().max(240).nullable(),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    classification: z
      .object({
        treatment: z.string().max(30),
        review_state: z.enum(["classified", "needs_review", "unclassified"]),
        provenance: z.enum(["manual", "rule"]),
        revision: z.number().int().positive(),
        merchant_id: z.string().regex(UUID).nullable(),
        allocation_count: z.number().int().nonnegative(),
      })
      .strict()
      .nullable(),
    latest_audit: z
      .object({
        audit_id: z.string().regex(UUID),
        action: z.string().max(30),
        created_at: z.string().datetime(),
      })
      .strict()
      .nullable(),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    limit: z.number().int().min(1).max(50),
    offset: z.number().int().min(0).max(5000),
    total: z.number().int().nonnegative(),
    items: z.array(TransactionItemSchema).max(50),
  })
  .strict();

const RowSchema = z
  .object({
    stable_id: z.string().regex(UUID),
    source: ProviderSchema,
    account_id: z.string().regex(UUID),
    transaction_date: z.union([z.date(), z.string()]),
    description: z.string().nullable(),
    counterparty: z.string().nullable(),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    treatment: z.string().nullable(),
    review_state: z.enum(["classified", "needs_review", "unclassified"]).nullable(),
    provenance: z.enum(["manual", "rule"]).nullable(),
    revision: z.coerce.number().int().positive().nullable(),
    merchant_id: z.string().regex(UUID).nullable(),
    allocation_count: z.coerce.number().int().nonnegative(),
    audit_id: z.string().regex(UUID).nullable(),
    audit_action: z.string().nullable(),
    audit_created_at: z.union([z.date(), z.string()]).nullable(),
    total_count: z.coerce.number().int().nonnegative(),
  })
  .strict();

export type SearchHouseholdTransactionsInput = z.infer<typeof InputSchema>;
export type SearchHouseholdTransactionsOutput = z.infer<typeof OutputSchema>;

export interface HouseholdTransactionQueryRunner {
  query<R extends Record<string, unknown>>(
    sql: string,
    params: ReadonlyArray<unknown>,
  ): Promise<{ rows: R[] }>;
}

export interface SearchHouseholdTransactionsOptions {
  runner: HouseholdTransactionQueryRunner;
  now?: () => Date;
}

const SEARCH_SQL = `
  SELECT
    t.id::text AS stable_id,
    a.provider AS source,
    a.id::text AS account_id,
    (t.ts AT TIME ZONE 'UTC')::date AS transaction_date,
    left(t.description, 240) AS description,
    left(t.counterparty, 240) AS counterparty,
    t.amount::text AS amount,
    a.currency,
    c.treatment,
    c.review_state,
    c.provenance,
    c.revision,
    c.merchant_id::text AS merchant_id,
    (SELECT count(*)::int FROM household_allocation x WHERE x.transaction_id = t.id)
      AS allocation_count,
    audit.id::text AS audit_id,
    audit.action AS audit_action,
    audit.created_at AS audit_created_at,
    count(*) OVER()::int AS total_count
  FROM transaction AS t
  INNER JOIN account AS a ON a.id = t.account_id
  LEFT JOIN household_classification AS c ON c.transaction_id = t.id
  LEFT JOIN household_merchant AS m ON m.id = c.merchant_id
  LEFT JOIN LATERAL (
    SELECT h.id, h.action, h.created_at
    FROM household_audit AS h
    WHERE h.subject_id = t.id
    ORDER BY h.created_at DESC, h.id DESC
    LIMIT 1
  ) AS audit ON true
  WHERE a.provider = ANY($1::text[])
    AND ($2::text IS NULL OR a.provider = $2)
    AND (t.ts AT TIME ZONE 'UTC')::date BETWEEN $3::date AND $4::date
    AND ($5::uuid[] IS NULL OR a.id = ANY($5::uuid[]))
    AND (
      $6::text IS NULL
      OR position(lower($6) in lower(concat_ws(' ', t.description, t.counterparty, m.name))) > 0
    )
  ORDER BY t.ts DESC, t.id DESC
  LIMIT $7 OFFSET $8
`;

function timestamp(value: Date | string | null): string | null {
  if (value === null) return null;
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("transaction query returned an invalid timestamp");
  }
  return parsed.toISOString();
}

export function searchHouseholdTransactionsTool(
  opts: SearchHouseholdTransactionsOptions,
): ToolDefinition<SearchHouseholdTransactionsInput, SearchHouseholdTransactionsOutput> {
  return {
    name: "search_household_transactions",
    description:
      "Search a bounded date window of household transactions and return stable IDs, current classification state, and audit references; never raw source payloads.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const providers = ProviderSchema.options;
      const result = await opts.runner.query(SEARCH_SQL, [
        providers,
        args.source ?? null,
        args.date_range.from,
        args.date_range.to,
        args.account_ids ?? null,
        args.query?.toLocaleLowerCase("en") ?? null,
        args.limit,
        args.offset,
      ]);
      const rows = result.rows.map((raw) => RowSchema.parse(raw));
      return {
        generated_at: (opts.now?.() ?? new Date()).toISOString(),
        limit: args.limit,
        offset: args.offset,
        total: rows[0]?.total_count ?? 0,
        items: rows.map((row) => ({
          stable_id: row.stable_id,
          source: row.source,
          account_id: row.account_id,
          transaction_date:
            row.transaction_date instanceof Date
              ? row.transaction_date.toISOString().slice(0, 10)
              : row.transaction_date.slice(0, 10),
          description: row.description,
          counterparty: row.counterparty,
          amount: row.amount,
          currency: row.currency,
          classification:
            row.treatment === null ||
            row.review_state === null ||
            row.provenance === null ||
            row.revision === null
              ? null
              : {
                  treatment: row.treatment,
                  review_state: row.review_state,
                  provenance: row.provenance,
                  revision: row.revision,
                  merchant_id: row.merchant_id,
                  allocation_count: row.allocation_count,
                },
          latest_audit:
            row.audit_id === null || row.audit_action === null || row.audit_created_at === null
              ? null
              : {
                  audit_id: row.audit_id,
                  action: row.audit_action,
                  created_at: timestamp(row.audit_created_at)!,
                },
        })),
      };
    },
  };
}
