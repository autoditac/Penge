import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

const cli = fileURLToPath(new URL("../dist/check-entitlement.js", import.meta.url));
const preload = fileURLToPath(new URL("./fixtures/entitlement-cli-preload.mjs", import.meta.url));
const token = "synthetic-explicit-token";

function startDiagnostic(root: string, scenario: "startup" | "listing" | "delayed") {
  const child = spawn(process.execPath, ["--import", preload, cli], {
    env: {
      PATH: process.env.PATH,
      TMPDIR: root,
      PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN: token,
      PENGE_FAKE_ROOT: root,
      PENGE_FAKE_SCENARIO: scenario,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
    stderr += chunk;
  });
  const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve) => {
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
  return { child, exited, output: () => ({ stdout, stderr }) };
}

async function waitForFile(path: string): Promise<void> {
  await vi.waitFor(() => expect(existsSync(path)).toBe(true), { timeout: 8_000, interval: 25 });
}

async function waitForPhase(root: string, phase: string): Promise<void> {
  await vi.waitFor(async () => expect(await readFile(join(root, "phase"), "utf8")).toBe(phase), {
    timeout: 8_000,
    interval: 25,
  });
}

async function waitForExit(
  exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }>,
): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      exited,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("Diagnostic did not exit within 10 seconds")),
          10_000,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function runtimePid(root: string): Promise<number> {
  const pid = Number(await readFile(join(root, "spawned.pid"), "utf8"));
  expect(Number.isInteger(pid) && pid > 0).toBe(true);
  return pid;
}

async function expectRuntimeGone(pid: number): Promise<void> {
  await vi.waitFor(
    () => {
      expect(() => process.kill(pid, 0)).toThrowError(expect.objectContaining({ code: "ESRCH" }));
    },
    { timeout: 3_000, interval: 25 },
  );
}

async function expectRetainedStorage(root: string): Promise<void> {
  const entries = await readdir(root);
  expect(entries.filter((entry) => entry.startsWith("penge-copilot-entitlement-"))).toHaveLength(1);
}

async function cleanup(
  child: ChildProcess,
  exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }>,
  root: string,
): Promise<void> {
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
  }
  await waitForExit(exited);
  const pidPath = join(root, "spawned.pid");
  if (existsSync(pidPath)) {
    const pid = Number(await readFile(pidPath, "utf8"));
    if (Number.isInteger(pid) && pid > 0) {
      try {
        process.kill(pid, 0);
        process.kill(-pid, "SIGKILL");
      } catch (error) {
        if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error;
      }
    }
  }
  await rm(root, { recursive: true, force: true });
}

describe.skipIf(process.platform === "win32")("entitlement CLI interruption", () => {
  it.each([
    { scenario: "startup", phase: "connect", signal: "SIGINT", code: 130 },
    { scenario: "listing", phase: "models.list", signal: "SIGTERM", code: 143 },
  ] as const)(
    "cleans up a stubborn runtime when $signal interrupts $scenario",
    async ({ scenario, phase, signal, code }) => {
      const root = await mkdtemp(join(tmpdir(), "penge-entitlement-cli-test-"));
      const diagnostic = startDiagnostic(root, scenario);
      try {
        await waitForPhase(root, phase);
        const pid = await runtimePid(root);
        expect(diagnostic.child.kill(signal)).toBe(true);
        if (scenario === "listing") {
          await waitForFile(join(root, "stop-called"));
          expect(diagnostic.child.kill("SIGINT")).toBe(true);
        }
        expect(await waitForExit(diagnostic.exited)).toEqual({ code, signal: null });
        const { stdout, stderr } = diagnostic.output();
        expect(stdout).toBe("");
        expect(stderr).toContain(`interrupted by ${signal}`);
        expect(stderr).toContain("temporary storage was retained");
        expect(stderr).not.toContain(token);
        await expectRuntimeGone(pid);
        await expectRetainedStorage(root);
      } finally {
        await cleanup(diagnostic.child, diagnostic.exited, root);
      }
    },
    20_000,
  );

  it("stops a runtime spawned after interruption while startup is pending", async () => {
    const root = await mkdtemp(join(tmpdir(), "penge-entitlement-cli-test-"));
    const diagnostic = startDiagnostic(root, "delayed");
    try {
      await waitForFile(join(root, "start-waiting"));
      expect(diagnostic.child.kill("SIGINT")).toBe(true);
      await waitForFile(join(root, "force-stop-called"));
      await writeFile(join(root, "release-start"), "ready");
      await waitForFile(join(root, "spawned.pid"));
      const pid = await runtimePid(root);
      expect(await waitForExit(diagnostic.exited)).toEqual({ code: 130, signal: null });
      expect(diagnostic.output().stdout).toBe("");
      await expectRuntimeGone(pid);
      await expectRetainedStorage(root);
      if (existsSync(join(root, "phase"))) {
        expect(await readFile(join(root, "phase"), "utf8")).not.toBe("models.list");
      }
    } finally {
      await cleanup(diagnostic.child, diagnostic.exited, root);
    }
  }, 20_000);

  it("exits before an indefinitely delayed startup can spawn after interruption", async () => {
    const root = await mkdtemp(join(tmpdir(), "penge-entitlement-cli-test-"));
    const diagnostic = startDiagnostic(root, "delayed");
    try {
      await waitForFile(join(root, "start-waiting"));
      expect(diagnostic.child.kill("SIGTERM")).toBe(true);
      await waitForFile(join(root, "force-stop-called"));
      expect(await waitForExit(diagnostic.exited)).toEqual({ code: 143, signal: null });
      expect(diagnostic.output().stdout).toBe("");
      await expectRetainedStorage(root);
      await writeFile(join(root, "release-start"), "ready");
      await new Promise((resolve) => setTimeout(resolve, 200));
      expect(existsSync(join(root, "spawned.pid"))).toBe(false);
    } finally {
      await cleanup(diagnostic.child, diagnostic.exited, root);
    }
  }, 20_000);
});
