import { z } from "zod";

export const ConfigSchema = z.object({
  databaseUrl: z.string().url(),
  duckdbPath: z.string().min(1),
  logDir: z.string().min(1),
  vaultRoot: z.string().min(1),
});

export type Config = z.infer<typeof ConfigSchema>;

export class ConfigError extends Error {
  override readonly name = "ConfigError";
  readonly code = "config/invalid";
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = ConfigSchema.safeParse({
    databaseUrl: env.PENGE_DB_URL,
    duckdbPath: env.PENGE_DUCKDB_PATH,
    logDir: env.PENGE_MCP_LOG_DIR ?? "logs/mcp",
    vaultRoot: env.PENGE_VAULT_ROOT ?? "data/vault",
  });
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new ConfigError(`invalid MCP config: ${issues}`);
  }
  return parsed.data;
}
