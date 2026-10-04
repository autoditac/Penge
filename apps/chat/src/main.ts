#!/usr/bin/env node

import pino from "pino";

import { loadConfig } from "./config.js";
import { closeServiceResources } from "./lifecycle.js";
import { verifyMcpServerContract } from "./mcp.js";
import { GitHubOAuthFlow, UserTokenService } from "./oauth.js";
import { ChatRuntime } from "./runtime.js";
import { GitHubCopilotRuntime } from "./sdk.js";
import { startChatServer } from "./server.js";
import { PostgresChatStore } from "./store.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = pino({ level: "info" });
  let shutdown: ((reason: string) => Promise<void>) | undefined;
  let poolFailed = false;
  const store = await PostgresChatStore.connect(config.databaseUrl, config.databaseRole, {
    timeoutMs: Math.min(config.requestTimeoutMs, 5_000),
    onPoolError: (error) => {
      poolFailed = true;
      process.exitCode = 1;
      logger.error(
        { operation: "database_pool", errorType: error.name },
        "chat database pool failed",
      );
      if (shutdown !== undefined) {
        void shutdown("database_pool");
      }
    },
  });
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
    let shuttingDown = false;
    shutdown = async (reason: string): Promise<void> => {
      if (shuttingDown) {
        return;
      }
      shuttingDown = true;
      try {
        await closeServiceResources(server, store);
      } catch (error) {
        logger.error(
          {
            operation: "shutdown",
            reason,
            errorType: error instanceof Error ? error.name : "UnknownError",
          },
          "chat service shutdown failed",
        );
        process.exitCode = 1;
      }
    };
    process.once("SIGINT", () => {
      void shutdown?.("SIGINT");
    });
    process.once("SIGTERM", () => {
      void shutdown?.("SIGTERM");
    });
    if (poolFailed) {
      void shutdown("database_pool");
    }
  } catch (error) {
    try {
      await store.close();
    } catch (closeError) {
      throw new AggregateError([error, closeError], "chat startup cleanup failed");
    }
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
