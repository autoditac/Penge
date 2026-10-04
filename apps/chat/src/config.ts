import { z } from "zod/v3";
import { readFileSync, statSync } from "node:fs";

import { ChatConfigError } from "./errors.js";

export const HYDRAFUSION_MODEL = "hydrafusion" as const;
export const MCP_TOOL_CONTRACT_VERSION = "issue-344-v1" as const;

export const MCP_CHAT_TOOL_ALLOWLIST = [
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "run_scenario",
  "answer_planning_question",
  "search_documents",
  "suggest_import_mapping",
  "compute_tax_year",
  "get_source_coverage",
  "search_household_transactions",
  "get_household_transaction_detail",
  "get_household_taxonomy_summary",
  "get_household_rule_summary",
  "get_household_merchant_summary",
  "get_merchant_reference_status",
  "search_merchant_reference",
] as const;

export const MCP_REGISTRATION_ALLOWLIST = ["_meta", ...MCP_CHAT_TOOL_ALLOWLIST] as const;

export const MCP_SOURCE_ALLOWLIST = [
  "gls",
  "ebank",
  "lunar",
  "enable_banking",
  "nordnet",
  "pfa",
  "growney",
  "ecb_fx",
  "manual_facts",
  "household_classification",
  "paypal",
  "nsi_merchant_reference",
] as const;

export const OAUTH_TABLE_ALLOWLIST = [
  "chat_oauth_state",
  "chat_oauth_link",
  "chat_audit_event",
] as const;

export function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, "");
  return normalized === "127.0.0.1" || normalized === "localhost" || normalized === "::1";
}

const Base64KeySchema = z
  .string()
  .transform((value) => Buffer.from(value, "base64"))
  .refine((value) => value.length === 32, "must decode to exactly 32 bytes");

const KeyringFileSchema = z
  .object({
    currentKeyId: z.string().regex(/^[a-zA-Z0-9._-]{1,64}$/),
    keys: z.record(z.string().regex(/^[a-zA-Z0-9._-]{1,64}$/), Base64KeySchema),
  })
  .strict()
  .refine((value) => value.keys[value.currentKeyId] !== undefined, {
    message: "currentKeyId must exist in keys",
  });

export const ChatConfigSchema = z
  .object({
    httpHost: z.string().refine(isLoopbackHost, "must be a loopback host"),
    httpPort: z.number().int().positive().max(65535),
    publicApiBase: z.string().url(),
    publicAppOrigin: z.string().url(),
    trustedProxyIssuer: z.string().min(1),
    identityPepper: z.string().min(32),
    proxySharedSecret: z.string().min(32),
    tokenEncryptionKeyring: KeyringFileSchema,
    githubClientId: z.string().min(1),
    githubClientSecret: z.string().min(1),
    githubOAuthAuthorizeUrl: z.string().url(),
    githubOAuthTokenUrl: z.string().url(),
    githubApiUrl: z.string().url(),
    model: z.literal(HYDRAFUSION_MODEL),
    fallbackModel: z.undefined(),
    productionEnabled: z.boolean(),
    mcpToolContractVersion: z.literal(MCP_TOOL_CONTRACT_VERSION),
    mcpCommand: z.string().min(1),
    mcpArgs: z.array(z.string().min(1)).min(1),
    mcpWorkingDirectory: z.string().min(1),
    mcpDatabaseUrlFile: z.string().min(1),
    mcpDuckdbPath: z.string().min(1),
    mcpVaultRoot: z.string().min(1),
    mcpLogDir: z.string().min(1),
    databaseUrl: z.string().url(),
    databaseRole: z.literal("penge_chat_oauth"),
    copilotBaseDirectory: z.string().min(1),
    requestTimeoutMs: z
      .number()
      .int()
      .positive()
      .max(10 * 60_000),
    idleTimeoutMs: z
      .number()
      .int()
      .positive()
      .max(60 * 60_000),
    httpRequestTimeoutMs: z.number().int().positive().max(60_000),
    maxConcurrentSessions: z.number().int().positive().max(16),
    maxConcurrentSessionsPerActor: z.number().int().positive().max(4),
  })
  .superRefine((config, context) => {
    for (const [path, value] of [
      ["publicApiBase", config.publicApiBase],
      ["publicAppOrigin", config.publicAppOrigin],
    ] as const) {
      const publicUrl = new URL(value);
      if (publicUrl.protocol !== "https:" && !isLoopbackHost(publicUrl.hostname)) {
        context.addIssue({
          code: "custom",
          path: [path],
          message: "must use HTTPS unless it is a loopback development origin",
        });
      }
    }
    const appUrl = new URL(config.publicAppOrigin);
    if (appUrl.pathname !== "/" || appUrl.search !== "" || appUrl.hash !== "") {
      context.addIssue({
        code: "custom",
        path: ["publicAppOrigin"],
        message: "must contain only the external app origin",
      });
    }
    if (!config.publicApiBase.endsWith("/")) {
      context.addIssue({
        code: "custom",
        path: ["publicApiBase"],
        message: "must end with a slash so proxy prefixes are preserved",
      });
    }
    if (config.maxConcurrentSessionsPerActor > config.maxConcurrentSessions) {
      context.addIssue({
        code: "custom",
        path: ["maxConcurrentSessionsPerActor"],
        message: "must not exceed maxConcurrentSessions",
      });
    }
  });

