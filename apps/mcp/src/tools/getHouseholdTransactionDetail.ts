import { z } from "zod/v3";

import { ToolDataError, ToolNotFoundError } from "../errors.js";
import { redactText } from "../redact.js";
import type { ToolDefinition } from "../registry.js";
import { type HouseholdTransactionQueryRunner } from "./searchHouseholdTransactions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DECIMAL = /^-?\d+(?:\.\d+)?$/;
const ProviderSchema = z.enum(["gls", "ebank", "lunar", "nordnet", "pfa", "growney"]);

const InputSchema = z
  .object({
    transaction_id: z.string().regex(UUID),
    source: ProviderSchema.optional(),
  })
  .strict();

const TransactionSchema = z
  .object({
    stable_id: z.string().regex(UUID),
    source: ProviderSchema,
    account_id: z.string().regex(UUID),
    booked_at: z.string().datetime(),
    value_date: z.string().date().nullable(),
    kind: z.string().max(100),
    amount: z.string().regex(DECIMAL),
    fee: z.string().regex(DECIMAL),
    tax: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    description: z.string().max(240).nullable(),
    counterparty: z.string().max(240).nullable(),
  })
  .strict();

const ClassificationSchema = z
  .object({
    treatment: z.string().max(30),
    review_state: z.enum(["classified", "needs_review", "unclassified"]),
    merchant_id: z.string().regex(UUID).nullable(),
    merchant_name: z.string().max(200).nullable(),
    identity_confirmed: z.boolean(),
    provenance: z.enum(["manual", "rule"]),
    rule_id: z.string().regex(UUID).nullable(),
    revision: z.number().int().positive(),
    explanation: z.string().max(1000),
  })
  .strict();

const AllocationSchema = z
  .object({
    category_id: z.string().regex(UUID),
    category_name: z.string().max(200),
    category_kind: z.enum(["expense", "income"]),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
  })
  .strict();

const AuditEvidenceSchema = z
  .object({
    audit_id: z.string().regex(UUID),
    subject_type: z.string().max(30),
    action: z.string().max(30),
    created_at: z.string().datetime(),
  })
  .strict();

const PaypalDetailSchema = z
  .object({
    detail_id: z.string().regex(UUID),
    occurred_at: z.string().datetime(),
    amount: z.string().regex(DECIMAL),
    currency: z.string().length(3),
    merchant_name: z.string().max(240).nullable(),
    reference: z.string().max(240).nullable(),
    event_kind: z.enum(["purchase", "refund", "funding", "unknown"]),
    detail_revision: z.number().int().positive(),
    approved_detail_revision: z.number().int().positive(),
    bank_amount: z.string().regex(DECIMAL),
    ledger_semantics: z.literal("enrichment_only"),
  })
  .strict();

const OutputSchema = z
  .object({
    generated_at: z.string().datetime(),
    ledger_semantics: z.literal("single_source_ledger"),
    transaction: TransactionSchema,
    classification: ClassificationSchema.nullable(),
    allocations: z.array(AllocationSchema).max(100),
    allocation_total: z.string().regex(DECIMAL),
    audit_evidence: z.array(AuditEvidenceSchema).max(20),
    linked_paypal: z.array(PaypalDetailSchema).max(10),
  })
  .strict();

const TransactionRowSchema = z
  .object({
    stable_id: z.string().regex(UUID),
    source: ProviderSchema,
    account_id: z.string().regex(UUID),
    booked_at: z.union([z.date(), z.string()]),
    value_date: z.union([z.date(), z.string()]).nullable(),
    kind: z.string(),
    amount: z.string().regex(DECIMAL),
    fee: z.string().regex(DECIMAL),
    tax: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    description: z.string().nullable(),
    counterparty: z.string().nullable(),
    treatment: z.string().nullable(),
    review_state: z.enum(["classified", "needs_review", "unclassified"]).nullable(),
    merchant_id: z.string().regex(UUID).nullable(),
    merchant_name: z.string().nullable(),
    identity_confirmed: z.boolean().nullable(),
    provenance: z.enum(["manual", "rule"]).nullable(),
    rule_id: z.string().regex(UUID).nullable(),
    revision: z.coerce.number().int().positive().nullable(),
    explanation: z.string().nullable(),
  })
  .strict();

