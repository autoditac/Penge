import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { CopilotClient, RuntimeConnection } from "@github/copilot-sdk";
import { describe, expect, it, vi } from "vitest";

import {
  EntitlementProbeInterruptedError,
  EntitlementProbeTimeoutError,
  diagnosticClientOptions,
  probeEntitlement,
  type EntitlementProbeClient,
} from "../src/entitlement.js";
import { SdkCleanupError, hydraFusionModel } from "../src/index.js";

const fixture = fileURLToPath(new URL("./fixtures/unresponsive-runtime.mjs", import.meta.url));

describe("isolated diagnostic authentication", () => {
  it("requires an explicit user credential without falling back to persisted or ambient auth", () => {
    const environment = {
      PATH: "/usr/bin:/bin",
      GH_TOKEN: "ambient-gh",
      GITHUB_TOKEN: "ambient-github",
      COPILOT_GITHUB_TOKEN: "ambient-copilot",
      COPILOT_HOME: "/persisted/copilot",
    };
    for (const token of [undefined, "", "   "]) {
      expect(() =>
        diagnosticClientOptions(
          {
            ...environment,
            PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN: token,
          },
          "/isolated",
        ),
      ).toThrow("PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN");
    }
    const options = diagnosticClientOptions(
      {
        ...environment,
        PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN: "synthetic-explicit-token",
      },
      "/isolated",
    );
    expect(options).toMatchObject({
      mode: "empty",
      baseDirectory: "/isolated",
      gitHubToken: "synthetic-explicit-token",
      useLoggedInUser: false,
      env: { PATH: "/usr/bin:/bin" },
    });
    expect(options.env).toEqual({ PATH: "/usr/bin:/bin" });
    expect(() => new CopilotClient(options)).not.toThrow();
  });
});

function syntheticClient(
  baseDirectory: string,
  shutdown: "graceful" | "stubborn",
  handshake: "complete" | "never" = "complete",
): CopilotClient {
  return new CopilotClient({
    connection: RuntimeConnection.forStdio({ path: process.execPath, args: [fixture] }),
    mode: "empty",
    baseDirectory,
    useLoggedInUser: false,
    logLevel: "none",
    env: {
      PENGE_FAKE_PID_FILE: join(baseDirectory, "runtime.pid"),
      PENGE_FAKE_SHUTDOWN: shutdown,
      PENGE_FAKE_HANDSHAKE: handshake,
    },
  });
}

async function expectProcessGone(pid: number): Promise<void> {
  await vi.waitFor(
    () => {
      expect(() => process.kill(pid, 0)).toThrowError(expect.objectContaining({ code: "ESRCH" }));
    },
    { timeout: 3_000, interval: 25 },
  );
}

function trackStartup(client: CopilotClient): {
  probeClient: EntitlementProbeClient;
  startup: () => Promise<void> | undefined;
} {
  let startup: Promise<void> | undefined;
  return {
    probeClient: {
      start: () => {
        startup = client.start();
        return startup;
      },
      listModels: () => client.listModels(),
      stop: () => client.stop(),
      forceStop: () => client.forceStop(),
    },
    startup: () => startup,
  };
}