export type ChatConfig = z.infer<typeof ChatConfigSchema>;

function required(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (value === undefined || value.trim() === "") {
    throw new ChatConfigError(`missing required environment variable: ${name}`);
  }
  return value;
}

function secretFilePath(env: NodeJS.ProcessEnv, name: string): string {
  const path = required(env, `${name}_FILE`);
  const stat = statSync(path);
  const processUid = process.getuid?.();
  if (!stat.isFile() || stat.size < 1 || stat.size > 65_536) {
    throw new ChatConfigError(`${name}_FILE must be a non-empty regular file under 64 KiB`);
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new ChatConfigError(`${name}_FILE must not be group- or world-accessible`);
  }
  if (processUid !== undefined && stat.uid !== processUid) {
    throw new ChatConfigError(`${name}_FILE must be owned by the chat process user`);
  }
  return path;
}

function secretFile(env: NodeJS.ProcessEnv, name: string): string {
  return readFileSync(secretFilePath(env, name), "utf8").trim();
}

function optionalFlag(env: NodeJS.ProcessEnv, name: string): boolean {
  const value = env[name];
  if (value === undefined || value === "0") {
    return false;
  }
  if (value === "1") {
    return true;
  }
  throw new ChatConfigError(`${name} must be 0, 1, or unset`);
}

function keyringFile(env: NodeJS.ProcessEnv): unknown {
  try {
    return JSON.parse(secretFile(env, "PENGE_CHAT_TOKEN_KEYRING")) as unknown;
  } catch (error) {
    if (error instanceof ChatConfigError) {
      throw error;
    }
    throw new ChatConfigError("PENGE_CHAT_TOKEN_KEYRING_FILE must contain valid JSON");
  }
}

