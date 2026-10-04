import { describe, expect, it } from "vitest";
import type { SessionEvent } from "@github/copilot-sdk";

import {
  ChatFeatureDisabledError,
  ModelUnavailableError,
  UserCredentialScopeError,
  assertHydraFusionAvailable,
  blockedToolSources,
  buildCopilotSdkProof,
  chatToolContractVersion,
  hydraFusionModel,
  pengeMcpTools,
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
        tools: pengeMcpTools,
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

    expect(availableTools?.toArray()).toEqual(pengeMcpTools.map((tool) => `mcp:penge-${tool}`));
    expect(excludedTools?.toArray()).toEqual(blockedToolSources);
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
