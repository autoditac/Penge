import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CopilotClient } from "@github/copilot-sdk";

import { diagnosticClientOptions, probeEntitlement } from "./entitlement.js";
import { PengeError } from "./index.js";

let client: CopilotClient | undefined;

async function main(): Promise<void> {
  const baseDirectory = await mkdtemp(join(tmpdir(), "penge-copilot-entitlement-"));
  try {
    client = new CopilotClient(diagnosticClientOptions(process.env, baseDirectory));
  } catch (error) {
    await rm(baseDirectory, { recursive: true, force: true });
    throw error;
  }

  const result = await probeEntitlement(client, baseDirectory);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.entitled ? 0 : 2;
}

try {
  await main();
} catch (error) {
  const message =
    error instanceof PengeError
      ? error.message
      : "Entitlement probe failed; no model conclusion was made";
  process.stderr.write(`${message}\n`);
  if (client !== undefined) {
    // An unsettled SDK startup can still spawn a runtime while this process lives. forceStop
    // sends SIGKILL synchronously, and exiting in the same turn prevents any later spawn.
    void client.forceStop().catch(() => undefined);
    process.exit(1);
  }
  process.exitCode = 1;
}
