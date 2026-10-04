import { z } from "zod/v3";

export class PengeError extends Error {
  code: string;

  constructor(message = "penge error") {
    super(message);
    this.name = "PengeError";
    this.code = "penge/error";
  }
}

export class ChatConfigError extends PengeError {
  override code: string;

  constructor(message = "invalid chat config") {
    super(message);
    this.name = "ChatConfigError";
    this.code = "chat/config";
  }
}

export function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(normalized);
}

export function parseInteger(value: string | undefined, fallback: number): number {
  if (value === undefined || value.trim() === "") {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return parsed;
}

export const DEFAULT_MCP_ALLOWLIST = [
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "run_scenario",
  "search_documents",
  "compute_tax_year",
] as const;

export const DEFAULT_ALLOWED_DB_TABLES = [
  "chat_oauth_state",
  "chat_oauth_link",
  "chat_oauth_nonce",
] as const;

export function normalizeMcpAllowlist(raw: string | undefined): string[] {
  const values = (raw ?? DEFAULT_MCP_ALLOWLIST.join(",")).split(",");
  const normalized = values.map((tool) => tool.trim()).filter(Boolean);
  return [...new Set(normalized)];
}

export function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, "");
  return ["127.0.0.1", "localhost", "::1"].includes(normalized);
}

export function assertLoopbackOnlyConfig(config: {
  httpHost: string;
  loopbackOnly: boolean;
  oauth2ProxyIssuer: string;
}): void {
  if (!config.loopbackOnly) {
    throw new ChatConfigError("loopbackOnly must be enabled for the chat runtime");
  }
  if (!isLoopbackHost(config.httpHost)) {
    throw new ChatConfigError("httpHost must be loopback-only when loopbackOnly=true");
  }

  const issuer = new URL(config.oauth2ProxyIssuer);
  if (!isLoopbackHost(issuer.hostname)) {
    throw new ChatConfigError("oauth2ProxyIssuer must resolve to a loopback-only local address");
  }
}

const AllowedDbTablesSchema = z.array(z.enum(DEFAULT_ALLOWED_DB_TABLES)).nonempty();

export const ChatConfigSchema = z.object({
  httpHost: z
    .string()
    .min(1)
    .refine((value) => isLoopbackHost(value), {
      message: "httpHost must be localhost or a loopback address",
    }),
  httpPort: z.number().int().positive().max(65535),
  loopbackOnly: z.literal(true),
  sessionSecret: z.string().min(32),
  tokenEncryptionKey: z.string().min(32),
  oauth2ProxyIssuer: z
    .string()
    .url()
    .refine((value) => isLoopbackHost(new URL(value).hostname), {
      message: "oauth2ProxyIssuer must be a loopback-only URL",
    }),
  githubClientId: z.string().min(1),
  githubClientSecret: z.string().min(1),
  githubAppId: z.string().min(1),
  githubAppPrivateKey: z.string().min(1),
  model: z.literal("hydrafusion"),
  disableFallback: z.literal(true),
  mcpAllowlist: z.array(z.string().min(1)).nonempty(),
  dbUrl: z.string().url(),
  dbRole: z
    .string()
    .min(1)
    .refine((value) => !value.toLowerCase().includes("finance"), {
      message: "dbRole must not grant finance-table access",
    }),
  dbAllowedTables: AllowedDbTablesSchema,
  idleTimeoutMs: z.number().int().positive(),
  noTranscriptPersistence: z.literal(true),
});

export type ChatConfig = z.infer<typeof ChatConfigSchema>;

function requireEnv(env: NodeJS.ProcessEnv, key: string): string {
  const value = env[key];
  if (value === undefined || value.trim() === "") {
    throw new ChatConfigError(`missing required environment variable: ${key}`);
  }
  return value;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ChatConfig {
  const allowlist = normalizeMcpAllowlist(env.PENGE_CHAT_MCP_ALLOWLIST);

  const raw = {
    httpHost: env.PENGE_CHAT_HTTP_HOST ?? "127.0.0.1",
    httpPort: parseInteger(env.PENGE_CHAT_HTTP_PORT, 3000),
    loopbackOnly: parseBoolean(env.PENGE_CHAT_LOOPBACK_ONLY, true),
    sessionSecret: env.PENGE_CHAT_SESSION_SECRET ?? requireEnv(env, "PENGE_CHAT_SESSION_SECRET"),
    tokenEncryptionKey:
      env.PENGE_CHAT_TOKEN_ENCRYPTION_KEY ?? requireEnv(env, "PENGE_CHAT_TOKEN_ENCRYPTION_KEY"),
    oauth2ProxyIssuer: env.PENGE_CHAT_GOOGLE_PROXY_ISSUER ?? "http://127.0.0.1:4180",
    githubClientId:
      env.PENGE_CHAT_GITHUB_CLIENT_ID ?? requireEnv(env, "PENGE_CHAT_GITHUB_CLIENT_ID"),
    githubClientSecret:
      env.PENGE_CHAT_GITHUB_CLIENT_SECRET ?? requireEnv(env, "PENGE_CHAT_GITHUB_CLIENT_SECRET"),
    githubAppId: env.PENGE_CHAT_GITHUB_APP_ID ?? requireEnv(env, "PENGE_CHAT_GITHUB_APP_ID"),
    githubAppPrivateKey:
      env.PENGE_CHAT_GITHUB_APP_PRIVATE_KEY ?? requireEnv(env, "PENGE_CHAT_GITHUB_APP_PRIVATE_KEY"),
    model: (env.PENGE_CHAT_MODEL ?? "hydrafusion") as "hydrafusion",
    disableFallback: true,
    mcpAllowlist: allowlist,
    dbUrl: env.PENGE_CHAT_DB_URL ?? requireEnv(env, "PENGE_CHAT_DB_URL"),
    dbRole: env.PENGE_CHAT_DB_ROLE ?? requireEnv(env, "PENGE_CHAT_DB_ROLE"),
    dbAllowedTables: normalizeMcpAllowlist(
      env.PENGE_CHAT_DB_ALLOWED_TABLES ?? DEFAULT_ALLOWED_DB_TABLES.join(","),
    ),
    idleTimeoutMs: parseInteger(env.PENGE_CHAT_IDLE_TIMEOUT_MS, 180_000),
    noTranscriptPersistence: true,
  };

  const parsed = ChatConfigSchema.safeParse(raw);
  if (!parsed.success) {
    const detail = parsed.error.issues
      .map((issue) => `${issue.path.join(".") || "config"}: ${issue.message}`)
      .join("; ");
    throw new ChatConfigError(`invalid chat config: ${detail}`);
  }

  assertLoopbackOnlyConfig(parsed.data);
  return parsed.data;
}
