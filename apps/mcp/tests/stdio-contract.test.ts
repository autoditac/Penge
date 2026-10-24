import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const fixturePath = fileURLToPath(new URL("fixtures/stdio-server.ts", import.meta.url));
const expectedTools = [
  "_meta",
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "compute_tax_year",
  "run_scenario",
  "answer_planning_question",
  "search_documents",
  "suggest_import_mapping",
];

describe("MCP stdio tools/list contract", () => {
  it("publishes every real Penge tool as read-only", async () => {
    const transport = new StdioClientTransport({
      command: "pnpm",
      args: ["exec", "tsx", fixturePath],
      cwd: packageRoot,
      stderr: "pipe",
    });
    const client = new Client(
      { name: "penge-mcp-stdio-contract-client", version: "0.0.0-test" },
      { capabilities: {} },
    );

    try {
      await client.connect(transport);
      const list = await client.listTools();

      expect(list.tools.map((tool) => tool.name)).toEqual(expectedTools);
      expect(list.tools.every((tool) => tool.annotations?.readOnlyHint === true)).toBe(true);
    } finally {
      await client.close();
    }
  }, 60_000);
});
