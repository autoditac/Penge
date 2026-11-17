import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { CopilotClient, RuntimeConnection } from "@github/copilot-sdk";
import { describe, expect, it, vi } from "vitest";

import {
  EntitlementProbeTimeoutError,
  probeEntitlement,
  type EntitlementProbeClient,
} from "../src/entitlement.js";
import { SdkCleanupError, hydraFusionModel } from "../src/index.js";

const fixture = fileURLToPath(new URL("./fixtures/unresponsive-runtime.mjs", import.meta.url));

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
      expect(forceStop).toHaveBeenCalledOnce();
      finishStartup();
      await vi.waitFor(() => expect(forceStop).toHaveBeenCalledTimes(2));
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
      expect(forceStop).toHaveBeenCalledOnce();
      await expect(stat(baseDirectory)).resolves.toBeDefined();
    } finally {
      await rm(baseDirectory, { recursive: true, force: true });
    }
  });

  it.each([1, 300])(
    "kills a runtime whose handshake never completes and settles startup (deadline %ims)",
    async (probeMs) => {
      const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
      const { probeClient, startup } = trackStartup(
        syntheticClient(baseDirectory, "stubborn", "never"),
      );

      try {
        await expect(
          probeEntitlement(probeClient, baseDirectory, { probeMs, shutdownMs: 1_000 }),
        ).rejects.toBeInstanceOf(SdkCleanupError);
        // The runtime was spawned before the deadline, so startup must already have settled.
        const pending = startup();
        expect(pending).toBeDefined();
        const settled = await Promise.race([
          pending?.then(
            () => "resolved",
            () => "rejected",
          ),
          new Promise((resolve) => setTimeout(() => resolve("pending"), 0)),
        ]);
        expect(settled).toBe("rejected");
        const pidText = await readFile(join(baseDirectory, "runtime.pid"), "utf8").catch(
          (error: unknown) => {
            // With a 1ms deadline the runtime may be killed before it can record its PID.
            if (probeMs === 1 && (error as NodeJS.ErrnoException).code === "ENOENT") return null;
            throw error;
          },
        );
        if (pidText !== null) await expectProcessGone(Number(pidText));
        await expect(stat(baseDirectory)).resolves.toBeDefined();
      } finally {
        await rm(baseDirectory, { recursive: true, force: true });
      }
    },
    10_000,
  );
});
