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

const SERVER_NAME = "penge-mcp";
const SERVER_VERSION = "0.0.0";

async function main(): Promise<void> {
  const config = loadConfig();
  const audit = createAuditLogger({ logDir: config.logDir });
  const data = await connect({
    databaseUrl: config.databaseUrl,
    duckdbPath: config.duckdbPath,
  });
  const runner = {
    async query<R extends Record<string, unknown>>(
      sql: string,
      params: ReadonlyArray<unknown>,
    ): Promise<{ rows: R[] }> {
      const client = await data.acquire();
      try {
        return await client.query<R>(sql, [...params]);
      } finally {
        client.release();
      }
    },
  };

  const { server } = buildServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
    audit,
    extraTools: createPengeTools({ runner, vaultRoot: config.vaultRoot }),
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
