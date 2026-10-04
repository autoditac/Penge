import { describe, expect, it } from "vitest";

import {
  ChatFeatureDisabledError,
  ChatStreamEventSchema,
  ModelUnavailableError,
  SharedIdentityError,
  buildLocalStdioMcpPolicy,
  buildSyntheticStream,
  hydraFusionModel,
  localMcpAllowlist,
  resolveChatRuntimeConfig,
} from "../src/chat.js";

describe("HydraFusion chat safety proof", () => {
  it("uses local stdio MCP and an explicit allowlist without ambient tools", () => {
    const policy = buildLocalStdioMcpPolicy({
      PENGE_CHAT_ALLOWED_TOOLS: [
        "penge.mcp.query_net_worth",
        "penge.mcp.query_cashflow",
        "penge.mcp.search_documents",
      ].join(","),
    });

    expect(policy.transport).toBe("stdio");
    expect(policy.mode).toBe("empty");
    expect(policy.allowlist).toEqual([
      "penge.mcp.query_net_worth",
      "penge.mcp.query_cashflow",
      "penge.mcp.search_documents",
    ]);
    expect(policy.blockedAmbientTools).toEqual(["shell", "filesystem", "default"]);
  });

  it("accepts the configured empty-mode HydraFusion runtime when the production gate is enabled", () => {
    const cfg = resolveChatRuntimeConfig({
      PENGE_CHAT_MODEL: hydraFusionModel,
      PENGE_CHAT_ENABLE_PRODUCTION: "1",
      PENGE_CHAT_GITHUB_LOGIN: "github-user",
      PENGE_CHAT_COPILOT_LOGIN: "copilot-user",
      PENGE_CHAT_SESSION_ID: "session-123",
      PENGE_CHAT_ALLOWED_TOOLS: localMcpAllowlist.join(","),
    });

    expect(cfg.model).toBe(hydraFusionModel);
    expect(cfg.mode).toBe("empty");
    expect(cfg.allowlist).toEqual(localMcpAllowlist);
    expect(cfg.blockedAmbientTools).toEqual(["shell", "filesystem", "default"]);
    expect(cfg.fallbackModel).toBeUndefined();
  });

  it("requires the exact HydraFusion model and rejects a fallback", () => {
    expect(() =>
      resolveChatRuntimeConfig({
        PENGE_CHAT_MODEL: "gpt-5.4",
        PENGE_CHAT_ENABLE_PRODUCTION: "1",
        PENGE_CHAT_GITHUB_LOGIN: "github-user",
        PENGE_CHAT_COPILOT_LOGIN: "copilot-user",
        PENGE_CHAT_ALLOWED_TOOLS: localMcpAllowlist.join(","),
      }),
    ).toThrow(ModelUnavailableError);

    expect(() =>
      resolveChatRuntimeConfig({
        PENGE_CHAT_MODEL: hydraFusionModel,
        PENGE_CHAT_FALLBACK_MODEL: "gpt-5.4",
        PENGE_CHAT_ENABLE_PRODUCTION: "1",
        PENGE_CHAT_GITHUB_LOGIN: "github-user",
        PENGE_CHAT_COPILOT_LOGIN: "copilot-user",
        PENGE_CHAT_ALLOWED_TOOLS: localMcpAllowlist.join(","),
      }),
    ).toThrow(ModelUnavailableError);
  });

  it("rejects shared GitHub/Copilot identities and a disabled production gate", () => {
    expect(() =>
      resolveChatRuntimeConfig({
        PENGE_CHAT_MODEL: hydraFusionModel,
        PENGE_CHAT_ENABLE_PRODUCTION: "0",
        PENGE_CHAT_GITHUB_LOGIN: "shared-user",
        PENGE_CHAT_COPILOT_LOGIN: "shared-user",
        PENGE_CHAT_ALLOWED_TOOLS: localMcpAllowlist.join(","),
      }),
    ).toThrow(SharedIdentityError);

    expect(() =>
      resolveChatRuntimeConfig({
        PENGE_CHAT_MODEL: hydraFusionModel,
        PENGE_CHAT_GITHUB_LOGIN: "github-user",
        PENGE_CHAT_COPILOT_LOGIN: "copilot-user",
        PENGE_CHAT_ALLOWED_TOOLS: localMcpAllowlist.join(","),
      }),
    ).toThrow(ChatFeatureDisabledError);
  });

  it("outputs the streaming event contract used by the chat harness", () => {
    const sessionId = "synthetic-session";
    const events = buildSyntheticStream(sessionId);
    const parsed = events.map((event) => ChatStreamEventSchema.parse(event));

    expect(parsed).toHaveLength(4);
    expect(parsed[0]).toMatchObject({
      event: "session_started",
      model: hydraFusionModel,
      mode: "empty",
      sessionId,
    });
    expect(parsed[1]).toMatchObject({
      event: "content_delta",
      sessionId,
    });
    expect(parsed[2]).toMatchObject({
      event: "tool_call",
      tool: "penge.mcp.query_net_worth",
    });
    expect(parsed[3]).toMatchObject({
      event: "session_completed",
      status: "ok",
      sessionId,
    });
  });
});
