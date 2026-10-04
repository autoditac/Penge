import { describe, expect, it } from "vitest";

import { ToolDataError } from "../src/errors.js";
import { getHouseholdMerchantSummaryTool } from "../src/tools/getHouseholdMerchantSummary.js";
import { getHouseholdRuleSummaryTool } from "../src/tools/getHouseholdRuleSummary.js";
import { getHouseholdTaxonomySummaryTool } from "../src/tools/getHouseholdTaxonomySummary.js";
import { getHouseholdTransactionDetailTool } from "../src/tools/getHouseholdTransactionDetail.js";
import { getMerchantReferenceStatusTool } from "../src/tools/getMerchantReferenceStatus.js";
import { getSourceCoverageTool } from "../src/tools/getSourceCoverage.js";
import { searchHouseholdTransactionsTool } from "../src/tools/searchHouseholdTransactions.js";
import { searchMerchantReferenceTool } from "../src/tools/searchMerchantReference.js";

const NOW = new Date("2026-10-04T08:00:00.000Z");
const CTX = { serverName: "test", serverVersion: "test" };
const TX = "11111111-1111-4111-8111-111111111111";
const ACCOUNT = "22222222-2222-4222-8222-222222222222";
const CATEGORY = "33333333-3333-4333-8333-333333333333";
const MERCHANT = "44444444-4444-4444-8444-444444444444";
const AUDIT = "66666666-6666-4666-8666-666666666666";
const DETAIL = "77777777-7777-4777-8777-777777777777";
const RULE = "88888888-8888-4888-8888-888888888888";
const GENERATION = "99999999-9999-4999-8999-999999999999";
const REFERENCE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function fixedRows(rows: Array<Record<string, unknown>>) {
  return {
    async query() {
      return { rows };
    },
  };
}

