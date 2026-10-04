import { z } from "zod/v3";

export const hydraFusionModel = "hydrafusion" as const;
export const blockedAmbientTools = ["shell", "filesystem", "default"] as const;
export const localMcpAllowlist = [
  "penge.mcp.query_net_worth",
  "penge.mcp.query_cashflow",
  "penge.mcp.query_household_report",
  "penge.mcp.run_scenario",
  "penge.mcp.answer_planning_question",
  "penge.mcp.search_documents",
  "penge.mcp.suggest_import_mapping",
  "penge.mcp.compute_tax_year",
] as const;

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

export class SharedIdentityError extends PengeError {
  override get name(): string {
    return "SharedIdentityError";
  }

  override get code(): string {
    return "chat/identity_invalid";
  }
}

export const LocalStdioMcpPolicySchema = z.object({
  transport: z.literal("stdio"),
  mode: z.literal("empty"),
  allowlist: z.array(z.enum(localMcpAllowlist)).min(1),
  blockedAmbientTools: z.array(z.enum(blockedAmbientTools)).default([...blockedAmbientTools]),
});

export type LocalStdioMcpPolicy = z.infer<typeof LocalStdioMcpPolicySchema>;

export const ChatStreamEventSchema = z.discriminatedUnion("event", [
  z.object({
    event: z.literal("session_started"),
    sessionId: z.string().min(1),
    model: z.literal(hydraFusionModel),
    mode: z.literal("empty"),
    ts: z.string().datetime(),
  }),
  z.object({
    event: z.literal("content_delta"),
    sessionId: z.string().min(1),
    content: z.string(),
    ts: z.string().datetime(),
  }),
  z.object({
    event: z.literal("tool_call"),
    sessionId: z.string().min(1),
    tool: z.string().min(1),
    args: z.record(z.unknown()),
    ts: z.string().datetime(),
  }),
  z.object({
    event: z.literal("session_completed"),
    sessionId: z.string().min(1),
    status: z.literal("ok"),
    ts: z.string().datetime(),
  }),
  z.object({
    event: z.literal("session_error"),
    sessionId: z.string().min(1),
    code: z.string().min(1),
    message: z.string().min(1),
    ts: z.string().datetime(),
  }),
]);

export type ChatStreamEvent = z.infer<typeof ChatStreamEventSchema>;

export const ChatRuntimeConfigSchema = z.object({
  mode: z.literal("empty"),
  model: z.literal(hydraFusionModel),
  fallbackModel: z
    .string()
    .trim()
    .min(1)
    .optional()
    .nullable()
    .superRefine((value, ctx) => {
      if (value && value.trim().length > 0) {
        ctx.addIssue({
          code: "custom",
          message: "HydraFusion requires no fallback model; set PENGE_CHAT_FALLBACK_MODEL unset.",
        });
      }
    }),
  sessionId: z.string().min(1),
  githubLogin: z.string().min(1),
  copilotLogin: z.string().min(1),
  productionEnabled: z.boolean(),
  allowlist: z.array(z.enum(localMcpAllowlist)).min(1),
  blockedAmbientTools: z.array(z.enum(blockedAmbientTools)).default([...blockedAmbientTools]),
});

export type ChatRuntimeConfig = z.infer<typeof ChatRuntimeConfigSchema>;

export function buildLocalStdioMcpPolicy(
  env: NodeJS.ProcessEnv = process.env,
): LocalStdioMcpPolicy {
  const allowlist = 
    env.PENGE_CHAT_ALLOWED_TOOLS?.split(",")
      .map((tool) => tool.trim())
      .filter((tool) => tool.length > 0) ?? [...localMcpAllowlist];

  const parsed = LocalStdioMcpPolicySchema.safeParse({
    transport: "stdio",
    mode: "empty",
    allowlist,
    blockedAmbientTools: [...blockedAmbientTools],
  });

  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join(".") || "allowlist"}: ${issue.message}`)
      .join("; ");
    throw new Error(`invalid local stdio MCP policy: ${issues}`);
  }

  return parsed.data;
}

export function assertModelAvailable(model: string, allowlist: readonly string[]): void {
  if (!allowlist.includes(model)) {
    throw new ModelUnavailableError(`requested model ${model} is unavailable in this environment`);
  }
}

export function resolveChatRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
): ChatRuntimeConfig {
  const requestedModel = env.PENGE_CHAT_MODEL ?? hydraFusionModel;
  const fallbackModel = env.PENGE_CHAT_FALLBACK_MODEL?.trim() || undefined;
  const productionEnabled = env.PENGE_CHAT_ENABLE_PRODUCTION === "1";
  const githubLogin = env.PENGE_CHAT_GITHUB_LOGIN ?? "";
  const copilotLogin = env.PENGE_CHAT_COPILOT_LOGIN ?? "";
  const sessionId = env.PENGE_CHAT_SESSION_ID ?? "synthetic-session";

  assertModelAvailable(requestedModel, [hydraFusionModel]);
  if (fallbackModel) {
    throw new ModelUnavailableError(
      "HydraFusion requires no fallback model; set PENGE_CHAT_FALLBACK_MODEL unset.",
    );
  }
  if (githubLogin === copilotLogin && githubLogin.length > 0) {
    throw new SharedIdentityError(
      "GitHub and Copilot identities must be separate; a shared account is not supported.",
    );
  }
  if (!productionEnabled) {
    throw new ChatFeatureDisabledError(
      "HydraFusion chat is disabled until the exact entitlement check is complete and the production gate is explicitly enabled.",
    );
  }

  const parsed = ChatRuntimeConfigSchema.safeParse({
    mode: "empty",
    model: hydraFusionModel,
    fallbackModel,
    sessionId,
    githubLogin,
    copilotLogin,
    productionEnabled,
    allowlist: buildLocalStdioMcpPolicy(env).allowlist,
    blockedAmbientTools: [...blockedAmbientTools],
  });

  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join(".") || "config"}: ${issue.message}`)
      .join("; ");
    throw new Error(`invalid HydraFusion runtime config: ${issues}`);
  }

  return parsed.data;
}

export function buildSyntheticStream(sessionId: string): ChatStreamEvent[] {
  const ts = new Date().toISOString();
  return [
    {
      event: "session_started",
      sessionId,
      model: hydraFusionModel,
      mode: "empty",
      ts,
    },
    {
      event: "content_delta",
      sessionId,
      content: "I can answer using only the explicitly allowed Penge MCP tools.",
      ts,
    },
    {
      event: "tool_call",
      sessionId,
      tool: "penge.mcp.query_net_worth",
      args: { currency: "EUR", range: "30d" },
      ts,
    },
    {
      event: "session_completed",
      sessionId,
      status: "ok",
      ts,
    },
  ];
}
