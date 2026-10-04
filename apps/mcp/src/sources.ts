import { z } from "zod/v3";

export const SourceKindSchema = z.enum([
  "bank",
  "brokerage",
  "pension",
  "fx",
  "manual",
  "taxonomy",
  "paypal",
  "merchant_reference",
]);

export const SourceStatusSchema = z.enum(["supported", "partial", "deprecated"]);
export const SourceFreshnessSchema = z.enum(["fresh", "stale", "unknown", "partial"]);
export const SourceEvidenceKindSchema = z.enum([
  "catalog",
  "transaction_search",
  "transaction_detail",
  "taxonomy_summary",
  "merchant_summary",
  "rule_summary",
  "merchant_status",
  "merchant_search",
  "fx_summary",
  "manual_fact_summary",
  "paypal_detail",
  "nsi_reference",
]);

export const SourceEvidencePathSchema = z
  .object({
    tool: z.string().min(1),
    kind: SourceEvidenceKindSchema,
    description: z.string().min(1),
  })
  .strict();

export const SourceCatalogEntrySchema = z
  .object({
    id: z.string().min(1),
    label: z.string().min(1),
    kind: SourceKindSchema,
    status: SourceStatusSchema,
    freshness: SourceFreshnessSchema,
    summary: z.string().min(1),
    tools: z.array(z.string().min(1)).min(1),
    evidence_paths: z.array(SourceEvidencePathSchema).min(1),
    notes: z.array(z.string().min(1)),
  })
  .strict();

export type SourceCatalogEntry = z.infer<typeof SourceCatalogEntrySchema>;

