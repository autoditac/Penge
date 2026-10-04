import { closeSync, constants, fstatSync, openSync, readFileSync } from "node:fs";

import { z } from "zod/v3";

import { PengeError } from "./errors.js";

const ULID = "[0-9A-HJKMNP-TV-Z]{26}";
const ActorIdSchema = z.string().regex(new RegExp(`^actor_${ULID}$`));
const SessionIdSchema = z.string().regex(new RegExp(`^session_${ULID}$`));
const MAX_SECRET_FILE_BYTES = 16 * 1024;

export const ConfigSchema = z.object({
  databaseUrl: z.string().url(),
  duckdbPath: z.string().min(1),
  logDir: z.string().min(1),
  vaultRoot: z.string().min(1),
  actorId: ActorIdSchema.optional(),
  sessionId: SessionIdSchema.optional(),
});

export type Config = z.infer<typeof ConfigSchema>;

export class ConfigError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "config/invalid", options);
  }
}

function databaseUrl(env: NodeJS.ProcessEnv): string | undefined {
  const hasDirect = env.PENGE_DB_URL !== undefined;
  const hasFile = env.PENGE_DB_URL_FILE !== undefined;
  if (hasDirect && hasFile) {
    throw new ConfigError("PENGE_DB_URL and PENGE_DB_URL_FILE are mutually exclusive");
  }
  if (!hasFile) return env.PENGE_DB_URL;

  let file: number | undefined;
  try {
    file = openSync(env.PENGE_DB_URL_FILE!, constants.O_RDONLY | constants.O_NOFOLLOW);
    const metadata = fstatSync(file);
    if (!metadata.isFile()) {
      throw new ConfigError("PENGE_DB_URL_FILE must reference a regular file");
    }
    const currentUserId = process.getuid?.();
    if (currentUserId === undefined || metadata.uid !== currentUserId) {
      throw new ConfigError("PENGE_DB_URL_FILE must be owned by the MCP process user");
    }
    if ((metadata.mode & 0o077) !== 0 || (metadata.mode & 0o400) === 0) {
      throw new ConfigError("PENGE_DB_URL_FILE must be owner-readable and inaccessible to others");
    }
    if (metadata.size > MAX_SECRET_FILE_BYTES) {
      throw new ConfigError("PENGE_DB_URL_FILE exceeds the 16 KiB limit");
    }
    return readFileSync(file, "utf8").trim();
  } catch (cause) {
    if (cause instanceof ConfigError) throw cause;
    throw new ConfigError("PENGE_DB_URL_FILE could not be read securely", { cause });
  } finally {
    if (file !== undefined) closeSync(file);
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = ConfigSchema.safeParse({
    databaseUrl: databaseUrl(env),
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
