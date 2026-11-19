import { access } from "node:fs/promises";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  CopilotClient,
  RuntimeConnection,
  ToolSet,
  type CopilotClientOptions,
  type GitHubTokenProvider,
} from "@github/copilot-sdk";
import { describe, expect, it, vi } from "vitest";

import { MCP_CHAT_TOOL_ALLOWLIST } from "../src/config.js";
import { HydraFusionUnavailableError, UpstreamResponseError } from "../src/errors.js";
import { BoundedMemorySessionFs } from "../src/memorySessionFs.js";
import {
  buildSessionConfig,
  GitHubCopilotRuntime,
  terminateRuntimeProcessTree,
} from "../src/sdk.js";
import { syntheticConfig } from "./helpers.js";

const provider: GitHubTokenProvider = async () => ({
  kind: "token",
  accessToken: "synthetic",
  expiresIn: 7_200,
});

function enabledModelRpc() {
  return {
    model: {
      list: async () => ({
        list: [{ id: "hydrafusion", policy: { state: "enabled" } }],
      }),
    },
  };
}

async function waitForFile(path: string): Promise<string> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      return await readFile(path, "utf8");
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
  throw new Error(`timed out waiting for ${path}`);
}

async function waitForProcessExit(pid: number): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const stat = await readFile(`/proc/${pid}/stat`, "utf8");
      if (stat.split(" ")[2] === "Z") return;
      process.kill(pid, 0);
    } catch (error) {
      if (["ENOENT", "ESRCH"].includes((error as NodeJS.ErrnoException).code ?? "")) return;
      throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`process ${pid} did not exit`);
}