describe("bounded entitlement probe", () => {
  it("does not start an already interrupted probe", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const controller = new AbortController();
    controller.abort();
    const start = vi.fn(async () => {});
    const stop = vi.fn(async () => []);
    const client: EntitlementProbeClient = {
      start,
      listModels: vi.fn(async () => [{ id: hydraFusionModel }]),
      stop,
      forceStop: async () => {},
    };

    await expect(
      probeEntitlement(client, baseDirectory, undefined, controller.signal),
    ).rejects.toBeInstanceOf(EntitlementProbeInterruptedError);
    expect(start).not.toHaveBeenCalled();
    expect(stop).toHaveBeenCalledOnce();
    await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("withholds a result when interrupted during graceful cleanup", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const controller = new AbortController();
    let markStopping: () => void = () => {};
    let finishStopping: () => void = () => {};
    const stopping = new Promise<void>((resolve) => {
      markStopping = resolve;
    });
    const stopped = new Promise<void>((resolve) => {
      finishStopping = resolve;
    });
    const client: EntitlementProbeClient = {
      start: async () => {},
      listModels: async () => [{ id: hydraFusionModel }],
      stop: async () => {
        markStopping();
        await stopped;
        return [];
      },
      forceStop: async () => {},
    };

    const result = probeEntitlement(client, baseDirectory, undefined, controller.signal);
    try {
      await stopping;
      controller.abort();
      finishStopping();
      await expect(result).rejects.toBeInstanceOf(EntitlementProbeInterruptedError);
      await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      finishStopping();
      await rm(baseDirectory, { recursive: true, force: true });
    }
  });

  it("reports a result only after graceful cleanup", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const client: EntitlementProbeClient = {
      start: async () => {},
      listModels: async () => [{ id: hydraFusionModel }],
      stop: async () => [],
      forceStop: async () => {
        throw new Error("unexpected forced shutdown");
      },
    };

    await expect(probeEntitlement(client, baseDirectory)).resolves.toEqual({
      exactModel: hydraFusionModel,
      entitled: true,
      matchCount: 1,
    });
    await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it.each([
    { state: "enabled", entitled: true },
    { state: "disabled", entitled: false },
    { state: "unconfigured", entitled: false },
  ] as const)("checks listed model policy $state", async ({ state, entitled }) => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const client: EntitlementProbeClient = {
      start: async () => {},
      listModels: async () => [{ id: hydraFusionModel, policy: { state, terms: "" } }],
      stop: async () => [],
      forceStop: async () => {},
    };

    await expect(probeEntitlement(client, baseDirectory)).resolves.toEqual({
      exactModel: hydraFusionModel,
      entitled,
      matchCount: 1,
    });
    await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("does not grant entitlement for duplicate exact model IDs", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const client: EntitlementProbeClient = {
      start: async () => {},
      listModels: async () => [{ id: hydraFusionModel }, { id: hydraFusionModel }],
      stop: async () => [],
      forceStop: async () => {},
    };

    await expect(probeEntitlement(client, baseDirectory)).resolves.toEqual({
      exactModel: hydraFusionModel,
      entitled: false,
      matchCount: 2,
    });
    await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("withholds a successful result when SDK cleanup reports errors", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const forceStop = vi.fn(async () => {});
    const client: EntitlementProbeClient = {
      start: async () => {},
      listModels: async () => [{ id: hydraFusionModel }],
      stop: async () => [new Error("synthetic cleanup failure")],
      forceStop,
    };

    await expect(probeEntitlement(client, baseDirectory)).rejects.toBeInstanceOf(SdkCleanupError);
    expect(forceStop).toHaveBeenCalledOnce();
    await expect(stat(baseDirectory)).resolves.toBeDefined();
    await rm(baseDirectory, { recursive: true, force: true });
  });

  it("times out a nonresponding runtime and cleans up after graceful exit", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const client = syntheticClient(baseDirectory, "graceful");

    await expect(
      probeEntitlement(client, baseDirectory, { probeMs: 2_000, shutdownMs: 3_000 }),
    ).rejects.toBeInstanceOf(EntitlementProbeTimeoutError);
    await expect(stat(baseDirectory)).rejects.toMatchObject({ code: "ENOENT" });
  }, 10_000);

  it("forces an unresponsive runtime to stop and retains unverified storage", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const client = syntheticClient(baseDirectory, "stubborn");

    await expect(
      probeEntitlement(client, baseDirectory, { probeMs: 2_000, shutdownMs: 500 }),
    ).rejects.toBeInstanceOf(SdkCleanupError);
    const pid = Number(await readFile(join(baseDirectory, "runtime.pid"), "utf8"));
    expect(Number.isInteger(pid) && pid > 0).toBe(true);
    await expect(stat(baseDirectory)).resolves.toBeDefined();
    await expectProcessGone(pid);
    await rm(baseDirectory, { recursive: true, force: true });
  }, 10_000);

  it("stops a runtime that starts after the probe deadline", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    let finishStartup: () => void = () => {
      throw new Error("synthetic startup was not initialized");
    };
    let child: ChildProcess | undefined;
    const startup = new Promise<void>((resolve) => {
      finishStartup = resolve;
    });
    const listModels = vi.fn(async () => [{ id: hydraFusionModel }]);
    const forceStop = vi.fn(async () => {
      child?.kill("SIGKILL");
    });
    const client: EntitlementProbeClient = {
      start: async () => {
        await startup;
        child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
          stdio: "ignore",
        });
      },
      listModels,
      stop: async () => [],
      forceStop,
    };

    try {
      await expect(
        probeEntitlement(client, baseDirectory, { probeMs: 50, shutdownMs: 500 }),
      ).rejects.toBeInstanceOf(SdkCleanupError);
      const stopsBeforeLateStartup = forceStop.mock.calls.length;
      expect(stopsBeforeLateStartup).toBeGreaterThan(0);
      finishStartup();
      await vi.waitFor(() => expect(forceStop).toHaveBeenCalledTimes(stopsBeforeLateStartup + 1));
      await vi.waitFor(() => expect(child?.signalCode).toBe("SIGKILL"));
      expect(listModels).not.toHaveBeenCalled();
      await expect(stat(baseDirectory)).resolves.toBeDefined();
    } finally {
      if (child && child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
        await vi.waitFor(() => expect(child?.signalCode).toBe("SIGKILL"));
      }
      await rm(baseDirectory, { recursive: true, force: true });
    }
  });

  it("returns within a bounded window when SDK startup never settles", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const forceStop = vi.fn(async () => {});
    const client: EntitlementProbeClient = {
      start: () => new Promise<void>(() => {}),
      listModels: vi.fn(async () => [{ id: hydraFusionModel }]),
      stop: async () => [],
      forceStop,
    };

    try {
      const startedAt = Date.now();
      const failure = await probeEntitlement(client, baseDirectory, {
        probeMs: 50,
        shutdownMs: 100,
      }).catch((error: unknown) => error);
      expect(Date.now() - startedAt).toBeLessThan(1_000);
      expect(failure).toBeInstanceOf(SdkCleanupError);
      const causes = ((failure as SdkCleanupError).cause as AggregateError).errors;
      expect(causes.map((cause) => (cause as Error).message)).toContain(
        "SDK startup settlement timed out after 100ms",
      );
      // A runtime may appear after any stop, so stopping repeats until the settlement window ends.
      expect(forceStop.mock.calls.length).toBeGreaterThan(1);
      await expect(stat(baseDirectory)).resolves.toBeDefined();
    } finally {
      await rm(baseDirectory, { recursive: true, force: true });
    }
  });

  it("kills a runtime whose handshake never completes and settles startup", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const { probeClient, startup } = trackStartup(
      syntheticClient(baseDirectory, "stubborn", "never"),
    );

    try {
      // The window must outlast child Node startup on a loaded host so the runtime records its PID
      // before the deadline; a never-completing handshake still makes the deadline fire.
      await expect(
        probeEntitlement(probeClient, baseDirectory, { probeMs: 2_000, shutdownMs: 1_000 }),
      ).rejects.toBeInstanceOf(SdkCleanupError);
      await expect(startup()).rejects.toBeDefined();
      const pid = Number(await readFile(join(baseDirectory, "runtime.pid"), "utf8"));
      expect(Number.isInteger(pid) && pid > 0).toBe(true);
      await expectProcessGone(pid);
      await expect(stat(baseDirectory)).resolves.toBeDefined();
    } finally {
      await rm(baseDirectory, { recursive: true, force: true });
    }
  }, 15_000);

  it("kills a runtime spawned after the deadline whose handshake never completes", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    const probeMs = 50;
    const spawnDelayMs = 300;
    const sdkClient = syntheticClient(baseDirectory, "stubborn", "never");
    let startup: Promise<void> | undefined;
    let spawnedAfterMs: number | undefined;
    const probeStartedAt = Date.now();
    // Models SDK runtime-path resolution outlasting the deadline: no child exists at the first stop.
    const probeClient: EntitlementProbeClient = {
      start: async () => {
        await new Promise((resolve) => setTimeout(resolve, spawnDelayMs));
        spawnedAfterMs = Date.now() - probeStartedAt;
        startup = sdkClient.start();
        return startup;
      },
      listModels: () => sdkClient.listModels(),
      stop: () => sdkClient.stop(),
      forceStop: () => sdkClient.forceStop(),
    };

    try {
      await expect(
        // The retry gap lets the late runtime record its PID before the next forced stop.
        probeEntitlement(probeClient, baseDirectory, {
          probeMs,
          shutdownMs: 3_000,
          stopRetryMs: 1_000,
        }),
      ).rejects.toBeInstanceOf(SdkCleanupError);
      expect(spawnedAfterMs).toBeGreaterThan(probeMs);
      const pid = Number(await readFile(join(baseDirectory, "runtime.pid"), "utf8"));
      expect(Number.isInteger(pid) && pid > 0).toBe(true);
      await expectProcessGone(pid);
      await expect(startup).rejects.toBeDefined();
      await expect(stat(baseDirectory)).resolves.toBeDefined();
    } finally {
      await sdkClient.forceStop();
      await rm(baseDirectory, { recursive: true, force: true });
    }
  }, 10_000);
});
