/** TanStack Query hooks for the read API.
 *
 * In demo mode (`VITE_PENGE_DEMO=true`) the hooks resolve deterministic
 * synthetic fixtures through a dynamic import, keeping fixtures out of the
 * production bundle's critical path while exercising identical UI states.
 */

import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import {
  demoMode,
  fetchAccounts,
  fetchAllocation,
  fetchCashflowDaily,
  fetchFreshness,
  fetchNetWorthByAccount,
  fetchNetWorthTotal,
} from "./client";
import type { SeriesParams } from "./client";
import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  CashflowSeriesResponse,
  FreshnessResponse,
  NetWorthSeriesResponse,
  NetWorthTotalSeriesResponse,
} from "./schemas";

const staleTimeMs = 60_000;

export function useAccounts(): UseQueryResult<readonly AccountSummary[], Error> {
  return useQuery({
    queryKey: ["accounts"],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoAccounts;
      }
      return fetchAccounts();
    },
  });
}

export function useAllocation(by: AllocationDimension): UseQueryResult<AllocationResponse, Error> {
  return useQuery({
    queryKey: ["allocation", by],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoAllocation(by);
      }
      return fetchAllocation(by);
    },
  });
}

export function useNetWorthTotal(
  params: SeriesParams,
): UseQueryResult<NetWorthTotalSeriesResponse, Error> {
  return useQuery({
    queryKey: ["net-worth-total", params.since ?? null, params.until ?? null, params.limit ?? null],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoNetWorthTotal;
      }
      return fetchNetWorthTotal(params);
    },
  });
}

export function useNetWorthByAccount(
  params: SeriesParams,
): UseQueryResult<NetWorthSeriesResponse, Error> {
  return useQuery({
    queryKey: [
      "net-worth-by-account",
      params.since ?? null,
      params.until ?? null,
      params.limit ?? null,
    ],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoNetWorthByAccount;
      }
      return fetchNetWorthByAccount(params);
    },
  });
}

export function useCashflowDaily(
  params: SeriesParams,
): UseQueryResult<CashflowSeriesResponse, Error> {
  return useQuery({
    queryKey: ["cashflow-daily", params.since ?? null, params.until ?? null, params.limit ?? null],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoCashflowDaily;
      }
      return fetchCashflowDaily(params);
    },
  });
}

export function useFreshness(): UseQueryResult<FreshnessResponse, Error> {
  return useQuery({
    queryKey: ["freshness"],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoFreshness;
      }
      return fetchFreshness();
    },
  });
}