describe("source coverage tools", () => {
  it("reports stale and missing evidence without claiming completeness", async () => {
    const tool = getSourceCoverageTool({
      runner: fixedRows([
        {
          source_id: "ecb_fx",
          account_count: 0,
          transaction_count: 0,
          holding_count: 0,
          evidence_count: 12,
          latest_observed_at: "2026-09-20T00:00:00.000Z",
        },
        {
          source_id: "paypal",
          account_count: 0,
          transaction_count: 0,
          holding_count: 0,
          evidence_count: 0,
          latest_observed_at: null,
        },
      ]),
      now: () => NOW,
    });
    const out = await tool.handler({ source_ids: ["ecb_fx", "paypal"] }, CTX);
    tool.outputSchema.parse(out);
    expect(out.sources[0]?.coverage.freshness).toBe("stale");
    expect(out.sources[0]?.coverage.completeness).toBe("complete");
    expect(out.sources[1]?.coverage.freshness).toBe("unknown");
    expect(out.sources[1]?.coverage.completeness).toBe("missing");
    expect(out.tool_allowlist).toContain("query_net_worth");
    expect(out.complete).toBe(false);
  });

  it("maps observed manual provider data to manual_facts", async () => {
    const tool = getSourceCoverageTool({
      runner: fixedRows([
        {
          source_id: "manual_facts",
          account_count: 2,
          transaction_count: 0,
          holding_count: 2,
          evidence_count: 2,
          latest_observed_at: "2026-10-01T00:00:00.000Z",
        },
      ]),
      now: () => NOW,
    });
    const out = await tool.handler({ source_ids: ["manual_facts"] }, CTX);
    expect(out.sources[0]?.coverage.completeness).toBe("complete");
    expect(out.sources[0]?.coverage.freshness).toBe("fresh");
  });

  it.each([
    {
      source_id: "enable_banking" as const,
      account_count: 1,
      transaction_count: 0,
      holding_count: 0,
      evidence_count: 0,
      expected: "partial",
    },
    {
      source_id: "manual_facts" as const,
      account_count: 1,
      transaction_count: 0,
      holding_count: 0,
      evidence_count: 0,
      expected: "partial",
    },
    {
      source_id: "household_classification" as const,
      account_count: 0,
      transaction_count: 2,
      holding_count: 0,
      evidence_count: 0,
      expected: "partial",
    },
    {
      source_id: "household_classification" as const,
      account_count: 0,
      transaction_count: 2,
      holding_count: 0,
      evidence_count: 2,
      expected: "complete",
    },
  ])("marks $source_id evidence as $expected", async (row) => {
    const { expected, ...observation } = row;
    const tool = getSourceCoverageTool({
      runner: fixedRows([{ ...observation, latest_observed_at: "2026-10-01T00:00:00.000Z" }]),
      now: () => NOW,
    });
    const out = await tool.handler({ source_ids: [row.source_id] }, CTX);
    expect(out.sources[0]?.coverage.completeness).toBe(expected);
  });

  it("rejects future observations instead of treating them as fresh", async () => {
    const tool = getSourceCoverageTool({
      runner: fixedRows([
        {
          source_id: "ecb_fx",
          account_count: 0,
          transaction_count: 0,
          holding_count: 0,
          evidence_count: 1,
          latest_observed_at: "2026-10-05T00:00:00.000Z",
        },
      ]),
      now: () => NOW,
    });
    await expect(tool.handler({ source_ids: ["ecb_fx"] }, CTX)).rejects.toBeInstanceOf(
      ToolDataError,
    );
  });

  it("returns bounded transaction rows from the query runner", async () => {
    const tool = searchHouseholdTransactionsTool({
      runner: fixedRows([
        {
          stable_id: TX,
          source: "gls",
          account_id: ACCOUNT,
          transaction_date: "2026-06-02",
          description: "Synthetic grocery",
          counterparty: "Synthetic Market",
          amount: "-125.4000",
          currency: "EUR",
          treatment: "expense",
          review_state: "classified",
          provenance: "manual",
          revision: 1,
          merchant_id: MERCHANT,
          allocation_count: 1,
          audit_id: AUDIT,
          audit_action: "create",
          audit_created_at: "2026-06-03T00:00:00.000Z",
          total_count: 1,
        },
      ]),
      now: () => NOW,
    });
    const out = await tool.handler(
      {
        date_range: { from: "2026-06-01", to: "2026-06-30" },
        limit: 10,
        offset: 0,
      },
      CTX,
    );
    tool.outputSchema.parse(out);
    expect(out.total).toBe(1);
    expect(out.items[0]?.classification?.allocation_count).toBe(1);
  });

  it("returns exact allocations and PayPal as enrichment-only detail", async () => {
    const runner = {
      async query(sql: string) {
        if (sql.includes("FROM transaction AS t")) {
          return {
            rows: [
              {
                stable_id: TX,
                source: "gls",
                account_id: ACCOUNT,
                booked_at: "2026-06-02T10:00:00.000Z",
                value_date: "2026-06-02",
                kind: "card",
                amount: "-125.4000",
                fee: "0.0000",
                tax: "0.0000",
                currency: "EUR",
                description: "Synthetic purchase",
                counterparty: "Synthetic Market",
                treatment: "expense",
                review_state: "classified",
                merchant_id: MERCHANT,
                merchant_name: "Synthetic Market",
                identity_confirmed: true,
                provenance: "manual",
                rule_id: null,
                revision: 2,
                explanation: "Synthetic manual classification",
              },
            ],
          };
        }
        if (sql.includes("FROM household_allocation AS x")) {
          return {
            rows: [
              {
                category_id: CATEGORY,
                category_name: "Groceries",
                category_kind: "expense",
                amount: "-125.4000",
                currency: "EUR",
                allocation_total: "-125.4000",
              },
            ],
          };
        }
        if (sql.includes("FROM household_audit")) {
          return {
            rows: [
              {
                audit_id: AUDIT,
                subject_type: "classification",
                action: "update",
                created_at: "2026-06-03T00:00:00.000Z",
              },
            ],
          };
        }
        return {
          rows: [
            {
              detail_id: DETAIL,
              occurred_at: "2026-06-02T09:59:00.000Z",
              amount: "-125.4000",
              currency: "EUR",
              merchant_name: "Synthetic Market",
              reference: "Synthetic basket",
              event_kind: "purchase",
              detail_revision: 2,
              approved_detail_revision: 2,
              bank_amount: "-125.4000",
            },
          ],
        };
      },
    };
    const tool = getHouseholdTransactionDetailTool({ runner, now: () => NOW });
    const out = await tool.handler({ transaction_id: TX }, CTX);
    tool.outputSchema.parse(out);
    expect(out.allocation_total).toBe("-125.4000");
    expect(out.allocations).toHaveLength(1);
    expect(out.linked_paypal).toHaveLength(1);
    expect(out.linked_paypal[0]?.ledger_semantics).toBe("enrichment_only");
    expect(out.ledger_semantics).toBe("single_source_ledger");
  });

  it("maps bounded taxonomy, rule, and merchant summary rows", async () => {
    const taxonomy = getHouseholdTaxonomySummaryTool({
      runner: fixedRows([
        {
          category_id: CATEGORY,
          name: "Groceries",
          kind: "expense",
          parent_id: null,
          sort_order: 1,
          archived: false,
          revision: 1,
          allocation_count: 2,
          classified_transaction_count: 2,
          total_count: 1,
        },
      ]),
      now: () => NOW,
    });
    const taxonomyOut = await taxonomy.handler(
      { include_archived: false, limit: 25, offset: 0 },
      CTX,
    );
    taxonomy.outputSchema.parse(taxonomyOut);

    const rules = getHouseholdRuleSummaryTool({
      runner: fixedRows([
        {
          rule_id: RULE,
          merchant_id: MERCHANT,
          merchant_name: "Synthetic Market",
          version: 1,
          state: "active",
          category_id: CATEGORY,
          category_name: "Groceries",
          treatment: "expense",
          explanation: "Synthetic exact alias",
          created_at: "2026-06-01T00:00:00.000Z",
          total_count: 1,
        },
      ]),
      now: () => NOW,
    });
    const ruleOut = await rules.handler({ limit: 25, offset: 0 }, CTX);
    rules.outputSchema.parse(ruleOut);

    const merchants = getHouseholdMerchantSummaryTool({
      runner: fixedRows([
        {
          merchant_id: MERCHANT,
          name: "Synthetic Market",
          identity_kind: "stable",
          confirmed: true,
          archived: false,
          revision: 1,
          rule_version: 1,
          alias_count: 1,
          active_rule_count: 1,
          classified_transaction_count: 2,
          reference_source: "nsi",
          reference_key: "synthetic-market",
          reference_version: "fixture-v1",
          total_count: 1,
        },
      ]),
      now: () => NOW,
    });
    const merchantOut = await merchants.handler(
      { include_archived: false, limit: 25, offset: 0 },
      CTX,
    );
    merchants.outputSchema.parse(merchantOut);
    expect(taxonomyOut.entries).toHaveLength(1);
    expect(ruleOut.rules).toHaveLength(1);
    expect(merchantOut.merchants[0]?.reference?.source).toBe("nsi");
  });

  it("returns local NSI status and bounded search results", async () => {
    const status = getMerchantReferenceStatusTool({
      runner: fixedRows([
        {
          source_id: "nsi",
          status: "current",
          active_generation_id: GENERATION,
          source_version: "fixture-v1",
          record_count: 1,
          source_generated_at: "2026-10-01T00:00:00.000Z",
          last_checked_at: "2026-10-04T00:00:00.000Z",
          last_success_at: "2026-10-04T00:00:00.000Z",
          error_code: null,
        },
      ]),
      now: () => NOW,
    });
    const statusOut = await status.handler({ source_id: "nsi" }, CTX);
    status.outputSchema.parse(statusOut);

    const search = searchMerchantReferenceTool({
      runner: fixedRows([
        {
          reference_id: REFERENCE,
          source_entity_id: "synthetic-market",
          label: "Synthetic Market",
          aliases: ["Synthetic Shop"],
          category_path: "retail/grocery",
          wikidata_id: null,
          source_version: "fixture-v1",
          source_revision_at: "2026-10-01T00:00:00.000Z",
          total_count: 1,
        },
      ]),
      now: () => NOW,
    });
    const searchOut = await search.handler({ query: "synthetic", limit: 10, offset: 0 }, CTX);
    search.outputSchema.parse(searchOut);
    expect(statusOut.status).toBe("current");
    expect(searchOut.results[0]?.label).toBe("Synthetic Market");
  });
});
