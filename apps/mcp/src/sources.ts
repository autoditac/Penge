import { z } from "zod/v3";

import { SourceCoverageError } from "./errors.js";

export const SourceIdSchema = z.enum([
  "gls",
  "ebank",
  "lunar",
  "enable_banking",
  "nordnet",
  "pfa",
  "growney",
  "ecb_fx",
  "manual_facts",
  "household_classification",
  "paypal",
  "nsi_merchant_reference",
]);
export type SourceId = z.infer<typeof SourceIdSchema>;

export const SourceKindSchema = z.enum([
  "bank",
  "brokerage",
  "pension",
  "fx",
  "manual",
  "taxonomy",
  "enrichment",
  "merchant_reference",
]);

export const SourceCapabilitySchema = z.enum([
  "transactions",
  "holdings",
  "balances",
  "fx_rates",
  "manual_facts",
  "classifications",
  "allocations",
  "rules",
  "merchant_aliases",
  "payment_enrichment",
  "merchant_reference",
]);

export const EvidenceToolNameSchema = z.enum([
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "get_source_coverage",
  "search_household_transactions",
  "get_household_transaction_detail",
  "get_household_taxonomy_summary",
  "get_household_rule_summary",
  "get_household_merchant_summary",
  "get_merchant_reference_status",
  "search_merchant_reference",
]);
export type EvidenceToolName = z.infer<typeof EvidenceToolNameSchema>;

export const MCP_READ_ONLY_TOOL_ALLOWLIST = [
  "_meta",
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "search_household_transactions",
  "get_household_transaction_detail",
  "get_household_taxonomy_summary",
  "get_household_rule_summary",
  "get_household_merchant_summary",
  "get_merchant_reference_status",
  "search_merchant_reference",
  "get_source_coverage",
  "compute_tax_year",
  "run_scenario",
  "answer_planning_question",
  "search_documents",
  "suggest_import_mapping",
] as const;

export const SourceEvidencePathSchema = z
  .object({
    tool: EvidenceToolNameSchema,
    evidence: z.string().min(1).max(240),
  })
  .strict();

export const SourceCatalogEntrySchema = z
  .object({
    id: SourceIdSchema,
    label: z.string().min(1).max(120),
    kind: SourceKindSchema,
    capabilities: z.array(SourceCapabilitySchema).min(1),
    evidence_paths: z.array(SourceEvidencePathSchema).min(1),
    stale_after_days: z.number().int().positive().max(400),
  })
  .strict();
export type SourceCatalogEntry = z.infer<typeof SourceCatalogEntrySchema>;

