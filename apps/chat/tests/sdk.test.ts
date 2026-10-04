import { ToolSet, type GitHubTokenProvider } from "@github/copilot-sdk";
import { describe, expect, it } from "vitest";

import {
  assertHydraFusionAvailable,
  buildSessionConfig,
  GitHubCopilotRuntime,
} from "../src/sdk.js";
import { syntheticConfig } from "./helpers.js";

const provider: GitHubTokenProvider = async () => ({
  kind: "token",
  accessToken: "synthetic",
  expiresIn: 7_200,
});

describe("Copilot SDK policy", () => {
  it("pins empty mode session semantics to exact HydraFusion with local stdio MCP", () => {
    const session = buildSessionConfig(
      syntheticConfig({ productionEnabled: true, entitlementVerified: true }),
      "session-1",
      provider,
    );
    expect(session).toMatchObject({
      model: "hydrafusion",
      allowedModels: ["hydrafusion"],
      enableSessionStore: false,
      enableConfigDiscovery: false,
      includedBuiltinSkills: [],
      requestCanvasRenderer: false,
      requestExtensions: false,
      mcpOAuthTokenStorage: "in-memory",
    });
    expect(session.mcpServers?.penge).toMatchObject({
      type: "stdio",
      command: "pnpm",
    });
    expect("url" in (session.mcpServers?.penge ?? {})).toBe(false);
    expect(session.availableTools).toBeInstanceOf(ToolSet);
    expect(session.excludedTools).toBeInstanceOf(ToolSet);
    if (
      !(session.availableTools instanceof ToolSet) ||
      !(session.excludedTools instanceof ToolSet)
    ) {
      throw new Error("empty-mode tool filters must use SDK ToolSet");
    }
    expect(session.availableTools.toArray()).toContain("mcp:penge-get_source_coverage");
    expect(session.excludedTools.toArray()).toEqual(["builtin:*", "custom:*"]);
  });

  it("fails before process creation while HydraFusion is feature-disabled", async () => {
    const runtime = new GitHubCopilotRuntime(syntheticConfig());
    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toThrow(/disabled until/);
  });

  it("fails closed when the exact experimental model is unavailable", () => {
    expect(() => assertHydraFusionAvailable([{ id: "gpt-5.4" }])).toThrow(
      /not entitled to hydrafusion/,
    );
    expect(() => assertHydraFusionAvailable([{ id: "hydrafusion-preview" }])).toThrow(
      /not entitled to hydrafusion/,
    );
    expect(() => assertHydraFusionAvailable([{ id: "hydrafusion" }])).not.toThrow();
  });
});
