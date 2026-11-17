import { rm } from "node:fs/promises";

import type { CopilotClient, ModelInfo } from "@github/copilot-sdk";

import {
  PengeError,
  SdkCleanupError,
  assertSdkCleanupSucceeded,
  hydraFusionModel,
} from "./index.js";

export class EntitlementProbeTimeoutError extends PengeError {
  override get name(): string {
    return "EntitlementProbeTimeoutError";
  }

  override get code(): string {
    return "chat/entitlement_probe_timeout";
  }
}

export interface EntitlementProbeClient {
  start: CopilotClient["start"];
  listModels: () => Promise<readonly Pick<ModelInfo, "id">[]>;
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
}

const defaultTimeouts: ProbeTimeouts = {
  probeMs: 30_000,
  shutdownMs: 5_000,
};

async function withDeadline<T>(
  operation: Promise<T>,
  timeoutMs: number,
  phase: string,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
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
  }
}

export async function probeEntitlement(
  client: EntitlementProbeClient,
  baseDirectory: string,
  timeouts: ProbeTimeouts = defaultTimeouts,
): Promise<EntitlementProbeResult> {
  let startCompleted = false;
  let probeActive = true;
  let probeFailed = false;
  let probeError: unknown;
  let result: EntitlementProbeResult | undefined;

  try {
    const operation = (async () => {
      await client.start();
      if (!probeActive) {
        await withDeadline(client.forceStop(), timeouts.shutdownMs, "Late SDK shutdown");
        throw new EntitlementProbeTimeoutError("SDK startup completed after the probe deadline");
      }
      startCompleted = true;
      return client.listModels();
    })();
    const models = await withDeadline(operation, timeouts.probeMs, "Entitlement probe");
    const matchCount = models.filter((model) => model.id === hydraFusionModel).length;
    result = { exactModel: hydraFusionModel, entitled: matchCount === 1, matchCount };
  } catch (error) {
    probeFailed = true;
    probeError = error;
  } finally {
    probeActive = false;
  }

  const cleanupErrors: unknown[] = [];
  if (startCompleted) {
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
    if (probeFailed) cleanupErrors.unshift(probeError);
    throw new SdkCleanupError(
      "SDK termination could not be confirmed; isolated temporary storage was retained",
      { cause: new AggregateError(cleanupErrors, "Entitlement probe or SDK cleanup failed") },
    );
  }

  await rm(baseDirectory, { recursive: true, force: true });
  if (probeFailed) throw probeError;
  if (result === undefined) throw new PengeError("Entitlement probe produced no result");
  return result;
}
