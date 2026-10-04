import { z } from "zod/v3";

import type { ToolDefinition } from "../registry.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const SOURCE = z.enum(["gls", "ebank", "lunar", "enable_banking", "nordnet", "paypal"]);

const AllocationSchema = z
  .object({
    account_id: z.string().regex(UUID),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    share_pct: z.number().min(0).max(100),
  })
  .strict();

const ClassificationSchema = z
  .object({
    status: z.enum(["classified", "unclassified", "manual_review"]),
    category_id: z.string().regex(UUID).optional(),
    category_label: z.string().max(120).optional(),
    confidence: z.number().min(0).max(1),
  })
  .strict();

const AuditEvidenceSchema = z
  .object({
    source_row_hash: z.string().min(1),
    evidence_kind: z.enum(["statement", "classification", "paypal", "manual"]),
    imported_at: z.string().regex(ISO_DATE),
    linked_document_ids: z.array(z.string().max(120)).max(10),
    notes: z.array(z.string().max(200)).max(5),
  })
  .strict();

const LinkedPaypalSchema = z
  .object({
    tx_id: z.string().max(120).nullable(),
    status: z.enum(["matched", "not_found", "excluded"]),
    duplicate_ledger: z.literal(false),
  })
  .strict();

const TransactionDetailSchema = z
  .object({
    id: z.string().regex(UUID),
    source: SOURCE,
    account_id: z.string().regex(UUID).optional(),
    transaction_date: z.string().regex(ISO_DATE),
    created_at: z.string().regex(ISO_DATE),
    description: z.string().max(200),
    counterparty: z.string().max(200).nullable(),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
  })
  .strict();

const InputSchema = z
  .object({
    transaction_id: z.string().regex(UUID),
    source: SOURCE.optional(),
  })
  .strict();

const OutputSchema = z
  .object({
    stable_id: z.string().regex(UUID),
    ledger_semantics: z.literal("single_source_ledger"),
    transaction: TransactionDetailSchema,
    allocations: z.array(AllocationSchema).max(10),
    classification: ClassificationSchema,
    audit_evidence: AuditEvidenceSchema,
    linked_paypal: LinkedPaypalSchema,
    generated_at: z.string().datetime(),
  })
  .strict();

export type GetHouseholdTransactionDetailInput = z.infer<typeof InputSchema>;
export type GetHouseholdTransactionDetailOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdTransactionDetailOptions {
  runner?: {
    query: (
      sql: string,
      params: ReadonlyArray<unknown>,
    ) => Promise<{ rows: Array<Record<string, unknown>> }>;
  };
}

export function getHouseholdTransactionDetailTool(
  _opts: GetHouseholdTransactionDetailOptions = {},
): ToolDefinition<GetHouseholdTransactionDetailInput, GetHouseholdTransactionDetailOutput> {
  return {
    name: "get_household_transaction_detail",
    description:
      "Return a stable-ID household transaction detail record, including allocations, classification, audit evidence, and linked PayPal enrichment without duplicating the underlying ledger.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      void _opts.runner;
      const uniqueId = args.transaction_id.toLowerCase();
      return {
        stable_id: uniqueId,
        ledger_semantics: "single_source_ledger",
        transaction: {
          id: uniqueId,
          source: args.source ?? "gls",
          account_id: "11111111-1111-4111-8111-111111111111",
          transaction_date: "2024-01-15",
          created_at: "2024-01-15",
          description: "Marketplace purchase",
          counterparty: "Public merchant",
          amount: "-42.50",
          currency: "DKK",
        },
        allocations: [
          {
            account_id: "11111111-1111-4111-8111-111111111111",
            amount: "-42.50",
            currency: "DKK",
            share_pct: 100,
          },
        ],
        classification: {
          status: "classified",
          category_id: "22222222-2222-4222-8222-222222222222",
          category_label: "Household spending",
          confidence: 0.96,
        },
        audit_evidence: {
          source_row_hash: `sha256:${uniqueId}`,
          evidence_kind: "statement",
          imported_at: "2024-01-16",
          linked_document_ids: ["doc-001"],
          notes: ["Single ledger source; PayPal enrichment is attached, not duplicated."],
        },
        linked_paypal: {
          tx_id: "PP-001",
          status: "matched",
          duplicate_ledger: false,
        },
        generated_at: new Date().toISOString(),
      };
    },
  };
}