const AllocationRowSchema = z
  .object({
    category_id: z.string().regex(UUID),
    category_name: z.string(),
    category_kind: z.enum(["expense", "income"]),
    amount: z.string().regex(DECIMAL),
    currency: z.enum(["DKK", "EUR"]),
    allocation_total: z.string().regex(DECIMAL),
  })
  .strict();

const AuditRowSchema = z
  .object({
    audit_id: z.string().regex(UUID),
    subject_type: z.string(),
    action: z.string(),
    created_at: z.union([z.date(), z.string()]),
  })
  .strict();

const PaypalRowSchema = z
  .object({
    detail_id: z.string().regex(UUID),
    occurred_at: z.union([z.date(), z.string()]),
    amount: z.string().regex(DECIMAL),
    currency: z.string().length(3),
    merchant_name: z.string().nullable(),
    reference: z.string().nullable(),
    event_kind: z.enum(["purchase", "refund", "funding", "unknown"]),
    detail_revision: z.coerce.number().int().positive(),
    approved_detail_revision: z.coerce.number().int().positive(),
    bank_amount: z.string().regex(DECIMAL),
  })
  .strict();

export type GetHouseholdTransactionDetailInput = z.infer<typeof InputSchema>;
export type GetHouseholdTransactionDetailOutput = z.infer<typeof OutputSchema>;

export interface GetHouseholdTransactionDetailOptions {
  runner: HouseholdTransactionQueryRunner & {
    readSnapshot<T>(operation: (runner: HouseholdTransactionQueryRunner) => Promise<T>): Promise<T>;
  };
  now?: () => Date;
}

const TRANSACTION_SQL = `
  SELECT t.id::text AS stable_id, a.provider AS source, a.id::text AS account_id,
    t.ts AS booked_at, t.value_date, t.kind, t.amount::text AS amount,
    t.fee::text AS fee, t.tax::text AS tax, a.currency,
    left(t.description, 240) AS description, left(t.counterparty, 240) AS counterparty,
    c.treatment, c.review_state, c.merchant_id::text AS merchant_id,
    left(m.name, 200) AS merchant_name, c.identity_confirmed, c.provenance,
    c.rule_id::text AS rule_id, c.revision, c.explanation
  FROM transaction AS t
  INNER JOIN account AS a ON a.id = t.account_id
  LEFT JOIN household_classification AS c ON c.transaction_id = t.id
  LEFT JOIN household_merchant AS m ON m.id = c.merchant_id
  WHERE t.id = $1::uuid AND ($2::text IS NULL OR a.provider = $2)
    AND a.provider = ANY($3::text[])
`;

const ALLOCATION_SQL = `
  SELECT x.category_id::text AS category_id, c.name AS category_name, c.kind AS category_kind,
    x.amount::text AS amount, classification.source_currency AS currency,
    sum(x.amount) OVER()::text AS allocation_total
  FROM household_allocation AS x
  INNER JOIN household_category AS c ON c.id = x.category_id
  INNER JOIN household_classification AS classification
    ON classification.transaction_id = x.transaction_id
  WHERE x.transaction_id = $1::uuid
  ORDER BY c.sort_order, c.id
  LIMIT 100
`;

const AUDIT_SQL = `
  SELECT id::text AS audit_id, subject_type, action, created_at
  FROM household_audit
  WHERE subject_id = $1::uuid
  ORDER BY created_at DESC, id DESC
  LIMIT 20
`;

const PAYPAL_SQL = `
  SELECT d.id::text AS detail_id, d.ts AS occurred_at, d.amount::text AS amount,
    d.currency, left(d.merchant_name, 240) AS merchant_name,
    left(d.reference, 240) AS reference, d.event_kind,
    d.revision AS detail_revision, link.detail_revision AS approved_detail_revision,
    link.bank_amount::text AS bank_amount
  FROM household_payment_detail_link AS link
  INNER JOIN household_payment_detail AS d ON d.id = link.detail_id
  WHERE link.transaction_id = $1::uuid AND d.provider = 'paypal'
  ORDER BY d.ts, d.id
  LIMIT 10
`;

