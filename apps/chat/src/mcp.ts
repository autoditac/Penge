import type { MCPStdioServerConfig } from "@github/copilot-sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { z } from "zod/v3";

import {
  MCP_SOURCE_ALLOWLIST,
  MCP_CHAT_TOOL_ALLOWLIST,
  MCP_TOOL_CONTRACT_VERSION,
  MCP_REGISTRATION_ALLOWLIST,
  type ChatConfig,
} from "./config.js";
import { ToolPolicyError } from "./security.js";

export const McpToolNameSchema = z.enum(MCP_CHAT_TOOL_ALLOWLIST);
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
  if (!MCP_CHAT_TOOL_ALLOWLIST.some((allowed) => allowed === normalized)) {
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
    tools: [...MCP_CHAT_TOOL_ALLOWLIST],
    timeout: config.requestTimeoutMs,
    env: {
      PATH: process.env.PATH ?? "",
      PENGE_DB_URL_FILE: config.mcpDatabaseUrlFile,
      PENGE_DUCKDB_PATH: config.mcpDuckdbPath,
      PENGE_VAULT_ROOT: config.mcpVaultRoot,
      PENGE_MCP_LOG_DIR: config.mcpLogDir,
    },
  };
}

function assertExactRegistrationSequence(
  actual: readonly string[],
  expected: readonly string[],
  label: string,
): void {
  const seen = new Set<string>();
  for (const name of actual) {
    if (seen.has(name)) {
      throw new ToolPolicyError(`${label} differs: duplicate=${name}`);
    }
    seen.add(name);
  }
  if (actual.length !== expected.length) {
    const missing = expected.filter((name) => !actual.includes(name));
    const unexpected = actual.filter((name) => !expected.includes(name));
    throw new ToolPolicyError(
      `${label} differs: missing=${missing.join(",") || "none"} unexpected=${unexpected.join(",") || "none"}`,
    );
  }
  for (let index = 0; index < actual.length; index += 1) {
    const name = actual[index];
    if (name === undefined) {
      throw new ToolPolicyError(`${label} differs: undefined entry at index ${index}`);
    }
    if (name !== expected[index]) {
      throw new ToolPolicyError(
        `${label} differs: expected[${index}]=${expected[index]} actual[${index}]=${name}`,
      );
    }
  }
}

export function assertExactMcpRegistration(
  tools: readonly { name: string; outputSchema?: unknown }[],
): void {
  const expected = [...MCP_REGISTRATION_ALLOWLIST] as string[];
  const available = tools.map((tool) => tool.name);
  assertExactRegistrationSequence(available, expected, `MCP contract ${MCP_TOOL_CONTRACT_VERSION}`);
  const missingOutputSchema = tools
    .filter((tool) => expected.includes(tool.name) && tool.outputSchema === undefined)
    .map((tool) => tool.name);
  if (missingOutputSchema.length > 0) {
    throw new ToolPolicyError(
      `MCP contract ${MCP_TOOL_CONTRACT_VERSION} differs: missingOutputSchema=${missingOutputSchema.join(",") || "none"}`,
    );
  }
}

export function assertExactToolAllowlist(toolAllowlist: unknown): void {
  if (!Array.isArray(toolAllowlist) || !toolAllowlist.every((name) => typeof name === "string")) {
    throw new ToolPolicyError(
      "get_source_coverage structuredContent has missing or malformed tool_allowlist",
    );
  }
  assertExactRegistrationSequence(
    toolAllowlist,
    [...MCP_REGISTRATION_ALLOWLIST],
    "get_source_coverage tool_allowlist",
  );
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
    assertExactMcpRegistration(response.tools);
  } finally {
    await client.close().catch(() => undefined);
    await transport.close().catch(() => undefined);
  }
}