function integer(env: NodeJS.ProcessEnv, name: string, fallback: number): number {
  const value = env[name];
  if (value === undefined) {
    return fallback;
  }
  if (!/^\d+$/.test(value)) {
    throw new ChatConfigError(`${name} must be an integer`);
  }
  return Number(value);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ChatConfig {
  const model = env.PENGE_CHAT_MODEL;
  if (model !== HYDRAFUSION_MODEL) {
    throw new ChatConfigError(`PENGE_CHAT_MODEL must be exactly ${HYDRAFUSION_MODEL}`);
  }
  if (env.PENGE_CHAT_FALLBACK_MODEL !== undefined) {
    throw new ChatConfigError("PENGE_CHAT_FALLBACK_MODEL must be unset");
  }

  const raw = {
    httpHost: env.PENGE_CHAT_HTTP_HOST ?? "127.0.0.1",
    httpPort: integer(env, "PENGE_CHAT_HTTP_PORT", 3000),
    publicApiBase: required(env, "PENGE_CHAT_PUBLIC_API_BASE"),
    publicAppOrigin: required(env, "PENGE_CHAT_PUBLIC_APP_ORIGIN"),
    trustedProxyIssuer: required(env, "PENGE_CHAT_TRUSTED_PROXY_ISSUER"),
    identityPepper: secretFile(env, "PENGE_CHAT_IDENTITY_PEPPER"),
    proxySharedSecret: secretFile(env, "PENGE_CHAT_PROXY_SHARED_SECRET"),
    tokenEncryptionKeyring: keyringFile(env),
    githubClientId: required(env, "PENGE_CHAT_GITHUB_CLIENT_ID"),
    githubClientSecret: secretFile(env, "PENGE_CHAT_GITHUB_CLIENT_SECRET"),
    githubOAuthAuthorizeUrl:
      env.PENGE_CHAT_GITHUB_AUTHORIZE_URL ?? "https://github.com/login/oauth/authorize",
    githubOAuthTokenUrl:
      env.PENGE_CHAT_GITHUB_TOKEN_URL ?? "https://github.com/login/oauth/access_token",
    githubApiUrl: env.PENGE_CHAT_GITHUB_API_URL ?? "https://api.github.com",
    model,
    fallbackModel: undefined,
    productionEnabled: optionalFlag(env, "PENGE_CHAT_ENABLE_PRODUCTION"),
    mcpToolContractVersion: env.PENGE_CHAT_MCP_TOOL_CONTRACT_VERSION ?? MCP_TOOL_CONTRACT_VERSION,
    mcpCommand: env.PENGE_CHAT_MCP_COMMAND ?? "pnpm",
    mcpArgs: (env.PENGE_CHAT_MCP_ARGS ?? "--filter,@penge/mcp,start").split(","),
    mcpWorkingDirectory: required(env, "PENGE_CHAT_MCP_WORKING_DIRECTORY"),
    mcpDatabaseUrlFile: secretFilePath(env, "PENGE_DB_URL"),
    mcpDuckdbPath: required(env, "PENGE_CHAT_MCP_DUCKDB_PATH"),
    mcpVaultRoot: required(env, "PENGE_CHAT_MCP_VAULT_ROOT"),
    mcpLogDir: required(env, "PENGE_CHAT_MCP_LOG_DIR"),
    databaseUrl: secretFile(env, "PENGE_CHAT_DATABASE_URL"),
    databaseRole: env.PENGE_CHAT_DATABASE_ROLE ?? "penge_chat_oauth",
    copilotBaseDirectory: required(env, "PENGE_CHAT_COPILOT_BASE_DIRECTORY"),
    requestTimeoutMs: integer(env, "PENGE_CHAT_REQUEST_TIMEOUT_MS", 120_000),
    idleTimeoutMs: integer(env, "PENGE_CHAT_IDLE_TIMEOUT_MS", 180_000),
    httpRequestTimeoutMs: integer(env, "PENGE_CHAT_HTTP_REQUEST_TIMEOUT_MS", 15_000),
    maxConcurrentSessions: integer(env, "PENGE_CHAT_MAX_CONCURRENT_SESSIONS", 2),
    maxConcurrentSessionsPerActor: integer(env, "PENGE_CHAT_MAX_CONCURRENT_SESSIONS_PER_ACTOR", 1),
  };

  const parsed = ChatConfigSchema.safeParse(raw);
  if (!parsed.success) {
    const detail = parsed.error.issues
      .map((issue) => `${issue.path.join(".") || "config"}: ${issue.message}`)
      .join("; ");
    throw new ChatConfigError(`invalid chat config: ${detail}`);
  }
  return parsed.data;
}
