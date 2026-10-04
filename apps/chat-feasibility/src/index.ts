import {
  ToolSet,
  type CopilotClientOptions,
  type GitHubTokenProvider,
  type ModelInfo,
  type SessionConfig,
} from "@github/copilot-sdk";
import { isAbsolute, relative, resolve } from "node:path";
import { z } from "zod/v3";

export const hydraFusionModel = "hydrafusion" as const;
export const pengeMcpServerName = "penge" as const;
export const implementedChatToolContractVersion = "issue-345-current-v1" as const;
export const plannedChatToolContractVersion = "issue-344-v1" as const;
export const implementedPengeMcpChatTools = [
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "run_scenario",
  "answer_planning_question",
  "search_documents",
  "suggest_import_mapping",
  "compute_tax_year",
] as const;
export const plannedPengeMcpChatTools = [
  ...implementedPengeMcpChatTools,
  "get_source_coverage",
  "search_household_transactions",
  "get_household_transaction_detail",
  "get_household_taxonomy_summary",
  "get_household_rule_summary",
  "get_household_merchant_summary",
  "get_merchant_reference_status",
  "search_merchant_reference",
] as const;
export const implementedPengeMcpRegisteredTools = [
  "_meta",
  ...implementedPengeMcpChatTools,
] as const;
export const plannedPengeMcpRegisteredTools = ["_meta", ...plannedPengeMcpChatTools] as const;
export const blockedToolSources = ["builtin:*", "custom:*"] as const;
export const runtimeEnvironmentKeys = [
  "PATH",
  "LANG",
  "LC_ALL",
  "TMPDIR",
  "SSL_CERT_FILE",
  "SSL_CERT_DIR",
  "NODE_EXTRA_CA_CERTS",
] as const;

const actorIdSchema = z.string().regex(/^actor_[a-z0-9]{16,64}$/);
const githubLoginSchema = z.string().regex(/^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,38})$/);

export class PengeError extends Error {
  override get name(): string {
    return "PengeError";
  }

  get code(): string {
    return "penge/error";
  }
}

export class ModelUnavailableError extends PengeError {
  override get name(): string {
    return "ModelUnavailableError";
  }

  override get code(): string {
    return "chat/model_unavailable";
  }
}

export class ChatFeatureDisabledError extends PengeError {
  override get name(): string {
    return "ChatFeatureDisabledError";
  }

  override get code(): string {
    return "chat/feature_disabled";
  }
}

export class UserCredentialScopeError extends PengeError {
  override get name(): string {
    return "UserCredentialScopeError";
  }

  override get code(): string {
    return "chat/credential_scope_invalid";
  }
}

export class SdkCleanupError extends PengeError {
  override get name(): string {
    return "SdkCleanupError";
  }

  override get code(): string {
    return "chat/sdk_cleanup_failed";
  }
}

export class McpContractUnavailableError extends PengeError {
  override get name(): string {
    return "McpContractUnavailableError";
  }

  override get code(): string {
    return "chat/mcp_contract_unavailable";
  }
}

export const ChatRuntimeConfigSchema = z.object({
  mode: z.literal("empty"),
  model: z.literal(hydraFusionModel),
  actorId: actorIdSchema,
  githubLogin: githubLoginSchema,
  productionEnabled: z.literal(true),
  entitlementVerifiedAt: z.string().datetime(),
  fallbackModel: z.undefined(),
});

export type ChatRuntimeConfig = z.infer<typeof ChatRuntimeConfigSchema>;

export const ActorEntitlementVerificationSchema = z.object({
  actorId: actorIdSchema,
  githubLogin: githubLoginSchema,
  model: z.literal(hydraFusionModel),
  verifiedAt: z.string().datetime(),
});

export type ActorEntitlementVerification = z.infer<typeof ActorEntitlementVerificationSchema>;

const CopilotEventMetadataSchema = z.object({
  id: z.string().uuid(),
  parentId: z.string().uuid().nullable(),
  timestamp: z.string().datetime(),
});

