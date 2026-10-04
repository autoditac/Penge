#!/usr/bin/env node

import pino from "pino";

import { loadConfig } from "./config.js";
import { verifyMcpServerContract } from "./mcp.js";
import { GitHubOAuthFlow, UserTokenService } from "./oauth.js";
import { ChatRuntime } from "./runtime.js";
import { GitHubCopilotRuntime } from "./sdk.js";
import { startChatServer } from "./server.js";
import { PostgresChatStore } from "./store.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = pino({ level: "info" });
  const store = await PostgresChatStore.connect(config.databaseUrl, config.databaseRole);
  try {
    if (config.productionEnabled) {
      await verifyMcpServerContract(config);
    }
    const tokenService = new UserTokenService(config, store);
    const runtime = new ChatRuntime(config, new GitHubCopilotRuntime(config), tokenService, store);
    const server = await startChatServer(config, {
      runtime,
      oauth: new GitHubOAuthFlow(config, store),
      logger,
    });
    const shutdown = async (): Promise<void> => {
      await server.close();
      await store.close();
    };
    process.once("SIGINT", () => void shutdown().then(() => process.exit(0)));
    process.once("SIGTERM", () => void shutdown().then(() => process.exit(0)));
  } catch (error) {
    await store.close();
    throw error;
  }
}

main().catch((error: unknown) => {
  const logger = pino({ level: "error" });
  logger.error(
    { errorType: error instanceof Error ? error.name : "UnknownError" },
    "chat service failed",
  );
  process.exitCode = 1;
});
