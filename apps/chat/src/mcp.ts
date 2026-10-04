import type { MCPStdioServerConfig } from "@github/copilot-sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { z } from "zod/v3";

import {
  MCP_SOURCE_ALLOWLIST,
  MCP_TOOL_ALLOWLIST,
  MCP_TOOL_CONTRACT_VERSION,
  type ChatConfig,
} from "./config.js";
import { ToolPolicyError } from "./security.js";

export const McpToolNameSchema = z.enum(MCP_TOOL_ALLOWLIST);
export const McpSourceNameSchema = z.enum(MCP_SOURCE_ALLOWLIST);

export type McpToolName = z.infer<typeof McpToolNameSchema>;
export type McpSourceName = z.infer<typeof McpSourceNameSchema>;

const DENIED_NAME_PARTS = [
  "shell",
  "filesystem",
  "browser",
  "web",
  "sql",
  "exec",
  "write",
  "delete",
  "mutation",
] as const;

export function assertMcpToolAllowed(toolName: string): asserts toolName is McpToolName {
  const normalized = toolName.trim().toLowerCase();
  if (DENIED_NAME_PARTS.some((part) => normalized.includes(part))) {
    throw new ToolPolicyError(`tool ${toolName} is denied by policy`);
  }
  if (!MCP_TOOL_ALLOWLIST.some((allowed) => allowed === normalized)) {
    throw new ToolPolicyError(`tool ${toolName} is not in contract ${MCP_TOOL_CONTRACT_VERSION}`);
  }
}

export function assertMcpSourceAllowed(sourceName: string): asserts sourceName is McpSourceName {
  if (!MCP_SOURCE_ALLOWLIST.some((allowed) => allowed === sourceName)) {
    throw new ToolPolicyError(`source ${sourceName} is not in the MCP source allowlist`);
  }
}

export function buildMcpServerConfig(config: ChatConfig): MCPStdioServerConfig {
  return {
    type: "stdio",
    command: config.mcpCommand,
    args: [...config.mcpArgs],
    workingDirectory: config.mcpWorkingDirectory,
    tools: [...MCP_TOOL_ALLOWLIST],
    timeout: config.requestTimeoutMs,
    env: {
      PATH: process.env.PATH ?? "",
      PENGE_DB_URL: config.mcpDatabaseUrl,
      PENGE_DUCKDB_PATH: config.mcpDuckdbPath,
      PENGE_VAULT_ROOT: config.mcpVaultRoot,
      PENGE_MCP_LOG_DIR: config.mcpLogDir,
    },
  };
}

export async function verifyMcpServerContract(config: ChatConfig): Promise<void> {
  const server = buildMcpServerConfig(config);
  const transport = new StdioClientTransport({
    command: server.command,
    args: server.args ?? [],
    cwd: server.workingDirectory ?? process.cwd(),
    env: server.env ?? {},
  });
  const client = new Client(
    { name: "penge-chat-contract-check", version: "0.0.0" },
    { capabilities: {} },
  );
  try {
    await client.connect(transport);
    const response = await client.listTools();
    const available = new Set(response.tools.map((tool) => tool.name));
    const missing = MCP_TOOL_ALLOWLIST.filter((tool) => !available.has(tool));
    if (missing.length > 0) {
      throw new ToolPolicyError(
        `MCP contract ${MCP_TOOL_CONTRACT_VERSION} is missing tools: ${missing.join(", ")}`,
      );
    }
  } finally {
    await client.close().catch(() => undefined);
    await transport.close().catch(() => undefined);
  }
}
