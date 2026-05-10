import { z } from "zod";
import type { ToolDefinition } from "../registry.js";

const InputSchema = z.object({}).strict();
const OutputSchema = z.object({
  serverName: z.string(),
  serverVersion: z.string(),
  tools: z.array(z.string()),
  ts: z.string(),
});

type Output = z.infer<typeof OutputSchema>;

export function metaTool(
  getToolNames: () => readonly string[],
): ToolDefinition<z.infer<typeof InputSchema>, Output> {
  return {
    name: "_meta",
    description:
      "Health-check tool. Returns server identity, the list of registered tool names and a UTC timestamp.",
    inputSchema: InputSchema,
    outputSchema: OutputSchema,
    handler(_args, ctx) {
      return {
        serverName: ctx.serverName,
        serverVersion: ctx.serverVersion,
        tools: [...getToolNames()],
        ts: new Date().toISOString(),
      };
    },
  };
}
