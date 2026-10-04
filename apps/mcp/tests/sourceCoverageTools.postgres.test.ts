import { describe, expect, it } from "vitest";
import pg from "pg";

import { connect } from "../src/db.js";
import { getHouseholdTransactionDetailTool } from "../src/tools/getHouseholdTransactionDetail.js";
import { getSourceCoverageTool } from "../src/tools/getSourceCoverage.js";
import { searchHouseholdTransactionsTool } from "../src/tools/searchHouseholdTransactions.js";

const enabled = process.env.PENGE_MCP_REPORT_PG_TEST === "1";

describe.skipIf(!enabled)("source coverage tools on disposable PostgreSQL", () => {
  it("executes bounded search and stable-ID detail against synthetic facts", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = new URL(rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:"));
    if (
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      !url.pathname.endsWith("_test")
    ) {
      throw new Error("Only a loopback test-suffixed PostgreSQL database is permitted");
    }
    const fixturePool = new pg.Pool({ connectionString: url.toString() });
    try {
      const entityId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
      const accountId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
      const instrumentId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
      await fixturePool.query("INSERT INTO entity (id, name, kind) VALUES ($1::uuid, $2, $3)", [
        entityId,
        "Synthetic Manual Owner",
        "person",
      ]);
      await fixturePool.query(
        `INSERT INTO account (id, entity_id, provider, external_id, name, kind, currency)
         VALUES ($1::uuid, $2::uuid, 'manual', $3, $4, 'cash', 'EUR')`,
        [accountId, entityId, "synthetic-manual-account", "Synthetic manual account"],
      );
      await fixturePool.query(
        `INSERT INTO instrument (id, name, kind, currency)
         VALUES ($1::uuid, $2, 'cash', 'EUR')`,
        [instrumentId, "Synthetic manual fact"],
      );
      await fixturePool.query(
        `INSERT INTO holding_snapshot (
           id, account_id, instrument_id, as_of, quantity, market_value
         ) VALUES ($1::uuid, $2::uuid, $3::uuid, '2026-06-30', 1, 100)`,
        ["dddddddd-dddd-4ddd-8ddd-dddddddddddd", accountId, instrumentId],
      );
    } finally {
      await fixturePool.end();
    }
    const data = await connect({ databaseUrl: url.toString(), duckdbPath: "" });
    try {
      const client = await data.acquire();
      try {
        const context = { serverName: "postgres-test", serverVersion: "test" };
        const search = searchHouseholdTransactionsTool({ runner: client });
        const page = await search.handler(
          {
            source: "gls",
            date_range: { from: "2026-06-01", to: "2026-06-30" },
            limit: 10,
            offset: 0,
          },
          context,
        );
        search.outputSchema.parse(page);
        expect(page.items.length).toBeGreaterThan(0);
        const transactionId = page.items[0]?.stable_id;
        if (!transactionId) throw new Error("Synthetic GLS transaction fixture is missing");
        const detail = getHouseholdTransactionDetailTool({ runner: client });
        const record = await detail.handler(
          { transaction_id: transactionId, source: "gls" },
          context,
        );
        detail.outputSchema.parse(record);
        expect(record.transaction.stable_id).toBe(transactionId);
        expect(record.ledger_semantics).toBe("single_source_ledger");

        const coverage = getSourceCoverageTool({ runner: client });
        const matrix = await coverage.handler(
          {
            source_ids: [
              "gls",
              "manual_facts",
              "household_classification",
              "paypal",
              "ecb_fx",
              "pfa",
            ],
          },
          context,
        );
        coverage.outputSchema.parse(matrix);
        expect(matrix.sources).toHaveLength(6);
        expect(matrix.sources.find((source) => source.id === "gls")?.coverage.account_count).toBe(
          1,
        );
        const manual = matrix.sources.find((source) => source.id === "manual_facts")?.coverage;
        expect(manual?.account_count).toBe(1);
        expect(manual?.holding_count).toBe(1);
        expect(manual?.completeness).toBe("complete");
        expect(
          matrix.sources.find((source) => source.id === "household_classification")?.coverage
            .transaction_count,
        ).toBeGreaterThan(0);
        expect(
          matrix.sources.find((source) => source.id === "household_classification")?.coverage
            .evidence_count,
        ).toBeGreaterThan(0);
        expect(
          matrix.sources.find((source) => source.id === "paypal")?.coverage.evidence_count,
        ).toBeGreaterThan(0);
        expect(
          matrix.sources.find((source) => source.id === "ecb_fx")?.coverage.evidence_count,
        ).toBeGreaterThan(0);
        expect(matrix.sources.find((source) => source.id === "pfa")?.coverage.completeness).toBe(
          "missing",
        );
      } finally {
        client.release();
      }
    } finally {
      await data.close();
    }
  });
});
