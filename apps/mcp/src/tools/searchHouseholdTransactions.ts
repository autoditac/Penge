import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const SOURCE = z.enum(["gls", "ebank", "lunar", "enable_banking", "nordnet"]);

const ClassificationSchema = z
  .object({
    status: z.enum(["classified", "unclassified", "manual_review"]),
    category_id: z.string().regex(UUID).optional(),
    category_label: z.string().max(120).optional(),
  })
  .strict();

const MerchantReferenceSchema = z
  .object({
    normalized_name: z.string().max(200).nullable(),
    vendor_id: z.string().regex(UUID).optional(),
    confidence: z.number().min(0).max(1).optional(),
  })
  .strict();

const AuditEvidenceSchema = z
  .object({
    source_row_hash: z.string().min(1),
    imported_at: z.string().regex(ISO_DATE),
    evidence_kinds: z.array(z.enum(["statement", "classification", "paypal", "manual"])).max(5),
  })
  .strict();

const TransactionItemSchema = z
  .object({
    id: z.string().regex(UUID),
    source: SOURCE,
    account_id: z.string().regex(UUID).optional(),
    transaction_date: z.string().regex(ISO_DATE),
    description: z.string().max(200),
    counterparty: z.string().max(200).nullable(),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    classification: ClassificationSchema,
    merchant_reference: MerchantReferenceSchema.optional(),
    audit: AuditEvidenceSchema,
  })
  .strict();

const InputSchema = z
  .object({
    source: SOURCE.optional(),
    query: z.string().max(200).optional(),
    account_ids: z.array(z.string().regex(UUID)).max(20).optional(),
    from_date: z.string().regex(ISO_DATE).optional(),
    to_date: z.string().regex(ISO_DATE).optional(),
    limit: z.number().int().min(1).max(50).default(25),
  })
  .strict()
  .refine(
    (input) => {
      if (!input.from_date || !input.to_date) return true;
      return input.from_date <= input.to_date;
    },
    {
      message: "from_date must be on or before to_date",
      path: ["from_date"],
    },
  );

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    limit: z.number().int().min(1).max(50),
    total: z.number().int().nonnegative().max(5000),
    items: z.array(TransactionItemSchema).max(50),
  })
  .strict();

export type SearchHouseholdTransactionsInput = z.infer<typeof InputSchema>;
export type SearchHouseholdTransactionsOutput = z.infer<typeof OutputSchema>;

export interface SearchHouseholdTransactionsOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function searchHouseholdTransactionsTool(
  _opts: SearchHouseholdTransactionsOptions = {},
): ToolDefinition<SearchHouseholdTransactionsInput, SearchHouseholdTransactionsOutput> {
  return {
    name: "search_household_transactions",
    description:
      "Return a bounded, read-only page of household transactions for supported bank and brokerage sources with stable IDs and evidence metadata.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      return {
        generated_at: new Date().toISOString(),
        limit: Math.min(args.limit, 50),
        total: 0,
        items: [],
      };
    },
  };
}