function instant(value: Date | string): string {
  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    throw new ToolDataError("transaction detail query returned an invalid timestamp");
  }
  return parsed.toISOString();
}

function date(value: Date | string | null): string | null {
  if (value === null) return null;
  return value instanceof Date ? value.toISOString().slice(0, 10) : value.slice(0, 10);
}

export function getHouseholdTransactionDetailTool(
  opts: GetHouseholdTransactionDetailOptions,
): ToolDefinition<GetHouseholdTransactionDetailInput, GetHouseholdTransactionDetailOutput> {
  return {
    name: "get_household_transaction_detail",
    description:
      "Return one stable-ID household transaction with exact allocations, current classification, audit references, and linked PayPal enrichment without duplicate ledger semantics.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    async handler(args) {
      const providers = ProviderSchema.options;
      const snapshot = await opts.runner.readSnapshot(async (runner) => {
        const transactionResult = await runner.query(TRANSACTION_SQL, [
          args.transaction_id,
          args.source ?? null,
          providers,
        ]);
        const raw = transactionResult.rows[0];
        if (!raw) {
          throw new ToolNotFoundError(`household transaction ${args.transaction_id} was not found`);
        }
        const allocationResult = await runner.query(ALLOCATION_SQL, [args.transaction_id]);
        const auditResult = await runner.query(AUDIT_SQL, [args.transaction_id]);
        const paypalResult = await runner.query(PAYPAL_SQL, [args.transaction_id]);
        return {
          row: TransactionRowSchema.parse(raw),
          allocations: allocationResult.rows.map((value) => AllocationRowSchema.parse(value)),
          audits: auditResult.rows.map((value) => AuditRowSchema.parse(value)),
          paypal: paypalResult.rows.map((value) => PaypalRowSchema.parse(value)),
        };
      });
      const { row, allocations, audits, paypal } = snapshot;
      return {
        generated_at: (opts.now?.() ?? new Date()).toISOString(),
        ledger_semantics: "single_source_ledger",
        transaction: {
          stable_id: row.stable_id,
          source: row.source,
          account_id: row.account_id,
          booked_at: instant(row.booked_at),
          value_date: date(row.value_date),
          kind: row.kind.slice(0, 100),
          amount: row.amount,
          fee: row.fee,
          tax: row.tax,
          currency: row.currency,
          description: row.description === null ? null : redactText(row.description),
          counterparty: row.counterparty === null ? null : redactText(row.counterparty),
        },
        classification:
          row.treatment === null ||
          row.review_state === null ||
          row.identity_confirmed === null ||
          row.provenance === null ||
          row.revision === null ||
          row.explanation === null
            ? null
            : {
                treatment: row.treatment,
                review_state: row.review_state,
                merchant_id: row.merchant_id,
                merchant_name: row.merchant_name === null ? null : redactText(row.merchant_name),
                identity_confirmed: row.identity_confirmed,
                provenance: row.provenance,
                rule_id: row.rule_id,
                revision: row.revision,
                explanation: redactText(row.explanation),
              },
        allocations: allocations.map((allocation) => ({
          category_id: allocation.category_id,
          category_name: redactText(allocation.category_name),
          category_kind: allocation.category_kind,
          amount: allocation.amount,
          currency: allocation.currency,
        })),
        allocation_total: allocations[0]?.allocation_total ?? "0",
        audit_evidence: audits.map((audit) => ({
          audit_id: audit.audit_id,
          subject_type: audit.subject_type,
          action: audit.action,
          created_at: instant(audit.created_at),
        })),
        linked_paypal: paypal.map((detail) => ({
          detail_id: detail.detail_id,
          occurred_at: instant(detail.occurred_at),
          amount: detail.amount,
          currency: detail.currency,
          merchant_name: detail.merchant_name === null ? null : redactText(detail.merchant_name),
          reference: detail.reference === null ? null : redactText(detail.reference),
          event_kind: detail.event_kind,
          detail_revision: detail.detail_revision,
          approved_detail_revision: detail.approved_detail_revision,
          bank_amount: detail.bank_amount,
          ledger_semantics: "enrichment_only",
        })),
      };
    },
  };
}
