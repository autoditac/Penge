import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CopilotClient, RuntimeConnection } from "@github/copilot-sdk";

import { probeEntitlement } from "./entitlement.js";
import { PengeError } from "./index.js";

async function main(): Promise<void> {
  const baseDirectory = await mkdtemp(join(tmpdir(), "penge-copilot-entitlement-"));
  let client: CopilotClient;
  try {
    client = new CopilotClient({
      connection: RuntimeConnection.forStdio(),
      mode: "empty",
      baseDirectory,
      useLoggedInUser: true,
      logLevel: "error",
    });
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
  process.exitCode = 1;
}
