/** Typed fetch client for the Penge read API (ADR-0035, ADR-0036).
 *
 * Every response is validated with the zod schemas in `schemas.ts` before it
 * reaches the UI. Failures surface as `PengeApiError` with a machine code.
 */

import type { ZodType } from "zod";

import { PengeApiError } from "../errors";
import {
  accountsResponseSchema,
  allocationResponseSchema,
  cashflowSeriesResponseSchema,
  freshnessResponseSchema,
  netWorthTotalSeriesResponseSchema,
} from "./schemas";
import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  CashflowSeriesResponse,
  FreshnessResponse,
  NetWorthTotalSeriesResponse,
} from "./schemas";

export const apiBaseUrl: string = import.meta.env.VITE_PENGE_API_URL ?? "http://127.0.0.1:8000";

/** True when the UI serves deterministic synthetic fixtures instead of the API. */
export const demoMode: boolean = import.meta.env.VITE_PENGE_DEMO === "true";

export type SeriesParams = {
  readonly since?: string;
  readonly until?: string;
  readonly limit?: number;
};

async function getJson<T>(
  path: string,
  params: Readonly<Record<string, string | number | undefined>>,
  schema: ZodType<T>,
): Promise<T> {
  const url = new URL(path, apiBaseUrl);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (cause) {
    throw new PengeApiError(
      "api_unreachable",
      `Penge API at ${apiBaseUrl} is unreachable: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }

  if (!response.ok) {
    throw new PengeApiError(
      "api_http_error",
      `Penge API returned ${response.status} for ${path}.`,
      response.status,
    );
  }

  const payload: unknown = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new PengeApiError(
      "api_schema_mismatch",
      `Penge API response for ${path} failed schema validation: ${parsed.error.message}`,
      response.status,
    );
  }
  return parsed.data;
}

export function fetchAccounts(): Promise<readonly AccountSummary[]> {
  return getJson("/accounts", {}, accountsResponseSchema);
}

export function fetchAllocation(by: AllocationDimension): Promise<AllocationResponse> {
  return getJson("/allocation/current", { by }, allocationResponseSchema);
}

export function fetchNetWorthTotal(params: SeriesParams): Promise<NetWorthTotalSeriesResponse> {
  return getJson(
    "/net-worth/daily",
    { group: "total", ...params },
    netWorthTotalSeriesResponseSchema,
  );
}

export function fetchCashflowDaily(params: SeriesParams): Promise<CashflowSeriesResponse> {
  return getJson("/cashflow/daily", { ...params }, cashflowSeriesResponseSchema);
}

export function fetchFreshness(): Promise<FreshnessResponse> {
  return getJson("/meta/freshness", {}, freshnessResponseSchema);
}
