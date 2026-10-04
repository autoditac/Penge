import {
  ToolSet,
  type CopilotClientOptions,
  type GitHubTokenProvider,
  type ModelInfo,
  type SessionConfig,
} from "@github/copilot-sdk";
import { z } from "zod/v3";

export const hydraFusionModel = "hydrafusion" as const;
export const pengeMcpServerName = "penge" as const;
export const chatToolContractVersion = "issue-345-v1-provisional" as const;
export const pengeMcpTools = [
  "query_net_worth",
  "query_cashflow",
  "query_household_report",
  "run_scenario",
  "answer_planning_question",
  "search_documents",
  "suggest_import_mapping",
  "compute_tax_year",
] as const;
export const blockedToolSources = ["builtin:*", "custom:*"] as const;

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
  toolContractVersion: typeof chatToolContractVersion;
  client: CopilotClientOptions;
  session: SessionConfig;
}

function sdkMcpToolName(tool: (typeof pengeMcpTools)[number]): string {
  return `${pengeMcpServerName}-${tool}`;
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
  baseDirectory: string;
  workingDirectory: string;
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
  for (const tool of pengeMcpTools) {
    availableTools.addMcp(sdkMcpToolName(tool));
  }

  const excludedTools = new ToolSet().addBuiltIn("*").addCustom("*");

  return {
    toolContractVersion: chatToolContractVersion,
    client: {
      mode: "empty",
      baseDirectory: options.baseDirectory,
      workingDirectory: options.workingDirectory,
      useLoggedInUser: false,
      logLevel: "error",
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
          tools: [...pengeMcpTools],
        },
      },
    },
  };
}

export function validateSyntheticCopilotStream(events: readonly unknown[]): CopilotStreamEvent[] {
  return events.map((event) => CopilotStreamEventSchema.parse(event));
}
