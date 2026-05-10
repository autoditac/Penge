import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { zodToJsonSchema } from "zod-to-json-schema";
import { z } from "zod";

import type { AuditLogger } from "./audit.js";
import { ToolRegistry, type ToolContext, type ToolDefinition } from "./registry.js";
import { metaTool } from "./tools/meta.js";

export interface BuildServerOptions {
  name: string;
  version: string;
  audit: AuditLogger;
  /** Optionally register additional tools after the built-in `_meta` tool. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  extraTools?: readonly ToolDefinition<any, any>[];
}

export interface BuiltServer {
  server: Server;
  registry: ToolRegistry;
}

class ToolInputError extends Error {
  override readonly name = "ToolInputError";
  readonly code = "tool/input_invalid";
}

class ToolUnknownError extends Error {
  override readonly name = "ToolUnknownError";
  readonly code = "tool/unknown";
}

export function buildServer(opts: BuildServerOptions): BuiltServer {
  const registry = new ToolRegistry();
  const ctx: ToolContext = { serverName: opts.name, serverVersion: opts.version };

  registry.register(metaTool(() => registry.list().map((t) => t.name)));
  for (const tool of opts.extraTools ?? []) {
    registry.register(tool);
  }

  const server = new Server(
    { name: opts.name, version: opts.version },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, () => {
    const tools: Tool[] = registry.list().map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: zodToJsonSchema(tool.inputSchema, {
        target: "openApi3",
        $refStrategy: "none",
      }) as Tool["inputSchema"],
    }));
    return { tools };
  });

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const startedAt = Date.now();
    const name = req.params.name;
    const rawArgs = req.params.arguments ?? {};
    const tool = registry.get(name);
    if (!tool) {
      const err = new ToolUnknownError(`unknown tool: ${name}`);
      opts.audit.record({
        tool: name,
        args: rawArgs,
        status: "error",
        durationMs: Date.now() - startedAt,
        error: err.message,
      });
      throw err;
    }

    let parsedArgs: unknown;
    try {
      parsedArgs = tool.inputSchema.parse(rawArgs);
    } catch (cause) {
      const message =
        cause instanceof z.ZodError ? cause.issues.map((i) => i.message).join("; ") : String(cause);
      const err = new ToolInputError(`invalid arguments for ${name}: ${message}`);
      opts.audit.record({
        tool: name,
        args: rawArgs,
        status: "error",
        durationMs: Date.now() - startedAt,
        error: err.message,
      });
      throw err;
    }

    try {
      const result = await tool.handler(parsedArgs, ctx);
      const validated = tool.outputSchema.parse(result);
      opts.audit.record({
        tool: name,
        args: rawArgs,
        status: "ok",
        durationMs: Date.now() - startedAt,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(validated) }],
      };
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      opts.audit.record({
        tool: name,
        args: rawArgs,
        status: "error",
        durationMs: Date.now() - startedAt,
        error: message,
      });
      throw cause;
    }
  });

  return { server, registry };
}
