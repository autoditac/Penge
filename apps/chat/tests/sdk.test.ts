import { ToolSet, type GitHubTokenProvider } from "@github/copilot-sdk";
import { describe, expect, it, vi } from "vitest";

import { buildSessionConfig, GitHubCopilotRuntime } from "../src/sdk.js";
import { syntheticConfig } from "./helpers.js";

const provider: GitHubTokenProvider = async () => ({
  kind: "token",
  accessToken: "synthetic",
  expiresIn: 7_200,
});

describe("Copilot SDK policy", () => {
  it("pins empty mode session semantics to exact HydraFusion with local stdio MCP", () => {
    const session = buildSessionConfig(syntheticConfig(), "session-1", provider);
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
    const runtime = new GitHubCopilotRuntime(syntheticConfig({ productionEnabled: false }));
    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toThrow(/disabled until/);
  });

  it("checks exact-model session creation with the linked actor token and never listModels", async () => {
    const listModels = vi.fn();
    const tokenProvider = vi.fn(provider);
    const forceStop = vi.fn(async () => undefined);
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      listModels,
      createSession: async (session) => {
        await session.gitHubTokenProvider?.({
          host: "github.com",
          sessionId: "session-a",
          reason: "initial",
        });
        throw {
          code: "model_not_entitled",
          message: "hydrafusion unavailable",
        };
      },
      stop: async () => [],
      forceStop,
    }));

    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toThrow(/exact hydrafusion session/);
    expect(tokenProvider).toHaveBeenCalledOnce();
    expect(listModels).not.toHaveBeenCalled();
    expect(forceStop).toHaveBeenCalledOnce();
  });

  it("uses each actor's provider for that actor's exact-model session", async () => {
    const accessTokens: string[] = [];
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      createSession: async (session) => {
        const token = await session.gitHubTokenProvider?.({
          host: "github.com",
          sessionId: session.sessionId ?? "synthetic-session",
          reason: "initial",
        });
        if (token?.kind === "token") {
          accessTokens.push(token.accessToken);
        }
        return {
          send: async () => undefined,
          abort: async () => undefined,
          disconnect: async () => undefined,
          on: () => () => undefined,
        };
      },
      stop: async () => [],
      forceStop: async () => undefined,
    }));
    const providerFor =
      (accessToken: string): GitHubTokenProvider =>
      async () => ({
        kind: "token",
        accessToken,
        expiresIn: 7_200,
      });

    const runs = await Promise.all([
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: providerFor("actor-a-token"),
        sink: { onEvent: () => undefined },
      }),
      runtime.createRun({
        actorId: "actor-b",
        sessionId: "session-b",
        tokenProvider: providerFor("actor-b-token"),
        sink: { onEvent: () => undefined },
      }),
    ]);
    expect(accessTokens.sort()).toEqual(["actor-a-token", "actor-b-token"]);
    await Promise.all(runs.map(async (run) => run.close()));
  });

  it("bounds abort and teardown and force-stops after cooperative cleanup fails", async () => {
    const forceStop = vi.fn(async () => undefined);
    const stop = vi.fn(async () => [new Error("synthetic stop failure")]);
    const runtime = new GitHubCopilotRuntime(syntheticConfig({ requestTimeoutMs: 10 }), () => ({
      start: async () => undefined,
      createSession: async () => ({
        send: async () => undefined,
        abort: async () => new Promise<void>(() => undefined),
        disconnect: async () => new Promise<void>(() => undefined),
        on: () => () => undefined,
      }),
      stop,
      forceStop,
    }));
    const run = await runtime.createRun({
      actorId: "actor-a",
      sessionId: "bounded-cleanup",
      tokenProvider: provider,
      sink: { onEvent: () => undefined },
    });

    await expect(run.abort()).rejects.toThrow(/exceeded 10 ms/);
    await expect(run.close()).rejects.toThrow(/cleanup failed/i);
    expect(stop).toHaveBeenCalledOnce();
    expect(forceStop).toHaveBeenCalledOnce();
  });
});
