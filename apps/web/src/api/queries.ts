/** TanStack Query hooks for the read API.
 *
 * In demo mode (`VITE_PENGE_DEMO=true`) the hooks resolve deterministic
 * synthetic fixtures through a dynamic import, keeping fixtures out of the
 * production bundle's critical path while exercising identical UI states.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  authorizeConnection,
  commitImport,
  demoMode,
  discardImport,
  fetchAccounts,
  fetchAllocation,
  fetchAspsps,
  fetchBenchmarkDaily,
  fetchBenchmarks,
  fetchCashflowDaily,
  fetchConnections,
  fetchFees,
  fetchFreshness,
  fetchImportSession,
  fetchImportSessions,
  fetchImportSuggestions,
  fetchNetWorthByAccount,
  fetchNetWorthTotal,
  fetchReturnsDaily,
  fetchReturnsSummary,
  patchImportRow,
  startConnectionLink,
  syncConnection,
  uploadImport,
} from "./client";
import type {
  AuthorizeConnectionInput,
  CommitOptions,
  ReturnsParams,
  RowPatch,
  SeriesParams,
  UploadImportOptions,
} from "./client";
import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  AspspListResponse,
  BenchmarkInfo,
  BenchmarkSeriesResponse,
  CashflowSeriesResponse,
  CommitResponse,
  Connection,
  ConnectionListResponse,
  FeesResponse,
  FreshnessResponse,
  ImportRow,
  ImportSession,
  ImportSessionList,
  ImportSessionWithRows,
  LinkResponse,
  NetWorthSeriesResponse,
  NetWorthTotalSeriesResponse,
  ReturnsSeriesResponse,
  ReturnsSummaryResponse,
  SuggestionsResponse,
  SyncResponse,
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

/* ---- returns, benchmarks, fees (#206) ---- */

export function useReturnsDaily(
  params: ReturnsParams,
): UseQueryResult<ReturnsSeriesResponse, Error> {
  return useQuery({
    queryKey: [
      "returns-daily",
      params.scope ?? null,
      params.scopeKey ?? null,
      params.since ?? null,
      params.until ?? null,
      params.limit ?? null,
      params.offset ?? null,
    ],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoReturnsDaily(params.scope ?? "household");
      }
      return fetchReturnsDaily(params);
    },
  });
}

export function useReturnsSummary(
  params: ReturnsParams,
): UseQueryResult<ReturnsSummaryResponse, Error> {
  return useQuery({
    queryKey: ["returns-summary", params.scope ?? null, params.since ?? null, params.until ?? null],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoReturnsSummary(params.scope ?? "account");
      }
      return fetchReturnsSummary(params);
    },
  });
}

export function useBenchmarks(): UseQueryResult<readonly BenchmarkInfo[], Error> {
  return useQuery({
    queryKey: ["benchmarks"],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoBenchmarks;
      }
      return fetchBenchmarks();
    },
  });
}

export function useBenchmarkDaily(
  instrumentId: string | null,
  params: SeriesParams,
): UseQueryResult<BenchmarkSeriesResponse, Error> {
  return useQuery({
    queryKey: [
      "benchmark-daily",
      instrumentId,
      params.since ?? null,
      params.until ?? null,
      params.limit ?? null,
    ],
    enabled: instrumentId !== null,
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (instrumentId === null) {
        throw new Error("no benchmark selected");
      }
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoBenchmarkDaily(instrumentId);
      }
      return fetchBenchmarkDaily(instrumentId, params);
    },
  });
}

export function useFees(params: SeriesParams): UseQueryResult<FeesResponse, Error> {
  return useQuery({
    queryKey: ["fees", params.since ?? null, params.until ?? null],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const fixtures = await import("../demo/fixtures");
        return fixtures.demoFees;
      }
      return fetchFees(params);
    },
  });
}

/* ---- import sessions (#207/#208) ---- */

export function useImportSessions(): UseQueryResult<ImportSessionList, Error> {
  return useQuery({
    queryKey: ["imports"],
    staleTime: 5_000,
    queryFn: async () => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoListImports();
      }
      return fetchImportSessions();
    },
  });
}

