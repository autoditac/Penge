import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import type { AuditLogger } from "../../src/audit.js";
import { buildServer } from "../../src/server.js";
import { createPengeTools, type PengeQueryRunner } from "../../src/tools/index.js";

const audit: AuditLogger = {
  record() {
    // The contract probe lists tools without invoking them.
  },
  async close() {
    // No resources are allocated by the contract probe.
  },
};

const runner: PengeQueryRunner = {
  async query<R extends Record<string, unknown>>(): Promise<{ rows: R[] }> {
    return { rows: [] };
  },
};

const { server } = buildServer({
  name: "penge-mcp-stdio-contract-test",
  version: "0.0.0-test",
  audit,
  extraTools: createPengeTools({
    runner,
    vaultRoot: "tests/fixtures/vault",
  }),
});

await server.connect(new StdioServerTransport());
