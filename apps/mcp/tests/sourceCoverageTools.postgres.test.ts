import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { describe, expect, it } from "vitest";
import pg from "pg";

import { connect } from "../src/db.js";
import { getHouseholdTransactionDetailTool } from "../src/tools/getHouseholdTransactionDetail.js";
import {
  getSourceCoverageTool,
  type GetSourceCoverageOutput,
} from "../src/tools/getSourceCoverage.js";
import { MCP_READ_ONLY_TOOL_ALLOWLIST } from "../src/sources.js";
import { queryNetWorthTool } from "../src/tools/queryNetWorth.js";
import { searchHouseholdTransactionsTool } from "../src/tools/searchHouseholdTransactions.js";

const enabled = process.env.PENGE_MCP_REPORT_PG_TEST === "1";
const SYNTHETIC_ENTITY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SYNTHETIC_ACCOUNT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const SYNTHETIC_INSTRUMENT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const SYNTHETIC_HOLDING_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

async function cleanSyntheticFacts(pool: pg.Pool): Promise<void> {
  await pool.query(
    `DELETE FROM public.holding_snapshot
     WHERE id = $1::uuid OR account_id = $2::uuid OR instrument_id = $3::uuid`,
    [SYNTHETIC_HOLDING_ID, SYNTHETIC_ACCOUNT_ID, SYNTHETIC_INSTRUMENT_ID],
  );
  await pool.query("DELETE FROM public.account WHERE id = $1::uuid", [SYNTHETIC_ACCOUNT_ID]);
  await pool.query("DELETE FROM public.instrument WHERE id = $1::uuid", [SYNTHETIC_INSTRUMENT_ID]);
  await pool.query("DELETE FROM public.entity WHERE id = $1::uuid", [SYNTHETIC_ENTITY_ID]);
}

async function isolateCoverageFacts(
  client: pg.PoolClient,
  transactionId: string,
  accountId: string,
): Promise<void> {
  await client.query(
    `CREATE TEMP TABLE account AS
     SELECT *
     FROM public.account
     WHERE id IN ($1::uuid, $2::uuid)`,
    [accountId, SYNTHETIC_ACCOUNT_ID],
  );
  await client.query(
    `CREATE TEMP TABLE transaction AS
     SELECT *
     FROM public.transaction
     WHERE id = $1::uuid`,
    [transactionId],
  );
  await client.query(
    `CREATE TEMP TABLE holding_snapshot AS
     SELECT *
     FROM public.holding_snapshot
     WHERE id = $1::uuid`,
    [SYNTHETIC_HOLDING_ID],
  );
  await client.query(
    `CREATE TEMP TABLE fx_rate AS
     SELECT *
     FROM public.fx_rate
     WHERE base_ccy = 'EUR' AND quote_ccy = 'DKK'
     ORDER BY as_of DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_classification AS
     SELECT *
     FROM public.household_classification
     ORDER BY transaction_id
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_allocation AS
     SELECT *
     FROM public.household_allocation
     ORDER BY transaction_id, category_id
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_audit AS
     SELECT *
     FROM public.household_audit
     ORDER BY created_at DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE household_payment_detail AS
     SELECT *
     FROM public.household_payment_detail
     WHERE provider = 'paypal'
     ORDER BY last_seen_at DESC
     LIMIT 1`,
  );
  await client.query(
    `CREATE TEMP TABLE merchant_reference_generation AS
     SELECT *
     FROM public.merchant_reference_generation
     WHERE status = 'active' AND source_id = 'name-suggestion-index'
     ORDER BY completed_at DESC
     LIMIT 1`,
  );
}

