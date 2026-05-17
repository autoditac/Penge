import type { z } from "zod/v3";

export interface ToolContext {
  serverName: string;
  serverVersion: string;
}

/**
 * A registered tool. The runtime input/output schemas are the source of truth;
 * the JSON Schema sent over the wire is derived from them. The handler is
 * pure with respect to the context — no global state.
 */
export interface ToolDefinition<I = unknown, O = unknown> {
  name: string;
  description: string;
  inputSchema: z.ZodType<I, z.ZodTypeDef, unknown>;
  outputSchema: z.ZodType<O>;
  handler: (args: I, ctx: ToolContext) => Promise<O> | O;
}

export class ToolRegistry {
  readonly #tools = new Map<string, ToolDefinition>();

  register<I, O>(tool: ToolDefinition<I, O>): void {
    if (this.#tools.has(tool.name)) {
      throw new Error(`tool ${tool.name} already registered`);
    }
    this.#tools.set(tool.name, tool as ToolDefinition);
  }

  get(name: string): ToolDefinition | undefined {
    return this.#tools.get(name);
  }

  list(): readonly ToolDefinition[] {
    return [...this.#tools.values()];
  }
}
