import { rm } from "node:fs/promises";

import {
  RuntimeConnection,
  type CopilotClient,
  type CopilotClientOptions,
  type ModelInfo,
} from "@github/copilot-sdk";
import { z } from "zod/v3";

import {
  PengeError,
  SdkCleanupError,
  assertSdkCleanupSucceeded,
  evaluateHydraFusionAvailability,
  hydraFusionModel,
  sanitizeRuntimeEnvironment,
} from "./index.js";

export function diagnosticClientOptions(
  environment: NodeJS.ProcessEnv,
  baseDirectory: string,
): CopilotClientOptions {
  const token = z.string().trim().min(1).safeParse(environment.PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN);
  if (!token.success) {
    throw new PengeError(
      "Set PENGE_CHAT_DIAGNOSTIC_GITHUB_TOKEN to your own diagnostic credential",
    );
  }
  return {
    connection: RuntimeConnection.forStdio(),
    mode: "empty",
    baseDirectory,
    gitHubToken: token.data,
    useLoggedInUser: false,
    env: sanitizeRuntimeEnvironment(environment),
    logLevel: "error",
  };
}

export class EntitlementProbeTimeoutError extends PengeError {
  override get name(): string {
    return "EntitlementProbeTimeoutError";
  }

  override get code(): string {
    return "chat/entitlement_probe_timeout";
  }
}

export class EntitlementProbeInterruptedError extends PengeError {
  constructor() {
    super("Entitlement probe interrupted; no model conclusion was made");
  }

  override get name(): string {
    return "EntitlementProbeInterruptedError";
  }

  override get code(): string {
    return "chat/entitlement_probe_interrupted";
  }
}

export interface EntitlementProbeClient {
  start: CopilotClient["start"];
  listModels: () => Promise<readonly Pick<ModelInfo, "id" | "policy">[]>;
  stop: CopilotClient["stop"];
  forceStop: CopilotClient["forceStop"];
}

export interface EntitlementProbeResult {
  exactModel: typeof hydraFusionModel;
  entitled: boolean;
  matchCount: number;
}

interface ProbeTimeouts {
  probeMs: number;
  shutdownMs: number;
  stopRetryMs?: number;
}

const defaultTimeouts: ProbeTimeouts = {
  probeMs: 30_000,
  shutdownMs: 5_000,
};

const defaultStopRetryMs = 50;

function sleep(ms: number): { done: Promise<void>; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const done = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, ms);
  });
  return { done, cancel: () => clearTimeout(timer) };
}

/**
 * SDK 1.0.16 may still be resolving its bundled runtime when the probe deadline fires, so a
 * forced stop can run before the child exists and the child's handshake may never complete.
 * Keep forcing a stop until startup settles; killing the child rejects the pending handshake.
 */
async function stopUntilStartupSettles(
  client: EntitlementProbeClient,
  startup: Promise<unknown>,
  timeouts: ProbeTimeouts,
): Promise<void> {
  let settled = false;
  const settlement = startup.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    },
  );
  const deadline = Date.now() + timeouts.shutdownMs;
  const retryMs = timeouts.stopRetryMs ?? defaultStopRetryMs;
  while (!settled) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      throw new EntitlementProbeTimeoutError(
        `SDK startup settlement timed out after ${timeouts.shutdownMs}ms`,
      );
    }
    await withDeadline(client.forceStop(), remaining, "Forced SDK shutdown");
    const pause = sleep(Math.min(retryMs, Math.max(deadline - Date.now(), 0)));
    try {
      await Promise.race([settlement, pause.done]);
    } finally {
      pause.cancel();
    }
  }
}

async function withDeadline<T>(
  operation: Promise<T>,
  timeoutMs: number,
  phase: string,
  signal?: AbortSignal,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const interruption =
    signal === undefined
      ? undefined
      : new Promise<never>((_, reject) => {
          onAbort = () => reject(new EntitlementProbeInterruptedError());
          if (signal.aborted) {
            onAbort();
          } else {
            signal.addEventListener("abort", onAbort, { once: true });
          }
        });
  try {
    return await Promise.race([
      ...(interruption === undefined ? [] : [interruption]),
      operation,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new EntitlementProbeTimeoutError(`${phase} timed out after ${timeoutMs}ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    if (signal !== undefined && onAbort !== undefined) {
      signal.removeEventListener("abort", onAbort);
    }
  }
}

export async function probeEntitlement(
  client: EntitlementProbeClient,
  baseDirectory: string,
  timeouts: ProbeTimeouts = defaultTimeouts,
  signal?: AbortSignal,
): Promise<EntitlementProbeResult> {
  let startInvoked = false;
  let startCompleted = false;
  let probeActive = true;
  let probeFailed = false;
  let probeError: unknown;
  let result: EntitlementProbeResult | undefined;
  let operation: Promise<readonly Pick<ModelInfo, "id" | "policy">[]> | undefined;

  try {
    if (signal?.aborted) throw new EntitlementProbeInterruptedError();
    startInvoked = true;
    operation = (async () => {
      await client.start();
      if (!probeActive || signal?.aborted) {
        await withDeadline(client.forceStop(), timeouts.shutdownMs, "Late SDK shutdown");
        if (signal?.aborted) throw new EntitlementProbeInterruptedError();
        throw new EntitlementProbeTimeoutError("SDK startup completed after the probe deadline");
      }
      startCompleted = true;
      return client.listModels();
    })();
    const models = await withDeadline(operation, timeouts.probeMs, "Entitlement probe", signal);
    result = { exactModel: hydraFusionModel, ...evaluateHydraFusionAvailability(models) };
  } catch (error) {
    probeFailed = true;
    probeError = error;
  } finally {
    probeActive = false;
  }

  const cleanupErrors: unknown[] = [];
  if (startCompleted || !startInvoked) {
    try {
      const errors = await withDeadline(client.stop(), timeouts.shutdownMs, "SDK shutdown");
      assertSdkCleanupSucceeded(errors);
    } catch (error) {
      cleanupErrors.push(error);
    }
  } else {
    cleanupErrors.push(new Error("SDK startup did not complete before cleanup"));
  }

  if (cleanupErrors.length > 0) {
    // SDK 1.0.16 forceStop sends SIGKILL but does not confirm the child's exit.
    try {
      await withDeadline(client.forceStop(), timeouts.shutdownMs, "Forced SDK shutdown");
    } catch (error) {
      cleanupErrors.push(error);
    }
    if (!startCompleted && operation !== undefined) {
      try {
        await stopUntilStartupSettles(client, operation, timeouts);
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    if (probeFailed) cleanupErrors.unshift(probeError);
    throw new SdkCleanupError(
      "SDK termination could not be confirmed; isolated temporary storage was retained",
      { cause: new AggregateError(cleanupErrors, "Entitlement probe or SDK cleanup failed") },
    );
  }

  await rm(baseDirectory, { recursive: true, force: true });
  if (probeFailed) throw probeError;
  if (signal?.aborted) throw new EntitlementProbeInterruptedError();
  if (result === undefined) throw new PengeError("Entitlement probe produced no result");
  return result;
}