describe.skipIf(!enabled)("source coverage tools on disposable PostgreSQL", () => {
  it("starts the stdio MCP server with only PENGE_DB_URL_FILE", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:");
    const dir = mkdtempSync(join(tmpdir(), "penge-mcp-stdio-"));
    const secretFile = join(dir, "database-url");
    writeFileSync(secretFile, `${url}\n`, { mode: 0o600 });
    const transport = new StdioClientTransport({
      command: join(process.cwd(), "node_modules", ".bin", "tsx"),
      args: ["src/index.ts"],
      cwd: process.cwd(),
      env: {
        ...getDefaultEnvironment(),
        PENGE_DB_URL_FILE: secretFile,
        PENGE_DUCKDB_PATH: join(dir, "marts.duckdb"),
        PENGE_MCP_LOG_DIR: join(dir, "audit"),
      },
      stderr: "pipe",
    });
    const client = new Client(
      { name: "penge-file-only-test", version: "test" },
      { capabilities: {} },
    );
    try {
      await client.connect(transport);
      const tools = await client.listTools();
      expect(tools.tools.map((tool) => tool.name).sort()).toEqual(
        [...MCP_READ_ONLY_TOOL_ALLOWLIST].sort(),
      );
      expect(tools.tools.every((tool) => tool.outputSchema !== undefined)).toBe(true);
      const result = await client.callTool({ name: "_meta", arguments: {} });
      expect(result.structuredContent).toMatchObject({ serverName: "penge-mcp" });
    } finally {
      await client.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("fails closed on missing net-worth FX in actual PostgreSQL aggregation", async () => {
    const rawUrl = process.env.PENGE_TEST_DATABASE_URL;
    if (!rawUrl || process.env.PENGE_ALLOW_DESTRUCTIVE_TEST_DB !== "1") {
      throw new Error("Explicit disposable test database opt-in is required");
    }
    const url = rawUrl.replace(/^postgresql\+psycopg:/, "postgresql:");
    const pool = new pg.Pool({ connectionString: url });
    const client = await pool.connect();
    try {
      await client.query(`
        CREATE TEMP TABLE account (
          id uuid PRIMARY KEY,
          provider text NOT NULL,
          kind text NOT NULL
        );
        CREATE TEMP TABLE mart_net_worth_daily (
          account_id uuid NOT NULL,
          as_of date NOT NULL,
          balance_eur numeric,
          balance_dkk numeric
        );
        INSERT INTO account VALUES
          ('11111111-1111-4111-8111-111111111111', 'manual', 'cash'),
          ('22222222-2222-4222-8222-222222222222', 'manual', 'cash');
        INSERT INTO mart_net_worth_daily VALUES
          ('11111111-1111-4111-8111-111111111111', '2026-06-30', 100, 746),
          ('22222222-2222-4222-8222-222222222222', '2026-06-30', NULL, NULL);
      `);
      const tool = queryNetWorthTool({
        runner: {
          query: (sql, params) => client.query(sql, [...params]),
        },
        martTable: "pg_temp.mart_net_worth_daily",
        accountTable: "pg_temp.account",
      });
      await expect(
        tool.handler(
          {
            date_range: { from: "2026-06-30", to: "2026-06-30" },
            currency: "EUR",
            breakdown_by: "none",
            source: "manual_facts",
          },
          { serverName: "postgres-test", serverVersion: "test" },
        ),
      ).rejects.toThrow(/cannot value every selected row in EUR/);
    } finally {
      client.release();
      await pool.end();
    }
  });

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
      await cleanSyntheticFacts(fixturePool);
      await fixturePool.query("INSERT INTO entity (id, name, kind) VALUES ($1::uuid, $2, $3)", [
        SYNTHETIC_ENTITY_ID,
        "Synthetic Manual Owner",
        "person",
      ]);
      await fixturePool.query(
        `INSERT INTO account (id, entity_id, provider, external_id, name, kind, currency)
         VALUES ($1::uuid, $2::uuid, 'manual', $3, $4, 'cash', 'EUR')`,
        [
          SYNTHETIC_ACCOUNT_ID,
          SYNTHETIC_ENTITY_ID,
          "synthetic-manual-account",
          "Synthetic manual account",
        ],
      );
      await fixturePool.query(
        `INSERT INTO instrument (id, name, kind, currency)
         VALUES ($1::uuid, $2, 'cash', 'EUR')`,
        [SYNTHETIC_INSTRUMENT_ID, "Synthetic manual fact"],
      );
      await fixturePool.query(
        `INSERT INTO holding_snapshot (
           id, account_id, instrument_id, as_of, quantity, market_value
         ) VALUES ($1::uuid, $2::uuid, $3::uuid, '2026-06-30', 1, 100)`,
        [SYNTHETIC_HOLDING_ID, SYNTHETIC_ACCOUNT_ID, SYNTHETIC_INSTRUMENT_ID],
      );
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
          const detail = getHouseholdTransactionDetailTool({
            runner: {
              query: (sql, params) => client.query(sql, [...params]),
              async readSnapshot<T>(operation: (runner: typeof client) => Promise<T>): Promise<T> {
                await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
                try {
                  const result = await operation(client);
                  await client.query("COMMIT");
                  return result;
                } catch (error) {
                  await client.query("ROLLBACK");
                  throw error;
                }
              },
            },
          });
          const record = await detail.handler(
            { transaction_id: transactionId, source: "gls" },
            context,
          );
          detail.outputSchema.parse(record);
          expect(record.transaction.stable_id).toBe(transactionId);
          expect(record.ledger_semantics).toBe("single_source_ledger");

          const accountId = page.items[0]?.account_id;
          if (!accountId) throw new Error("Synthetic GLS account fixture is missing");
          const coverageClient = await fixturePool.connect();
          let matrix: GetSourceCoverageOutput;
          try {
            await isolateCoverageFacts(coverageClient, transactionId, accountId);
            await coverageClient.query(
              `UPDATE account SET updated_at = '2000-01-01T00:00:00Z'
               WHERE id = $1::uuid`,
              [accountId],
            );
            await coverageClient.query(
              `UPDATE transaction SET created_at = '2026-12-30T12:00:00Z'
               WHERE id = $1::uuid`,
              [transactionId],
            );
            await coverageClient.query("BEGIN TRANSACTION READ ONLY");
            const coverage = getSourceCoverageTool({
              runner: coverageClient,
              now: () => new Date("2026-12-31T00:00:00Z"),
            });
            try {
              matrix = await coverage.handler(
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
              await coverageClient.query("COMMIT");
            } catch (error) {
              await coverageClient.query("ROLLBACK");
              throw error;
            }
          } finally {
            coverageClient.release();
          }
          expect(matrix.sources).toHaveLength(6);
          expect(matrix.sources.find((source) => source.id === "gls")?.coverage.account_count).toBe(
            1,
          );
          expect(
            matrix.sources.find((source) => source.id === "gls")?.coverage.transaction_count,
          ).toBe(1);
          expect(matrix.sources.find((source) => source.id === "gls")?.coverage.freshness).toBe(
            "fresh",
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
    } finally {
      await cleanSyntheticFacts(fixturePool);
      await fixturePool.end();
    }
  });
});
