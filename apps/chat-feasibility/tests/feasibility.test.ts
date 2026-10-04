import { describe, expect, it } from "vitest";
import type { SessionEvent } from "@github/copilot-sdk";

import {
  ChatFeatureDisabledError,
  ModelUnavailableError,
  SdkCleanupError,
  UserCredentialScopeError,
  assertHydraFusionAvailable,
  assertSdkCleanupSucceeded,
  blockedToolSources,
  buildCopilotSdkProof,
  chatToolContractVersion,
  hydraFusionModel,
  pengeMcpChatTools,
  pengeMcpRegisteredTools,
  resolveChatRuntimeConfig,
  validateSyntheticCopilotStream,
} from "../src/index.js";

const actorId = "actor_0123456789abcdef";
const githubLogin = "synthetic-user-a";
const verifiedAt = "2026-10-04T08:00:00.000Z";

function enabledRuntime() {
  return resolveChatRuntimeConfig(
    {
      PENGE_CHAT_MODEL: hydraFusionModel,
      PENGE_CHAT_ENABLE_PRODUCTION: "1",
      PENGE_CHAT_ACTOR_ID: actorId,
      PENGE_CHAT_GITHUB_LOGIN: githubLogin,
    },
    {
      actorId,
      githubLogin,
      model: hydraFusionModel,
      verifiedAt,
    },
  );
}

