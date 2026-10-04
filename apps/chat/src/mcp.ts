import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { z } from "zod/v3";

import { assertToolAllowed, createToolPolicy, type ToolExecutionPolicy } from "./security.js";

export const DEFAULT_MCP_ALLOWLIST = [
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "run_scenario",
  "search_documents",
  "compute_tax_year",
] as const;

export const McpRequestSchema = z.object({
  tool: z.string().min(1),
  arguments: z.record(z.unknown()).default({}),
});

export type McpRequest = z.infer<typeof McpRequestSchema>;

export type McpProcess = {
  client: Client;
  policy: ToolExecutionPolicy;
  close: () => Promise<void>;
};

export function createProcessLocalMcpClient(options: {
  command: string;
  args: readonly string[];
  cwd?: string;
  env?: Record<string, string | undefined>;
  allowlist?: readonly string[];
  sourceAllowlist?: readonly string[];
}): McpProcess {
  const policy = createToolPolicy(
    options.allowlist ?? [...DEFAULT_MCP_ALLOWLIST],
    options.sourceAllowlist ?? [],
  );
  const serverEnv: Record<string, string> = Object.fromEntries(
    Object.entries({ ...process.env, ...options.env }).flatMap(([key, value]) =>
      value === undefined ? [] : [[key, value]],
    ),
  );
  const transport = new StdioClientTransport({
    command: options.command,
    args: [...options.args],
    env: serverEnv,
    cwd: options.cwd ?? process.cwd(),
  });

  const client = new Client(
    { name: "penge-chat-local-mcp", version: "0.0.0" },
    {
      capabilities: {},
    },
  );

  return {
    client,
    policy,
    close: async () => {
      await client.close();
      await transport.close();
    },
  };
}

export async function callAllowedTool(
  client: Client,
  toolName: string,
  args: Record<string, unknown>,
  policy: ToolExecutionPolicy,
): Promise<unknown> {
  assertToolAllowed(toolName, policy);
  const parsed = McpRequestSchema.parse({ tool: toolName, arguments: args });
  return client.callTool({ name: parsed.tool, arguments: parsed.arguments });
}