describe("Copilot SDK policy", () => {
  it("pins empty mode session semantics to exact Copilot Fusion with local stdio MCP", async () => {
    const session = buildSessionConfig(syntheticConfig(), "actor-1", "session-1", provider);
    expect(session).toMatchObject({
      model: "hydrafusion",
      allowedModels: ["hydrafusion"],
      enableSessionStore: false,
      infiniteSessions: { enabled: false },
      largeOutput: { enabled: false },
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
    expect(session.createSessionFsProvider).toBeTypeOf("function");
    const memoryFs = new BoundedMemorySessionFs();
    await memoryFs.writeFile("/sessions/session-1/events.jsonl", "synthetic transcript");
    await expect(memoryFs.readFile("/sessions/session-1/events.jsonl")).resolves.toBe(
      "synthetic transcript",
    );
    await expect(
      memoryFs.writeFile("/sessions/too-large", "x".repeat(8 * 1024 * 1024 + 1)),
    ).rejects.toThrow(/memory is exhausted/);

    const fullMemoryFs = new BoundedMemorySessionFs();
    await fullMemoryFs.writeFile("/sessions/full", "x".repeat(8 * 1024 * 1024));
    await fullMemoryFs.rename("/sessions/full", "/sessions/./full");
    await expect(fullMemoryFs.writeFile("/sessions/extra", "x")).rejects.toThrow(
      /memory is exhausted/,
    );
  });

  it("approves only individual reviewed Penge MCP lookups without overriding managed approval", async () => {
    const session = buildSessionConfig(syntheticConfig(), "actor-1", "session-1", provider);
    const handle = session.onPermissionRequest;
    if (handle === undefined) throw new Error("permission handler was not installed");

    const request = {
      kind: "mcp" as const,
      serverName: "penge",
      toolName: "query_cashflow",
      toolTitle: "Synthetic lookup",
      readOnly: false,
    };
    const invocation = { sessionId: "session-1" };
    for (const toolName of MCP_CHAT_TOOL_ALLOWLIST) {
      expect(await handle({ ...request, toolName }, invocation)).toEqual({
        kind: "approve-once",
      });
    }

    for (const denied of [
      { ...request, serverName: "other" },
      { ...request, serverName: "penge-extra" },
      { ...request, toolName: "execute_sql" },
      { ...request, toolName: "_meta" },
      { ...request, toolName: "QUERY_CASHFLOW" },
      { ...request, toolName: " query_cashflow" },
      { ...request, managedApprovalRequired: true },
      {
        kind: "shell" as const,
        fullCommandText: "synthetic",
        intention: "synthetic",
        commands: [],
        possiblePaths: [],
        possibleUrls: [],
        canOfferSessionApproval: false,
        hasWriteFileRedirection: false,
      },
    ]) {
      expect(await handle(denied, invocation)).toMatchObject({ kind: "reject" });
    }
  });

  it("keeps tool output above the SDK spill threshold available to the event sink", async () => {
    const payload = "x".repeat(51_201);
    const received: unknown[] = [];
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      createSession: async (session) => {
        expect(session.largeOutput).toEqual({ enabled: false });
        return {
          rpc: enabledModelRpc(),
          send: async () => undefined,
          abort: async () => undefined,
          disconnect: async () => undefined,
          on: (handler) => {
            handler({
              id: crypto.randomUUID(),
              parentId: null,
              timestamp: new Date().toISOString(),
              type: "tool.execution_complete",
              data: {
                success: true,
                toolCallId: "large-output",
                result: { content: payload },
              },
            });
            return () => undefined;
          },
        };
      },
      stop: async () => [],
      forceStop: async () => undefined,
    }));
    const run = await runtime.createRun({
      actorId: "actor-a",
      sessionId: "large-output",
      tokenProvider: provider,
      sink: { onEvent: (event) => received.push(event) },
    });

    expect(JSON.stringify(received)).toContain(payload);
    await run.close();
  });

  it("does not forward runtime child stderr into service stderr", async () => {
    const directory = await mkdtemp(join(tmpdir(), "penge-copilot-stderr-"));
    const runtimePath = join(directory, "runtime.js");
    const marker = "synthetic-sensitive-runtime-marker";
    await writeFile(
      runtimePath,
      `process.stderr.write(${JSON.stringify(`${marker}\n`)}); setInterval(() => {}, 1000);`,
      "utf8",
    );
    const writes: string[] = [];
    const write = vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
      writes.push(String(chunk));
      return true;
    });
    const client = new CopilotClient({
      connection: RuntimeConnection.forStdio({ path: runtimePath }),
      mode: "empty",
      sessionFs: {
        initialCwd: directory,
        sessionStatePath: "/sessions",
        conventions: "posix",
      },
      logLevel: "none",
      useLoggedInUser: false,
    });
    const start = client.start().catch(() => undefined);
    try {
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(writes.join("")).not.toContain(marker);
    } finally {
      await client.forceStop();
      await start;
      write.mockRestore();
      await rm(directory, { recursive: true });
    }
  });

  it.runIf(process.platform !== "win32")(
    "force-stops a stuck runtime descendant process",
    async () => {
      const directory = await mkdtemp(join(tmpdir(), "penge-copilot-tree-"));
      const runtimePath = join(directory, "runtime.js");
      const descendantPidPath = join(directory, "descendant.pid");
      await writeFile(
        runtimePath,
        [
          'const { spawn } = require("node:child_process");',
          'const { writeFileSync } = require("node:fs");',
          `const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });`,
          `writeFileSync(${JSON.stringify(descendantPidPath)}, JSON.stringify({ runtime: process.pid, descendant: child.pid }));`,
          "setInterval(() => {}, 1000);",
        ].join("\n"),
        "utf8",
      );
      const client = new CopilotClient({
        connection: RuntimeConnection.forStdio({ path: runtimePath }),
        mode: "empty",
        sessionFs: {
          initialCwd: directory,
          sessionStatePath: "/sessions",
          conventions: "posix",
        },
        logLevel: "none",
        useLoggedInUser: false,
      });
      let runtimePid: number | undefined;
      try {
        const start = client.start().catch(() => undefined);
        const processIds = JSON.parse(await waitForFile(descendantPidPath)) as {
          runtime: number;
          descendant: number;
        };
        const descendantPid = processIds.descendant;
        runtimePid = processIds.runtime;
        expect(descendantPid).toBeGreaterThan(0);
        process.kill(descendantPid, 0);
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(
          (
            client as unknown as {
              ownedProcessGroups: Set<number>;
            }
          ).ownedProcessGroups,
        ).toContain(processIds.runtime);

        await client.forceStop();
        await terminateRuntimeProcessTree(runtimePid);
        await start;

        await waitForProcessExit(descendantPid);
      } finally {
        await client.forceStop();
        await terminateRuntimeProcessTree(runtimePid);
        await rm(directory, { recursive: true });
      }
    },
  );

  it("fails before process creation while Copilot Fusion is feature-disabled", async () => {
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

  it("pins an owned stdio runtime with minimal env despite ambient transport overrides", async () => {
    vi.stubEnv("COPILOT_SDK_DEFAULT_CONNECTION", "inprocess");
    vi.stubEnv("PENGE_SYNTHETIC_SENSITIVE_ENV", "synthetic-sensitive-env-marker");
    vi.stubEnv("PATH", "/synthetic/bin");
    let clientOptions: CopilotClientOptions | undefined;
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), (options) => {
      clientOptions = options;
      return {
        start: async () => {
          throw new Error("synthetic start stop");
        },
        createSession: async () => {
          throw new Error("unreachable");
        },
        stop: async () => [],
        forceStop: async () => undefined,
      };
    });
    try {
      await expect(
        runtime.createRun({
          actorId: "actor-a",
          sessionId: "session-a",
          tokenProvider: provider,
          sink: { onEvent: () => undefined },
        }),
      ).rejects.toThrow();
      expect(clientOptions?.mode).toBe("empty");
      expect(clientOptions?.env).toBeUndefined();
      const connection = clientOptions?.connection;
      expect(connection?.kind).toBe("stdio");
      const env = connection?.kind === "stdio" ? connection.env : undefined;
      expect(env?.PATH).toBe("/synthetic/bin");
      expect(
        Object.keys(env ?? {}).every((name) =>
          ["PATH", "TMPDIR", "XDG_RUNTIME_DIR", "LANG"].includes(name),
        ),
      ).toBe(true);
      expect(JSON.stringify(env)).not.toContain("synthetic-sensitive-env-marker");

      const client = new CopilotClient(clientOptions);
      expect(
        (client as unknown as { connectionConfig: { kind: string } }).connectionConfig.kind,
      ).toBe("stdio");
    } finally {
      vi.unstubAllEnvs();
    }
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

  it.each([
    ["disabled", [{ id: "hydrafusion", policy: { state: "disabled" } }]],
    ["unconfigured", [{ id: "hydrafusion", policy: { state: "unconfigured" } }]],
    ["missing policy", [{ id: "hydrafusion" }]],
    ["unknown policy", [{ id: "hydrafusion", policy: { state: "unknown" } }]],
    ["missing model", [{ id: "another-model", policy: { state: "enabled" } }]],
    [
      "duplicate model",
      [
        { id: "hydrafusion", policy: { state: "enabled" } },
        { id: "hydrafusion", policy: { state: "disabled" } },
      ],
    ],
  ])("rejects the exact model when its policy is %s", async (_label, models) => {
    const list = vi.fn(async () => ({ list: models }));
    const send = vi.fn(async () => undefined);
    const forceStop = vi.fn(async () => undefined);
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      createSession: async () => ({
        rpc: { model: { list } },
        send,
        abort: async () => undefined,
        disconnect: async () => undefined,
        on: () => () => undefined,
      }),
      stop: async () => [],
      forceStop,
    }));

    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toBeInstanceOf(HydraFusionUnavailableError);
    expect(list).toHaveBeenCalledWith({ skipCache: true });
    expect(send).not.toHaveBeenCalled();
    expect(forceStop).toHaveBeenCalledOnce();
  });

  it("fails explicitly and cleans up when the session model list is malformed", async () => {
    const forceStop = vi.fn(async () => undefined);
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      createSession: async () => ({
        rpc: { model: { list: async () => ({ list: "invalid" }) } },
        send: async () => undefined,
        abort: async () => undefined,
        disconnect: async () => undefined,
        on: () => () => undefined,
      }),
      stop: async () => [],
      forceStop,
    }));

    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toBeInstanceOf(UpstreamResponseError);
    expect(forceStop).toHaveBeenCalledOnce();
  });

  it("bounds a stalled session model-list request and cleans up", async () => {
    const forceStop = vi.fn(async () => undefined);
    const runtime = new GitHubCopilotRuntime(syntheticConfig({ requestTimeoutMs: 20 }), () => ({
      start: async () => undefined,
      createSession: async () => ({
        rpc: { model: { list: async () => new Promise<never>(() => undefined) } },
        send: async () => undefined,
        abort: async () => undefined,
        disconnect: async () => undefined,
        on: () => () => undefined,
      }),
      stop: async () => [],
      forceStop,
    }));

    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toThrow(/exceeded 20 ms/);
    expect(forceStop).toHaveBeenCalledOnce();
  });

  it("uses no disk-backed session path even when forced termination interrupts setup", async () => {
    const copilotBaseDirectory = join(tmpdir(), `penge-chat-${crypto.randomUUID()}`);
    let clientOptions: CopilotClientOptions | undefined;
    const runtime = new GitHubCopilotRuntime(
      syntheticConfig({ copilotBaseDirectory }),
      (options) => {
        clientOptions = options;
        return {
          start: async () => undefined,
          createSession: async () => {
            throw new Error("synthetic forced termination");
          },
          stop: async () => [],
          forceStop: async () => undefined,
        };
      },
    );
    await expect(
      runtime.createRun({
        actorId: "actor-a",
        sessionId: "session-a",
        tokenProvider: provider,
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toThrow(/forced termination/);
    expect(clientOptions?.baseDirectory).toBeUndefined();
    expect(clientOptions?.sessionFs).toMatchObject({
      sessionStatePath: "/sessions",
      conventions: "posix",
    });
    await expect(access(copilotBaseDirectory)).rejects.toThrow();
  });

  it("uses each actor's provider for that actor's exact-model session", async () => {
    const accessTokens: string[] = [];
    const policyTokens: string[] = [];
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
          rpc: {
            model: {
              list: async (options) => {
                expect(options).toEqual({ skipCache: true });
                if (token?.kind === "token") policyTokens.push(token.accessToken);
                return { list: [{ id: "hydrafusion", policy: { state: "enabled" } }] };
              },
            },
          },
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
    expect(policyTokens.sort()).toEqual(["actor-a-token", "actor-b-token"]);
    await Promise.all(runs.map(async (run) => run.close()));
  });

  it("does not use one actor's enabled model policy for another actor", async () => {
    const runtime = new GitHubCopilotRuntime(syntheticConfig(), () => ({
      start: async () => undefined,
      createSession: async (session) => {
        const token = await session.gitHubTokenProvider?.({
          host: "github.com",
          sessionId: session.sessionId ?? "synthetic-session",
          reason: "initial",
        });
        return {
          rpc: {
            model: {
              list: async () => ({
                list: [
                  {
                    id: "hydrafusion",
                    policy: {
                      state:
                        token?.kind === "token" && token.accessToken === "actor-a-token"
                          ? "enabled"
                          : "disabled",
                    },
                  },
                ],
              }),
            },
          },
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
      async () => ({ kind: "token", accessToken, expiresIn: 7200 });

    const first = await runtime.createRun({
      actorId: "actor-a",
      sessionId: "session-a",
      tokenProvider: providerFor("actor-a-token"),
      sink: { onEvent: () => undefined },
    });
    await expect(
      runtime.createRun({
        actorId: "actor-b",
        sessionId: "session-b",
        tokenProvider: providerFor("actor-b-token"),
        sink: { onEvent: () => undefined },
      }),
    ).rejects.toBeInstanceOf(HydraFusionUnavailableError);
    await first.close();
  });

  it("bounds abort and teardown and force-stops after cooperative cleanup fails", async () => {
    const forceStop = vi.fn(async () => undefined);
    const stop = vi.fn(async () => [new Error("synthetic stop failure")]);
    const runtime = new GitHubCopilotRuntime(syntheticConfig({ requestTimeoutMs: 10 }), () => ({
      start: async () => undefined,
      createSession: async () => ({
        rpc: enabledModelRpc(),
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