export const CopilotStreamEventSchema = z.discriminatedUnion("type", [
  CopilotEventMetadataSchema.extend({
    type: z.literal("assistant.message_delta"),
    ephemeral: z.literal(true),
    data: z.object({
      deltaContent: z.string(),
      messageId: z.string().min(1),
    }),
  }),
  CopilotEventMetadataSchema.extend({
    type: z.literal("tool.execution_start"),
    data: z.object({
      toolName: z.string().min(1),
      toolCallId: z.string().min(1),
      arguments: z.unknown().optional(),
      mcpServerName: z.string().optional(),
      mcpToolName: z.string().optional(),
    }),
  }),
  CopilotEventMetadataSchema.extend({
    type: z.literal("session.idle"),
    ephemeral: z.literal(true),
    data: z.object({
      aborted: z.boolean().optional(),
    }),
  }),
  CopilotEventMetadataSchema.extend({
    type: z.literal("session.error"),
    data: z.object({
      errorType: z.string().min(1),
      message: z.string().min(1),
    }),
  }),
]);

export type CopilotStreamEvent = z.infer<typeof CopilotStreamEventSchema>;

export interface UserScopedTokenProvider {
  actorId: string;
  githubLogin: string;
  acquire: GitHubTokenProvider;
}

export interface CopilotSdkProof {
  toolContractVersion: typeof implementedChatToolContractVersion;
  registeredMcpTools: typeof implementedPengeMcpRegisteredTools;
  chatExposedMcpTools: typeof implementedPengeMcpChatTools;
  client: CopilotClientOptions;
  session: SessionConfig;
}

const McpChildEnvironmentSchema = z
  .object({
    PATH: z.string().min(1),
    PENGE_DB_URL: z.string().url(),
    PENGE_DUCKDB_PATH: z.string().min(1),
    PENGE_MCP_LOG_DIR: z.string().min(1),
    PENGE_VAULT_ROOT: z.string().min(1),
  })
  .strict();

export type McpChildEnvironment = z.infer<typeof McpChildEnvironmentSchema>;

function sdkMcpToolName(tool: (typeof implementedPengeMcpChatTools)[number]): string {
  return `${pengeMcpServerName}-${tool}`;
}

export function deriveActorBaseDirectory(storageRoot: string, actorId: string): string {
  if (!isAbsolute(storageRoot)) {
    throw new UserCredentialScopeError("the trusted SDK storage root must be absolute");
  }
  const parsedActorId = actorIdSchema.parse(actorId);
  const trustedRoot = resolve(storageRoot);
  const actorDirectory = resolve(trustedRoot, parsedActorId);
  const ownershipPath = relative(trustedRoot, actorDirectory);
  if (ownershipPath === "" || ownershipPath.startsWith("..") || isAbsolute(ownershipPath)) {
    throw new UserCredentialScopeError(
      "the actor SDK directory must remain under the trusted root",
    );
  }
  return actorDirectory;
}

export function sanitizeRuntimeEnvironment(
  source: NodeJS.ProcessEnv,
): Record<string, string | undefined> {
  const path = z.string().min(1).parse(source.PATH);
  const sanitized: Record<string, string | undefined> = { PATH: path };
  for (const key of runtimeEnvironmentKeys.slice(1)) {
    if (source[key] !== undefined) {
      sanitized[key] = source[key];
    }
  }
  return sanitized;
}

export function sanitizeMcpEnvironment(source: unknown): McpChildEnvironment {
  return McpChildEnvironmentSchema.parse(source);
}

export function assertPlannedMcpContractAvailable(observedTools: readonly string[]): void {
  if (
    observedTools.length !== plannedPengeMcpRegisteredTools.length ||
    !plannedPengeMcpRegisteredTools.every((tool, index) => observedTools[index] === tool)
  ) {
    throw new McpContractUnavailableError(
      `${plannedChatToolContractVersion} requires independent stdio tools/list evidence`,
    );
  }
}