export function useImportSession(
  sessionId: string | null,
): UseQueryResult<ImportSessionWithRows, Error> {
  return useQuery({
    queryKey: ["import", sessionId],
    enabled: sessionId !== null,
    staleTime: 0,
    queryFn: async () => {
      if (sessionId === null) {
        throw new Error("no import session selected");
      }
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoGetImport(sessionId);
      }
      return fetchImportSession(sessionId);
    },
  });
}

type UploadVariables = {
  readonly file: File;
  readonly options: UploadImportOptions;
};

export function useUploadImport(): UseMutationResult<
  ImportSessionWithRows,
  Error,
  UploadVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, options }: UploadVariables) => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoUploadImport(file, options.source);
      }
      return uploadImport(file, options);
    },
    onSuccess: (session) => {
      queryClient.setQueryData(["import", session.id], session);
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
}

type PatchRowVariables = {
  readonly sessionId: string;
  readonly rowId: string;
  readonly patch: RowPatch;
};

export function usePatchImportRow(): UseMutationResult<ImportRow, Error, PatchRowVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ sessionId, rowId, patch }: PatchRowVariables) => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoPatchImportRow(sessionId, rowId, patch);
      }
      return patchImportRow(sessionId, rowId, patch);
    },
    onSuccess: (_row, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["import", variables.sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
}

type CommitVariables = {
  readonly sessionId: string;
  readonly options: CommitOptions;
};

/** POST /imports/{id}/suggestions as a mutation: suggestions are an explicit
 * user action, not background data, and the call spawns an MCP subprocess
 * server-side. A 503 means the AI layer is unconfigured — the wizard
 * degrades to manual review. */
export function useImportSuggestions(): UseMutationResult<SuggestionsResponse, Error, string> {
  return useMutation({
    mutationFn: async (sessionId: string) => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoSuggestImports(sessionId);
      }
      return fetchImportSuggestions(sessionId);
    },
  });
}

export function useCommitImport(): UseMutationResult<CommitResponse, Error, CommitVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ sessionId, options }: CommitVariables) => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoCommitImport(sessionId);
      }
      return commitImport(sessionId, options);
    },
    onSuccess: (_response, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["import", variables.sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
}

export function useDiscardImport(): UseMutationResult<ImportSession, Error, string> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      if (demoMode) {
        const store = await import("../demo/importsStore");
        return store.demoDiscardImport(sessionId);
      }
      return discardImport(sessionId);
    },
    onSuccess: (_session, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: ["import", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
}

/* ---- bank connections (Enable Banking, #230) ---- */

export function useAspsps(): UseQueryResult<AspspListResponse, Error> {
  return useQuery({
    queryKey: ["connections-aspsps"],
    staleTime: staleTimeMs,
    queryFn: async () => {
      if (demoMode) {
        const store = await import("../demo/connectionsStore");
        return store.demoListAspsps();
      }
      return fetchAspsps();
    },
  });
}

export function useConnections(): UseQueryResult<ConnectionListResponse, Error> {
  return useQuery({
    queryKey: ["connections"],
    staleTime: 5_000,
    queryFn: async () => {
      if (demoMode) {
        const store = await import("../demo/connectionsStore");
        return store.demoListConnections();
      }
      return fetchConnections();
    },
  });
}

type StartLinkVariables = {
  readonly provider: string;
  readonly entityName: string;
};

export function useStartConnectionLink(): UseMutationResult<
  LinkResponse,
  Error,
  StartLinkVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ provider, entityName }: StartLinkVariables) => {
      if (demoMode) {
        const store = await import("../demo/connectionsStore");
        return store.demoStartLink(provider, entityName);
      }
      return startConnectionLink(provider, entityName);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

export function useAuthorizeConnection(): UseMutationResult<
  Connection,
  Error,
  AuthorizeConnectionInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: AuthorizeConnectionInput) => {
      if (demoMode) {
        const store = await import("../demo/connectionsStore");
        return store.demoAuthorize(input);
      }
      return authorizeConnection(input);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

type SyncConnectionVariables = {
  readonly connectionId: string;
  readonly days?: number | undefined;
};

export function useSyncConnection(): UseMutationResult<
  SyncResponse,
  Error,
  SyncConnectionVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ connectionId, days }: SyncConnectionVariables) => {
      if (demoMode) {
        const store = await import("../demo/connectionsStore");
        return store.demoSync(connectionId);
      }
      return syncConnection(connectionId, days);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}
