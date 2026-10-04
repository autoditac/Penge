import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CopilotClient } from "@github/copilot-sdk";

import { assertSdkCleanupSucceeded, hydraFusionModel } from "./index.js";

const baseDirectory = await mkdtemp(join(tmpdir(), "penge-copilot-entitlement-"));
const client = new CopilotClient({
  mode: "empty",
  baseDirectory,
  useLoggedInUser: true,
  logLevel: "error",
});

let result: {
  exactModel: typeof hydraFusionModel;
  entitled: boolean;
  matchCount: number;
};
let stopErrors: Error[] = [];

try {
  await client.start();
  const models = await client.listModels();
  const matchCount = models.filter((model) => model.id === hydraFusionModel).length;
  result = {
    exactModel: hydraFusionModel,
    entitled: matchCount === 1,
    matchCount,
  };
} finally {
  try {
    stopErrors = await client.stop();
  } finally {
    await rm(baseDirectory, { recursive: true, force: true });
  }
}

assertSdkCleanupSucceeded(stopErrors);
process.stdout.write(`${JSON.stringify(result)}\n`);
process.exitCode = result.entitled ? 0 : 2;