describe("HydraFusion Copilot SDK feasibility proof", () => {
  it("builds the pinned SDK empty-mode session with stdio-only MCP", () => {
    const proof = buildCopilotSdkProof({
      runtime: enabledRuntime(),
      tokenProvider: {
        actorId,
        githubLogin,
        acquire: async () => ({
          kind: "token",
          accessToken: "synthetic-token",
          expiresIn: 300,
        }),
      },
      baseDirectory: "/tmp/penge-copilot/actor_0123456789abcdef",
      workingDirectory: "/srv/penge",
    });

    expect(proof.client).toMatchObject({
      mode: "empty",
      useLoggedInUser: false,
      logLevel: "error",
    });
    expect(proof.toolContractVersion).toBe(chatToolContractVersion);
    expect(proof.registeredMcpTools).toEqual(["_meta", ...pengeMcpChatTools]);
    expect(proof.chatExposedMcpTools).toEqual(pengeMcpChatTools);
    expect(proof.chatExposedMcpTools).not.toContain("_meta");
    expect(proof.session).toMatchObject({
      model: hydraFusionModel,
      allowedModels: [hydraFusionModel],
      streaming: true,
      enableSessionStore: false,
      includedBuiltinSkills: [],
      mcpOAuthTokenStorage: "in-memory",
    });
    expect(proof.session.mcpServers).toEqual({
      penge: {
        type: "stdio",
        command: "pnpm",
        args: ["--filter", "@penge/mcp", "start"],
        workingDirectory: "/srv/penge",
        tools: pengeMcpChatTools,
      },
    });
    expect("url" in (proof.session.mcpServers?.penge ?? {})).toBe(false);
  });

  it("allows only named Penge MCP tools and denies every ambient source", () => {
    const proof = buildCopilotSdkProof({
      runtime: enabledRuntime(),
      tokenProvider: {
        actorId,
        githubLogin,
        acquire: async () => ({
          kind: "token",
          accessToken: "synthetic-token",
          expiresIn: 300,
        }),
      },
      baseDirectory: "/tmp/penge-copilot/actor_0123456789abcdef",
      workingDirectory: "/srv/penge",
    });

    const availableTools = proof.session.availableTools;
    const excludedTools = proof.session.excludedTools;

    expect(availableTools).not.toBeInstanceOf(Array);
    expect(excludedTools).not.toBeInstanceOf(Array);
    if (availableTools instanceof Array || excludedTools instanceof Array) {
      throw new Error("expected SDK ToolSet instances");
    }

    expect(availableTools?.toArray()).toEqual(pengeMcpChatTools.map((tool) => `mcp:penge-${tool}`));
    expect(excludedTools?.toArray()).toEqual(blockedToolSources);
  });

  it("pins the final MCP registration and chat-exposure contract from issue 344", () => {
    expect(chatToolContractVersion).toBe("issue-344-v1");
    expect(pengeMcpRegisteredTools).toEqual([
      "_meta",
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
    ]);
    expect(pengeMcpChatTools).toEqual(pengeMcpRegisteredTools.slice(1));
  });

  it("requires exact model configuration and the production gate", () => {
    expect(() =>
      resolveChatRuntimeConfig(
        {
          PENGE_CHAT_MODEL: "gpt-5.4",
          PENGE_CHAT_ENABLE_PRODUCTION: "1",
          PENGE_CHAT_ACTOR_ID: actorId,
          PENGE_CHAT_GITHUB_LOGIN: githubLogin,
        },
        {
          actorId,
          githubLogin,
          model: hydraFusionModel,
          verifiedAt,
        },
      ),
    ).toThrow(ModelUnavailableError);

    expect(() =>
      resolveChatRuntimeConfig(
        {
          PENGE_CHAT_MODEL: hydraFusionModel,
          PENGE_CHAT_FALLBACK_MODEL: "gpt-5.4",
          PENGE_CHAT_ENABLE_PRODUCTION: "1",
          PENGE_CHAT_ACTOR_ID: actorId,
          PENGE_CHAT_GITHUB_LOGIN: githubLogin,
        },
        {
          actorId,
          githubLogin,
          model: hydraFusionModel,
          verifiedAt,
        },
      ),
    ).toThrow(ModelUnavailableError);

    expect(() =>
      resolveChatRuntimeConfig(
        {
          PENGE_CHAT_MODEL: hydraFusionModel,
          PENGE_CHAT_ACTOR_ID: actorId,
          PENGE_CHAT_GITHUB_LOGIN: githubLogin,
        },
        {
          actorId,
          githubLogin,
          model: hydraFusionModel,
          verifiedAt,
        },
      ),
    ).toThrow(ChatFeatureDisabledError);
  });

  it("rejects another actor using the first actor's entitlement verification", () => {
    expect(() =>
      resolveChatRuntimeConfig(
        {
          PENGE_CHAT_MODEL: hydraFusionModel,
          PENGE_CHAT_ENABLE_PRODUCTION: "1",
          PENGE_CHAT_ACTOR_ID: "actor_fedcba9876543210",
          PENGE_CHAT_GITHUB_LOGIN: "synthetic-user-b",
        },
        {
          actorId,
          githubLogin,
          model: hydraFusionModel,
          verifiedAt,
        },
      ),
    ).toThrow(UserCredentialScopeError);
  });

  it("rejects an entitlement verification for a different linked GitHub identity", () => {
    expect(() =>
      resolveChatRuntimeConfig(
        {
          PENGE_CHAT_MODEL: hydraFusionModel,
          PENGE_CHAT_ENABLE_PRODUCTION: "1",
          PENGE_CHAT_ACTOR_ID: actorId,
          PENGE_CHAT_GITHUB_LOGIN: "synthetic-user-b",
        },
        {
          actorId,
          githubLogin,
          model: hydraFusionModel,
          verifiedAt,
        },
      ),
    ).toThrow(UserCredentialScopeError);
  });

  it("returns a typed unavailable-model error from user-scoped model metadata", () => {
    expect(() => assertHydraFusionAvailable([{ id: "gpt-5.4" }])).toThrow(ModelUnavailableError);
    expect(() => assertHydraFusionAvailable([{ id: hydraFusionModel }])).not.toThrow();
  });

  it("fails the entitlement probe when SDK cleanup returns errors", () => {
    expect(() => assertSdkCleanupSucceeded([])).not.toThrow();
    expect(() => assertSdkCleanupSucceeded([new Error("runtime did not terminate")])).toThrow(
      SdkCleanupError,
    );
  });

  it("rejects a token provider owned by another household actor", () => {
    expect(() =>
      buildCopilotSdkProof({
        runtime: enabledRuntime(),
        tokenProvider: {
          actorId: "actor_fedcba9876543210",
          githubLogin: "synthetic-user-b",
          acquire: async () => ({
            kind: "token",
            accessToken: "synthetic-token",
            expiresIn: 300,
          }),
        },
        baseDirectory: "/tmp/penge-copilot/actor_0123456789abcdef",
        workingDirectory: "/srv/penge",
      }),
    ).toThrow(UserCredentialScopeError);
  });

  it("validates the official streaming event names with synthetic payloads", () => {
    const sdkEvents = [
      {
        id: "00000000-0000-4000-8000-000000000001",
        parentId: null,
        timestamp: "2026-10-04T08:00:00.000Z",
        type: "assistant.message_delta",
        ephemeral: true,
        data: {
          deltaContent: "Grounded answer",
          messageId: "message-1",
        },
      },
      {
        id: "00000000-0000-4000-8000-000000000002",
        parentId: "00000000-0000-4000-8000-000000000001",
        timestamp: "2026-10-04T08:00:00.100Z",
        type: "tool.execution_start",
        data: {
          toolName: "penge-query_net_worth",
          toolCallId: "call-1",
          arguments: { currency: "EUR" },
          mcpServerName: "penge",
          mcpToolName: "query_net_worth",
        },
      },
      {
        id: "00000000-0000-4000-8000-000000000003",
        parentId: "00000000-0000-4000-8000-000000000002",
        timestamp: "2026-10-04T08:00:00.200Z",
        type: "session.idle",
        ephemeral: true,
        data: {},
      },
    ] satisfies SessionEvent[];
    const parsed = validateSyntheticCopilotStream(sdkEvents);

    expect(parsed.map((event) => event.type)).toEqual([
      "assistant.message_delta",
      "tool.execution_start",
      "session.idle",
    ]);
    expect(() =>
      validateSyntheticCopilotStream([
        {
          id: "00000000-0000-4000-8000-000000000001",
          parentId: null,
          timestamp: "2026-10-04T08:00:00.000Z",
          type: "assistant.message_delta",
          ephemeral: true,
          data: { content: "wrong SDK field" },
        },
      ]),
    ).toThrow();
  });
});
