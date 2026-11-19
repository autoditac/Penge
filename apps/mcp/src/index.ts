#!/usr/bin/env node
/**
 * Penge MCP server entrypoint. Speaks JSON-RPC over stdio so it can be
 * launched directly by MCP hosts (Claude Desktop, VS Code Copilot Chat, etc.).
 */

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { createAuditLogger } from "./audit.js";
import { loadConfig } from "./config.js";
import { connect } from "./db.js";
import { buildServer } from "./server.js";
import { createPengeTools } from "./tools/index.js";
import { assertRegisteredToolAllowlist, assertSourceCatalogCoverage } from "./sources.js";
import type { HouseholdTransactionQueryRunner } from "./tools/searchHouseholdTransactions.js";

const SERVER_NAME = "penge-mcp";
const SERVER_VERSION = "0.0.0";

async function main(): Promise<void> {
  const config = loadConfig();
  const audit = createAuditLogger({
    logDir: config.logDir,
    ...(config.actorId === undefined ? {} : { actorId: config.actorId }),
    ...(config.sessionId === undefined ? {} : { sessionId: config.sessionId }),
  });
  const data = await connect({
    databaseUrl: config.databaseUrl,
    duckdbPath: config.duckdbPath,
  });
  const runner: HouseholdTransactionQueryRunner = {
    async query(sql, params) {
      const client = await data.acquire();
      try {
        return await client.query(sql, [...params]);
      } finally {
        client.release();
      }
    },
  };
  const snapshotRunner = {
    ...runner,
    async readSnapshot<T>(
      operation: (transactionRunner: HouseholdTransactionQueryRunner) => Promise<T>,
    ): Promise<T> {
      const client = await data.acquire();
      let transactionStarted = false;
      try {
        await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
        transactionStarted = true;
        const transactionRunner: HouseholdTransactionQueryRunner = {
          async query(sql, params) {
            return await client.query(sql, [...params]);
          },
        };
        const result = await operation(transactionRunner);
        await client.query("COMMIT");
        return result;
      } catch (error) {
        if (transactionStarted) await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },
  };

  const { server, registry } = buildServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
    audit,
    extraTools: createPengeTools({ runner: snapshotRunner, vaultRoot: config.vaultRoot }),
  });
  assertSourceCatalogCoverage();
  assertRegisteredToolAllowlist(registry.list().map((tool) => tool.name));

  const transport = new StdioServerTransport();
  await server.connect(transport);

  const shutdown = async (): Promise<void> => {
    try {
      await server.close();
    } finally {
      await data.close();
      await audit.close();
    }
  };

  process.on("SIGINT", () => {
    void shutdown().then(() => process.exit(0));
  });
  process.on("SIGTERM", () => {
    void shutdown().then(() => process.exit(0));
  });
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
