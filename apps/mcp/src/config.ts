import { z } from "zod/v3";

import { PengeError } from "./errors.js";

const PseudonymousIdSchema = z
  .string()
  .min(8)
  .max(64)
  .regex(/^[a-z0-9][a-z0-9_-]+$/i);

export const ConfigSchema = z.object({
  databaseUrl: z.string().url(),
  duckdbPath: z.string().min(1),
  logDir: z.string().min(1),
  vaultRoot: z.string().min(1),
  actorId: PseudonymousIdSchema.optional(),
  sessionId: PseudonymousIdSchema.optional(),
});

export type Config = z.infer<typeof ConfigSchema>;

export class ConfigError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "config/invalid", options);
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = ConfigSchema.safeParse({
    databaseUrl: env.PENGE_DB_URL,
    duckdbPath: env.PENGE_DUCKDB_PATH,
    logDir: env.PENGE_MCP_LOG_DIR ?? "logs/mcp",
    vaultRoot: env.PENGE_VAULT_ROOT ?? "data/vault",
    actorId: env.PENGE_MCP_ACTOR_ID,
    sessionId: env.PENGE_MCP_SESSION_ID,
  });
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new ConfigError(`invalid MCP config: ${issues}`);
  }
  return parsed.data;
}
