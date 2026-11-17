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

function syntheticClient(baseDirectory: string, shutdown: "graceful" | "stubborn"): CopilotClient {
  return new CopilotClient({
    connection: RuntimeConnection.forStdio({ path: process.execPath, args: [fixture] }),
    mode: "empty",
    baseDirectory,
    useLoggedInUser: false,
    logLevel: "none",
    env: {
      PENGE_FAKE_PID_FILE: join(baseDirectory, "runtime.pid"),
      PENGE_FAKE_SHUTDOWN: shutdown,
    },
  });
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
    await vi.waitFor(
      () => {
        expect(() => process.kill(pid, 0)).toThrowError(expect.objectContaining({ code: "ESRCH" }));
      },
      { timeout: 3_000, interval: 25 },
    );
    await rm(baseDirectory, { recursive: true, force: true });
  }, 10_000);

  it("does not list models if SDK startup finishes after the deadline", async () => {
    const baseDirectory = await mkdtemp(join(tmpdir(), "penge-entitlement-test-"));
    let finishStartup: () => void = () => {
      throw new Error("synthetic startup was not initialized");
    };
    const startup = new Promise<void>((resolve) => {
      finishStartup = resolve;
    });
    const listModels = vi.fn(async () => [{ id: hydraFusionModel }]);
    const forceStop = vi.fn(async () => {});
    const client: EntitlementProbeClient = {
      start: () => startup,
      listModels,
      stop: async () => [],
      forceStop,
    };

    await expect(
      probeEntitlement(client, baseDirectory, { probeMs: 50, shutdownMs: 500 }),
    ).rejects.toBeInstanceOf(SdkCleanupError);
    finishStartup();
    await Promise.resolve();
    expect(listModels).not.toHaveBeenCalled();
    expect(forceStop).toHaveBeenCalledOnce();
    await expect(stat(baseDirectory)).resolves.toBeDefined();
    await rm(baseDirectory, { recursive: true, force: true });
  });
});
