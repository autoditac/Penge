import { writeSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CopilotClient } from "@github/copilot-sdk";

import {
  EntitlementProbeInterruptedError,
  diagnosticClientOptions,
  probeEntitlement,
} from "./entitlement.js";
import { PengeError } from "./index.js";

let client: CopilotClient | undefined;
let interruptedBy: "SIGINT" | "SIGTERM" | undefined;
const interruption = new AbortController();

function interrupt(signal: "SIGINT" | "SIGTERM"): void {
  if (interruptedBy === undefined) {
    interruptedBy = signal;
    interruption.abort();
  }
}

process.on("SIGINT", () => interrupt("SIGINT"));
process.on("SIGTERM", () => interrupt("SIGTERM"));

async function main(signal: AbortSignal): Promise<void> {
  const baseDirectory = await mkdtemp(join(tmpdir(), "penge-copilot-entitlement-"));
  try {
    if (signal.aborted) throw new EntitlementProbeInterruptedError();
    client = new CopilotClient(diagnosticClientOptions(process.env, baseDirectory));
  } catch (error) {
    await rm(baseDirectory, { recursive: true, force: true });
    throw error;
  }

  const result = await probeEntitlement(client, baseDirectory, undefined, signal);
  if (signal.aborted) throw new EntitlementProbeInterruptedError();
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.entitled ? 0 : 2;
}

try {
  await main(interruption.signal);
} catch (error) {
  const message =
    error instanceof PengeError
      ? error.message
      : "Entitlement probe failed; no model conclusion was made";
  const exitCode = interruptedBy === "SIGINT" ? 130 : interruptedBy === "SIGTERM" ? 143 : 1;
  try {
    if (interruptedBy !== undefined) {
      writeSync(
        process.stderr.fd,
        `Entitlement probe interrupted by ${interruptedBy}; no model conclusion was made\n`,
      );
    }
    if (interruptedBy === undefined || !(error instanceof EntitlementProbeInterruptedError)) {
      writeSync(process.stderr.fd, `${message}\n`);
    }
  } finally {
    if (client !== undefined) {
      // The SDK sends SIGKILL synchronously; exiting in the same turn prevents a later spawn.
      void client.forceStop().catch(() => undefined);
      process.exit(exitCode);
    }
    process.exitCode = exitCode;
  }
}