export function resolveChatRuntimeConfig(
  env: NodeJS.ProcessEnv,
  rawVerification: unknown,
): ChatRuntimeConfig {
  const requestedModel = env.PENGE_CHAT_MODEL;
  if (requestedModel !== hydraFusionModel) {
    throw new ModelUnavailableError(
      `PENGE_CHAT_MODEL must be exactly ${hydraFusionModel}; no fallback is supported`,
    );
  }
  if (env.PENGE_CHAT_FALLBACK_MODEL !== undefined) {
    throw new ModelUnavailableError("PENGE_CHAT_FALLBACK_MODEL must be unset");
  }
  if (env.PENGE_CHAT_ENABLE_PRODUCTION !== "1") {
    throw new ChatFeatureDisabledError("PENGE_CHAT_ENABLE_PRODUCTION must be 1");
  }

  const identity = z
    .object({
      actorId: actorIdSchema,
      githubLogin: githubLoginSchema,
    })
    .parse({
      actorId: env.PENGE_CHAT_ACTOR_ID,
      githubLogin: env.PENGE_CHAT_GITHUB_LOGIN,
    });
  const verification = ActorEntitlementVerificationSchema.parse(rawVerification);

  if (
    verification.actorId !== identity.actorId ||
    verification.githubLogin.toLowerCase() !== identity.githubLogin.toLowerCase()
  ) {
    throw new UserCredentialScopeError(
      "HydraFusion entitlement verification must match the current actor and linked GitHub identity",
    );
  }

  return ChatRuntimeConfigSchema.parse({
    mode: "empty",
    model: requestedModel,
    actorId: identity.actorId,
    githubLogin: identity.githubLogin,
    productionEnabled: true,
    entitlementVerifiedAt: verification.verifiedAt,
    fallbackModel: undefined,
  });
}

export function assertHydraFusionAvailable(models: readonly Pick<ModelInfo, "id">[]): void {
  if (!models.some((model) => model.id === hydraFusionModel)) {
    throw new ModelUnavailableError(
      `authenticated Copilot identity is not entitled to model ${hydraFusionModel}`,
    );
  }
}

export function assertSdkCleanupSucceeded(errors: readonly Error[]): void {
  if (errors.length > 0) {
    throw new SdkCleanupError(
      `Copilot SDK cleanup failed: ${errors.map((error) => error.message).join("; ")}`,
    );
  }
}

export function buildCopilotSdkProof(options: {
  runtime: ChatRuntimeConfig;
  tokenProvider: UserScopedTokenProvider;
  storageRoot: string;
  workingDirectory: string;
  ambientEnvironment: NodeJS.ProcessEnv;
  mcpEnvironment: unknown;
}): CopilotSdkProof {
  if (
    options.tokenProvider.actorId !== options.runtime.actorId ||
    options.tokenProvider.githubLogin.toLowerCase() !== options.runtime.githubLogin.toLowerCase()
  ) {
    throw new UserCredentialScopeError(
      "the GitHub token provider must belong to the current Penge actor and linked GitHub identity",
    );
  }

  const availableTools = new ToolSet();
  for (const tool of implementedPengeMcpChatTools) {
    availableTools.addMcp(sdkMcpToolName(tool));
  }

  const excludedTools = new ToolSet().addBuiltIn("*").addCustom("*");
  const baseDirectory = deriveActorBaseDirectory(options.storageRoot, options.runtime.actorId);

  return {
    toolContractVersion: implementedChatToolContractVersion,
    registeredMcpTools: implementedPengeMcpRegisteredTools,
    chatExposedMcpTools: implementedPengeMcpChatTools,
    client: {
      mode: "empty",
      baseDirectory,
      workingDirectory: options.workingDirectory,
      useLoggedInUser: false,
      logLevel: "error",
      env: sanitizeRuntimeEnvironment(options.ambientEnvironment),
    },
    session: {
      model: hydraFusionModel,
      allowedModels: [hydraFusionModel],
      streaming: true,
      enableSessionStore: false,
      enableConfigDiscovery: false,
      includedBuiltinSkills: [],
      requestCanvasRenderer: false,
      requestExtensions: false,
      mcpOAuthTokenStorage: "in-memory",
      gitHubTokenProvider: options.tokenProvider.acquire,
      availableTools,
      excludedTools,
      onPermissionRequest: () => ({
        kind: "reject",
        feedback: "Penge chat denies every ambient permission request",
      }),
      mcpServers: {
        [pengeMcpServerName]: {
          type: "stdio",
          command: "pnpm",
          args: ["--filter", "@penge/mcp", "start"],
          workingDirectory: options.workingDirectory,
          env: sanitizeMcpEnvironment(options.mcpEnvironment),
          tools: [...implementedPengeMcpChatTools],
        },
      },
    },
  };
}

export function validateSyntheticCopilotStream(events: readonly unknown[]): CopilotStreamEvent[] {
  return events.map((event) => CopilotStreamEventSchema.parse(event));
}