export const SOURCE_CATALOG: readonly SourceCatalogEntry[] = [
  {
    id: "gls",
    label: "GLS Bank",
    kind: "bank",
    status: "supported",
    freshness: "fresh",
    summary:
      "GLS checking and savings source evidence for household cashflow and account coverage.",
    tools: [
      "search_household_transactions",
      "get_household_transaction_detail",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        kind: "transaction_search",
        description: "List bounded GLS account transactions by account/date with stable IDs.",
      },
      {
        tool: "get_household_transaction_detail",
        kind: "transaction_detail",
        description:
          "Fetch stable-ID allocations, classification and audit evidence for a GLS transaction.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Expose the GLS source in the typed source catalog and tool mapping.",
      },
    ],
    notes: [
      "GLS is a supported cash-account source; the MCP layer exposes evidence summaries only.",
    ],
  },
  {
    id: "ebank",
    label: "Evangelische Bank",
    kind: "bank",
    status: "supported",
    freshness: "fresh",
    summary:
      "Evangelische Bank account summaries and transaction evidence surfaced read-only over MCP.",
    tools: [
      "search_household_transactions",
      "get_household_transaction_detail",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        kind: "transaction_search",
        description: "Bounded transaction search over Evangelische Bank statements.",
      },
      {
        tool: "get_household_transaction_detail",
        kind: "transaction_detail",
        description: "Stable-ID detail for allocations, classifications and audit lineage.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Source-matrix declaration for Evangelische Bank coverage.",
      },
    ],
    notes: ["MCP exposes evidence summaries, not raw account or statement dumps."],
  },
  {
    id: "lunar",
    label: "Lunar",
    kind: "bank",
    status: "supported",
    freshness: "fresh",
    summary: "Lunar Enable Banking source evidence for card and checking transactions.",
    tools: [
      "search_household_transactions",
      "get_household_transaction_detail",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        kind: "transaction_search",
        description: "Read-only search for Lunar transactions with bounded output.",
      },
      {
        tool: "get_household_transaction_detail",
        kind: "transaction_detail",
        description: "Return Lunar detail and linked PayPal evidence without duplicate ledgers.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Catalog entry for the Lunar source and tool mapping.",
      },
    ],
    notes: ["Enable Banking integration remains read-only and evidence-scoped in MCP."],
  },
  {
    id: "enable_banking",
    label: "Enable Banking",
    kind: "bank",
    status: "supported",
    freshness: "fresh",
    summary:
      "Enable Banking abstractions for the household account sources behind GLS, Lunar and Evangelische Bank.",
    tools: [
      "search_household_transactions",
      "get_household_transaction_detail",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        kind: "transaction_search",
        description: "Bounded transaction search across the Enable Banking-backed account sources.",
      },
      {
        tool: "get_household_transaction_detail",
        kind: "transaction_detail",
        description: "Stable-ID detail with classification and audit-only evidence path.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Allowlist and tool mapping for the shared Enable Banking layer.",
      },
    ],
    notes: ["This is the shared provider layer, not a raw statement dump surface."],
  },
  {
    id: "nordnet",
    label: "Nordnet",
    kind: "brokerage",
    status: "supported",
    freshness: "fresh",
    summary: "Nordnet transaction and holdings evidence via read-only MCP summaries.",
    tools: [
      "search_household_transactions",
      "get_household_transaction_detail",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "search_household_transactions",
        kind: "transaction_search",
        description: "Search Nordnet transactions by date and account with stable IDs.",
      },
      {
        tool: "get_household_transaction_detail",
        kind: "transaction_detail",
        description: "Return Nordnet transaction detail, holdings context, and audit evidence.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Catalog coverage declaration for Nordnet transactions and holdings.",
      },
    ],
    notes: [
      "MCP supports Nordnet transactions and holdings evidence, not full account export dumps.",
    ],
  },
  {
    id: "pfa",
    label: "PFA",
    kind: "pension",
    status: "supported",
    freshness: "stale",
    summary: "PFA pension statement evidence exposed as summary and latest-scan metadata only.",
    tools: ["get_household_taxonomy_summary", "get_source_coverage"],
    evidence_paths: [
      {
        tool: "get_household_taxonomy_summary",
        kind: "taxonomy_summary",
        description: "Summarize pension and household classifications reachable from PFA metadata.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Keep the PFA source in the source coverage matrix.",
      },
    ],
    notes: [
      "PFA is valid as a supported source, but the MCP layer remains summary-only until full detail schemas are upstream.",
    ],
  },
  {
    id: "growney",
    label: "Growney",
    kind: "brokerage",
    status: "supported",
    freshness: "stale",
    summary:
      "Growney statement and holdings data are summarized with coverage metadata for MCP consumers.",
    tools: ["get_household_taxonomy_summary", "get_source_coverage"],
    evidence_paths: [
      {
        tool: "get_household_taxonomy_summary",
        kind: "taxonomy_summary",
        description: "Summarize household allocation and classification coverage for Growney.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Track Growney as a supported source with summary-only evidence.",
      },
    ],
    notes: ["Growney evidence is intentionally bounded to classification and category summaries."],
  },
  {
    id: "ecb_fx",
    label: "ECB FX",
    kind: "fx",
    status: "supported",
    freshness: "fresh",
    summary: "ECB exchange-rate source for FX freshness and missing-currency coverage checks.",
    tools: ["get_source_coverage"],
    evidence_paths: [
      {
        tool: "get_source_coverage",
        kind: "fx_summary",
        description:
          "Expose ECB FX coverage, missing-rate freshness, and source dependency status.",
      },
    ],
    notes: [
      "FX coverage is evaluated by freshness and missing-rate status, not by raw rate dumps.",
    ],
  },
  {
    id: "manual_facts",
    label: "Manual facts",
    kind: "manual",
    status: "supported",
    freshness: "fresh",
    summary:
      "Manual cash balances and valuation facts are available as bounded evidence summaries.",
    tools: ["get_source_coverage", "get_household_taxonomy_summary"],
    evidence_paths: [
      {
        tool: "get_household_taxonomy_summary",
        kind: "manual_fact_summary",
        description: "Return manual fact summaries used for household coverage and balancing.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Document the manual-facts source in the source matrix.",
      },
    ],
    notes: [
      "Manual facts stay bounded to summary metadata; no raw journal or ledger dump is exposed.",
    ],
  },
  {
    id: "household_classification",
    label: "Household classifications",
    kind: "taxonomy",
    status: "supported",
    freshness: "fresh",
    summary:
      "Household taxonomy, merchant mapping and rule summaries used for card and allocation processing.",
    tools: [
      "get_household_taxonomy_summary",
      "get_household_rule_summary",
      "get_household_merchant_summary",
      "get_source_coverage",
    ],
    evidence_paths: [
      {
        tool: "get_household_taxonomy_summary",
        kind: "taxonomy_summary",
        description: "Summarize categories, weights, and coverage from the household taxonomy.",
      },
      {
        tool: "get_household_rule_summary",
        kind: "rule_summary",
        description: "Describe active classification rules and their scope.",
      },
      {
        tool: "get_household_merchant_summary",
        kind: "merchant_summary",
        description: "Summarize merchant-level mappings and classification status.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Declare the taxonomy and classification coverage contract in the MCP matrix.",
      },
    ],
    notes: ["This source is a classification layer, not a raw ledger or statement extractor."],
  },
  {
    id: "paypal",
    label: "PayPal enrichment",
    kind: "paypal",
    status: "supported",
    freshness: "fresh",
    summary:
      "PayPal enrichment detail is exposed as stable linked records without duplicating transaction ledgers.",
    tools: ["get_household_transaction_detail", "get_source_coverage"],
    evidence_paths: [
      {
        tool: "get_household_transaction_detail",
        kind: "paypal_detail",
        description:
          "Expose linked PayPal details for a stable transaction without duplicating ledger semantics.",
      },
      {
        tool: "get_source_coverage",
        kind: "catalog",
        description: "Record the PayPal enrichment source as supported and evidence-backed.",
      },
    ],
    notes: [
      "PayPal detail is attached only as enrichment; the ledger remains single-source and non-duplicative.",
    ],
  },
  {
    id: "nsi_merchant_reference",
    label: "NSI merchant reference",
    kind: "merchant_reference",
    status: "supported",
    freshness: "fresh",
    summary:
      "Local NSI merchant-reference index is exposed through bounded status and search tools.",
    tools: ["get_merchant_reference_status", "search_merchant_reference", "get_source_coverage"],
    evidence_paths: [
      {
        tool: "get_merchant_reference_status",
        kind: "merchant_status",
        description: "Return the local merchant-reference generation and status summary.",
      },
      {
        tool: "search_merchant_reference",
        kind: "merchant_search",
        description: "Search the local public merchant reference index with bounded results.",
      },
      {
        tool: "get_source_coverage",
        kind: "nsi_reference",
        description: "Track the NSI merchant-reference source in the coverage matrix.",
      },
    ],
    notes: [
      "This is the public local reference index and never sends raw customer or account data upstream.",
    ],
  },
];

export const SOURCE_BY_ID = new Map(SOURCE_CATALOG.map((entry) => [entry.id, entry]));
export const SOURCE_ALLOWLIST = SOURCE_CATALOG.map((entry) => entry.id);

export function getSourceCoverage(sourceIds?: readonly string[]): {
  sources: SourceCatalogEntry[];
  missing: string[];
  complete: boolean;
} {
  const requested = sourceIds && sourceIds.length > 0 ? [...new Set(sourceIds)] : SOURCE_ALLOWLIST;
  const sources = requested.flatMap((sourceId) => {
    const entry = SOURCE_BY_ID.get(sourceId);
    return entry ? [entry] : [];
  });
  const missing = requested.filter((sourceId) => !SOURCE_BY_ID.has(sourceId));
  return {
    sources,
    missing,
    complete: missing.length === 0 && sources.length > 0,
  };
}

export function assertCoverageForSource(sourceId: string): void {
  const entry = SOURCE_BY_ID.get(sourceId);
  if (!entry) {
    throw new Error(`source ${sourceId} is not in the supported MCP source catalog`);
  }
  if (entry.evidence_paths.length === 0) {
    throw new Error(`source ${sourceId} is missing its MCP evidence path`);
  }
}
