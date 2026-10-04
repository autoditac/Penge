import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CopilotClient } from "@github/copilot-sdk";

import { hydraFusionModel } from "./index.js";

const baseDirectory = await mkdtemp(join(tmpdir(), "penge-copilot-entitlement-"));
const client = new CopilotClient({
  mode: "empty",
  baseDirectory,
  useLoggedInUser: true,
  logLevel: "error",
});

try {
  await client.start();
  const models = await client.listModels();
  const matchCount = models.filter((model) => model.id === hydraFusionModel).length;
  process.stdout.write(
    `${JSON.stringify({
      exactModel: hydraFusionModel,
      entitled: matchCount === 1,
      matchCount,
    })}\n`,
  );
  process.exitCode = matchCount === 1 ? 0 : 2;
} finally {
  await client.stop();
  await rm(baseDirectory, { recursive: true, force: true });
}
