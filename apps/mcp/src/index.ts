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
import { computeTaxYearTool } from "./tools/computeTaxYear.js";
import { queryCashflowTool } from "./tools/queryCashflow.js";
import { queryNetWorthTool } from "./tools/queryNetWorth.js";
import { runScenarioTool } from "./tools/runScenario.js";
import { searchDocumentsTool } from "./tools/searchDocuments.js";

const SERVER_NAME = "penge-mcp";
const SERVER_VERSION = "0.0.0";

async function main(): Promise<void> {
  const config = loadConfig();
  const audit = createAuditLogger({ logDir: config.logDir });
  const data = await connect({
    databaseUrl: config.databaseUrl,
    duckdbPath: config.duckdbPath,
  });

  const { server } = buildServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
    audit,
    extraTools: [
      queryNetWorthTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      queryCashflowTool({
        runner: {
          async query(sql, params) {
            const client = await data.acquire();
            try {
              return await client.query(sql, [...params]);
            } finally {
              client.release();
            }
          },
        },
      }),
      computeTaxYearTool(),
      runScenarioTool(),
      searchDocumentsTool({ vaultRoot: config.vaultRoot }),
    ],
  });

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