const entries = {
  gls: {
    id: "gls",
    label: "GLS Bank",
    kind: "bank",
    capabilities: ["transactions", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded transaction search over GLS accounts.",
      },
      {
        tool: "get_household_transaction_detail",
        evidence: "Stable transaction detail with classification and audit lineage.",
      },
      {
        tool: "query_household_report",
        evidence: "Exact EUR/DKK household allocations and missing-FX evidence.",
      },
      { tool: "get_source_coverage", evidence: "Account and transaction freshness counts." },
    ],
    stale_after_days: 8,
  },
  ebank: {
    id: "ebank",
    label: "Evangelische Bank",
    kind: "bank",
    capabilities: ["transactions", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded transaction search over Evangelische Bank accounts.",
      },
      {
        tool: "get_household_transaction_detail",
        evidence: "Stable transaction detail with classification and audit lineage.",
      },
      {
        tool: "query_household_report",
        evidence: "Exact EUR/DKK household allocations and missing-FX evidence.",
      },
      { tool: "get_source_coverage", evidence: "Account and transaction freshness counts." },
    ],
    stale_after_days: 8,
  },
  lunar: {
    id: "lunar",
    label: "Lunar",
    kind: "bank",
    capabilities: ["transactions", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded transaction search over Lunar accounts.",
      },
      {
        tool: "get_household_transaction_detail",
        evidence: "Stable detail with linked payment enrichment.",
      },
      {
        tool: "query_household_report",
        evidence: "Exact EUR/DKK household allocations and missing-FX evidence.",
      },
      { tool: "get_source_coverage", evidence: "Account and transaction freshness counts." },
    ],
    stale_after_days: 8,
  },
  enable_banking: {
    id: "enable_banking",
    label: "Enable Banking",
    kind: "bank",
    capabilities: ["transactions", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Provider-backed GLS, Evangelische Bank, and Lunar transactions.",
      },
      {
        tool: "query_cashflow",
        evidence: "Bounded provider-backed cashflow aggregates.",
      },
      { tool: "get_source_coverage", evidence: "Aggregate provider-layer freshness." },
    ],
    stale_after_days: 8,
  },
  nordnet: {
    id: "nordnet",
    label: "Nordnet",
    kind: "brokerage",
    capabilities: ["transactions", "holdings", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded Nordnet transaction search.",
      },
      {
        tool: "get_household_transaction_detail",
        evidence: "Stable Nordnet transaction detail.",
      },
      {
        tool: "query_net_worth",
        evidence: "Bounded Nordnet holding valuation aggregates.",
      },
      { tool: "get_source_coverage", evidence: "Transaction and holding freshness counts." },
    ],
    stale_after_days: 35,
  },
  pfa: {
    id: "pfa",
    label: "PFA",
    kind: "pension",
    capabilities: ["transactions", "holdings", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded pension transaction evidence when present.",
      },
      {
        tool: "query_net_worth",
        evidence: "Bounded PFA holding valuation aggregates.",
      },
      { tool: "get_source_coverage", evidence: "PFA account, transaction, and holding counts." },
    ],
    stale_after_days: 400,
  },
  growney: {
    id: "growney",
    label: "Growney",
    kind: "brokerage",
    capabilities: ["transactions", "holdings", "balances"],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        evidence: "Bounded Growney transaction evidence when present.",
      },
      {
        tool: "query_net_worth",
        evidence: "Bounded Growney holding valuation aggregates.",
      },
      {
        tool: "get_source_coverage",
        evidence: "Growney account, transaction, and holding counts.",
      },
    ],
    stale_after_days: 100,
  },
  ecb_fx: {
    id: "ecb_fx",
    label: "ECB FX",
    kind: "fx",
    capabilities: ["fx_rates"],
    evidence_paths: [
      {
        tool: "query_household_report",
        evidence: "Exact EUR/DKK totals with explicit missing-FX counts.",
      },
      {
        tool: "query_net_worth",
        evidence: "EUR/DKK-valued household holdings using the canonical FX mart.",
      },
    ],
    stale_after_days: 5,
  },
  manual_facts: {
    id: "manual_facts",
    label: "Manual facts",
    kind: "manual",
    capabilities: ["manual_facts", "balances", "holdings"],
    evidence_paths: [
      {
        tool: "query_net_worth",
        evidence: "Bounded manual balance and valuation aggregates.",
      },
      {
        tool: "get_source_coverage",
        evidence: "Manual account and snapshot counts with latest observation.",
      },
    ],
    stale_after_days: 100,
  },
  household_classification: {
    id: "household_classification",
    label: "Household classifications",
    kind: "taxonomy",
    capabilities: ["classifications", "allocations", "rules", "merchant_aliases"],
    evidence_paths: [
      {
        tool: "get_household_taxonomy_summary",
        evidence: "Bounded category tree and usage counts.",
      },
      { tool: "get_household_rule_summary", evidence: "Bounded append-only rule summaries." },
      {
        tool: "get_household_merchant_summary",
        evidence: "Bounded household merchant and alias summaries.",
      },
      {
        tool: "get_household_transaction_detail",
        evidence: "Exact allocations and current classification by stable transaction ID.",
      },
      {
        tool: "get_source_coverage",
        evidence: "Classification count and latest audit observation.",
      },
    ],
    stale_after_days: 35,
  },
  paypal: {
    id: "paypal",
    label: "PayPal enrichment",
    kind: "enrichment",
    capabilities: ["payment_enrichment"],
    evidence_paths: [
      {
        tool: "get_household_transaction_detail",
        evidence: "Linked PayPal detail marked explicitly as non-ledger enrichment.",
      },
      {
        tool: "get_source_coverage",
        evidence: "Payment-detail count and latest observed revision.",
      },
    ],
    stale_after_days: 8,
  },
  nsi_merchant_reference: {
    id: "nsi_merchant_reference",
    label: "NSI merchant reference",
    kind: "merchant_reference",
    capabilities: ["merchant_reference"],
    evidence_paths: [
      {
        tool: "get_merchant_reference_status",
        evidence: "Local refresh state and active generation metadata.",
      },
      {
        tool: "search_merchant_reference",
        evidence: "Bounded local label and alias search.",
      },
      { tool: "get_source_coverage", evidence: "Active generation freshness and row count." },
    ],
    stale_after_days: 35,
  },
} satisfies Record<SourceId, SourceCatalogEntry>;

export const SOURCE_CATALOG: readonly SourceCatalogEntry[] = SourceIdSchema.options.map(
  (id) => entries[id],
);
export const SOURCE_ALLOWLIST: readonly SourceId[] = SourceIdSchema.options;

export function assertSourceCatalogCoverage(
  catalog: readonly SourceCatalogEntry[] = SOURCE_CATALOG,
): void {
  const byId = new Map(catalog.map((entry) => [entry.id, entry]));
  for (const id of SOURCE_ALLOWLIST) {
    const entry = byId.get(id);
    if (!entry) {
      throw new SourceCoverageError(`supported source ${id} is missing from the MCP catalog`);
    }
    if (entry.evidence_paths.length === 0) {
      throw new SourceCoverageError(`supported source ${id} has no MCP evidence path`);
    }
    if (entry.evidence_paths.every((path) => path.tool === "get_source_coverage")) {
      throw new SourceCoverageError(`supported source ${id} has no data-bearing MCP evidence path`);
    }
    for (const path of entry.evidence_paths) {
      EvidenceToolNameSchema.parse(path.tool);
    }
  }
}

export function assertRegisteredToolAllowlist(registeredTools: readonly string[]): void {
  const expected = new Set<string>(MCP_READ_ONLY_TOOL_ALLOWLIST);
  const registered = new Set(registeredTools);
  const missing = [...expected].filter((tool) => !registered.has(tool));
  const unexpected = [...registered].filter((tool) => !expected.has(tool));
  if (missing.length > 0 || unexpected.length > 0) {
    throw new SourceCoverageError(
      `registered MCP tools differ from the read-only allowlist: ` +
        `missing=${missing.join(",") || "none"} unexpected=${unexpected.join(",") || "none"}`,
    );
  }
}
