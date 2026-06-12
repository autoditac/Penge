/** TanStack Query hooks for the read API.
 *
 * In demo mode (`VITE_PENGE_DEMO=true`) the hooks resolve deterministic
 * synthetic fixtures through a dynamic import, keeping fixtures out of the
 * production bundle's critical path while exercising identical UI states.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  commitImport,
  demoMode,
  discardImport,
  fetchAccounts,
  fetchAllocation,
  fetchCashflowDaily,
  fetchFreshness,
  fetchImportSession,
  fetchImportSessions,
  fetchImportSuggestions,
  fetchNetWorthByAccount,
  fetchNetWorthTotal,
  patchImportRow,
  uploadImport,
} from "./client";
import type { CommitOptions, RowPatch, SeriesParams, UploadImportOptions } from "./client";
import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  CashflowSeriesResponse,
  CommitResponse,
  FreshnessResponse,
  ImportRow,
  ImportSession,
  ImportSessionList,
  ImportSessionWithRows,
  NetWorthSeriesResponse,
  NetWorthTotalSeriesResponse,
  SuggestionsResponse,
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
