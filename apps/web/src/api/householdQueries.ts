/** TanStack Query hooks for the audited household API (#330/#334). */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  applyHouseholdPreview,
  correctHouseholdTransaction,
  createHouseholdAlias,
  createHouseholdCategory,
  createHouseholdMerchant,
  fetchAllHouseholdAliases,
  fetchAllHouseholdCategories,
  fetchAllHouseholdMerchants,
  fetchAllHouseholdPaymentDetails,
  fetchAllHouseholdRules,
  fetchHouseholdAudit,
  fetchHouseholdPreview,
  fetchHouseholdSuggestion,
  fetchHouseholdTransaction,
  fetchHouseholdTransactions,
  fetchUnmatchedHouseholdPaymentDetails,
  previewHouseholdRule,
  undoHouseholdTransaction,
  updateHouseholdAlias,
  updateHouseholdCategory,
  updateHouseholdMerchant,
  updateHouseholdRule,
} from "./householdClient";
import type { components, operations } from "./schema";
import type {
  HouseholdAliasResponse,
  HouseholdAuditResponse,
  HouseholdCategoryResponse,
  HouseholdClassificationResponse,
  HouseholdMerchantResponse,
  HouseholdPaymentDetailResponse,
  HouseholdPreviewResponse,
  HouseholdRuleResponse,
  HouseholdSuggestionResponse,
  HouseholdTransactionResponse,
} from "./schemas";

type TransactionQuery = NonNullable<
  operations["transactions_household_transactions_get"]["parameters"]["query"]
>;
type HouseholdWrite = components["schemas"];
type CategoryWrite = HouseholdWrite["CategoryWrite"];
type MerchantWrite = HouseholdWrite["MerchantWrite"];
type AliasWrite = HouseholdWrite["AliasWrite"];
type RuleControl = HouseholdWrite["RuleControl"];
type ClassificationWrite = HouseholdWrite["ClassificationWrite"];
type UndoWrite = HouseholdWrite["Undo"];

const householdKey = ["household"] as const;
const staleTime = 30_000;

function useHouseholdList<T>(key: string, queryFn: () => Promise<T>): UseQueryResult<T, Error> {
  return useQuery({
    queryKey: [...householdKey, key],
    queryFn,
    staleTime,
  });
}

export function useHouseholdCategories(): UseQueryResult<HouseholdCategoryResponse[], Error> {
  return useHouseholdList("categories", fetchAllHouseholdCategories);
}

export function useHouseholdMerchants(): UseQueryResult<HouseholdMerchantResponse[], Error> {
  return useHouseholdList("merchants", fetchAllHouseholdMerchants);
}

export function useHouseholdAliases(): UseQueryResult<HouseholdAliasResponse[], Error> {
  return useHouseholdList("aliases", fetchAllHouseholdAliases);
}

export function useHouseholdRules(): UseQueryResult<HouseholdRuleResponse[], Error> {
  return useHouseholdList("rules", fetchAllHouseholdRules);
}

export function useUnmatchedHouseholdPaymentDetails(): UseQueryResult<
  HouseholdPaymentDetailResponse[],
  Error
> {
  return useHouseholdList("payment-details-unmatched", fetchUnmatchedHouseholdPaymentDetails);
}

export function useHouseholdPaymentDetails(): UseQueryResult<
  HouseholdPaymentDetailResponse[],
  Error
> {
  return useHouseholdList("payment-details", fetchAllHouseholdPaymentDetails);
}

export function useHouseholdTransactions(
  query: TransactionQuery,
): UseQueryResult<HouseholdTransactionResponse[], Error> {
  return useQuery({
    queryKey: [...householdKey, "transactions", query],
    queryFn: () => fetchHouseholdTransactions(query),
    staleTime,
  });
}

const transactionPageSize = 100;

export function useInfiniteHouseholdTransactions(search: string) {
  return useInfiniteQuery({
    queryKey: [...householdKey, "transaction-search", search],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      fetchHouseholdTransactions({
        limit: transactionPageSize,
        offset: pageParam,
        search: search.trim() === "" ? null : search.trim(),
      }),
    getNextPageParam: (lastPage, _allPages, lastOffset) =>
      lastPage.length < transactionPageSize ? undefined : lastOffset + lastPage.length,
    staleTime,
  });
}

export function useHouseholdTransaction(
  transactionId: string | null,
): UseQueryResult<HouseholdTransactionResponse, Error> {
  return useQuery({
    queryKey: [...householdKey, "transaction", transactionId],
    enabled: transactionId !== null,
    staleTime,
    queryFn: () => {
      if (transactionId === null) {
        throw new Error("no household transaction selected");
      }
      return fetchHouseholdTransaction(transactionId);
    },
  });
}

export function useHouseholdSuggestion(
  transactionId: string | null,
): UseQueryResult<HouseholdSuggestionResponse, Error> {
  return useQuery({
    queryKey: [...householdKey, "suggestion", transactionId],
    enabled: transactionId !== null,
    staleTime,
    queryFn: () => {
      if (transactionId === null) {
        throw new Error("no household transaction selected");
      }
      return fetchHouseholdSuggestion(transactionId);
    },
  });
}

export function useHouseholdAudit(
  subjectId: string | null,
): UseQueryResult<HouseholdAuditResponse[], Error> {
  return useQuery({
    queryKey: [...householdKey, "audit", subjectId],
    enabled: subjectId !== null,
    staleTime: 0,
    queryFn: () => {
      if (subjectId === null) {
        throw new Error("no household subject selected");
      }
      return fetchHouseholdAudit(subjectId);
    },
  });
}

export function useHouseholdPreview(
  previewId: string | null,
): UseQueryResult<HouseholdPreviewResponse, Error> {
  return useQuery({
    queryKey: [...householdKey, "preview", previewId],
    enabled: previewId !== null,
    staleTime: 0,
    queryFn: () => {
      if (previewId === null) {
        throw new Error("no household preview selected");
      }
      return fetchHouseholdPreview(previewId);
    },
  });
}

type IdWrite<T> = {
  readonly id: string | null;
  readonly body: T;
};

function useHouseholdMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
): UseMutationResult<TResult, Error, TVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: householdKey }),
  });
}

export function useSaveHouseholdCategory(): UseMutationResult<
  HouseholdCategoryResponse,
  Error,
  IdWrite<CategoryWrite>
> {
  return useHouseholdMutation(({ id, body }) =>
    id === null ? createHouseholdCategory(body) : updateHouseholdCategory(id, body),
  );
}

export function useSaveHouseholdMerchant(): UseMutationResult<
  HouseholdMerchantResponse,
  Error,
  IdWrite<MerchantWrite>
> {
  return useHouseholdMutation(({ id, body }) =>
    id === null ? createHouseholdMerchant(body) : updateHouseholdMerchant(id, body),
  );
}

type SaveAliasVariables = {
  readonly id: string | null;
  readonly body: AliasWrite;
};

export function useSaveHouseholdAlias(): UseMutationResult<
  HouseholdAliasResponse,
  Error,
  SaveAliasVariables
> {
  return useHouseholdMutation(({ id, body }) =>
    id === null ? createHouseholdAlias(body) : updateHouseholdAlias(id, body),
  );
}

type UpdateRuleVariables = {
  readonly ruleId: string;
  readonly body: RuleControl;
};

export function useControlHouseholdRule(): UseMutationResult<
  HouseholdRuleResponse,
  Error,
  UpdateRuleVariables
> {
  return useHouseholdMutation(({ ruleId, body }) => updateHouseholdRule(ruleId, body));
}

export function usePreviewHouseholdRule(): UseMutationResult<
  HouseholdPreviewResponse,
  Error,
  string
> {
  return useHouseholdMutation((ruleId) => previewHouseholdRule(ruleId));
}

export function useApplyHouseholdPreview(): UseMutationResult<
  HouseholdPreviewResponse,
  Error,
  string
> {
  return useHouseholdMutation((previewId) => applyHouseholdPreview(previewId));
}

type CorrectTransactionVariables = {
  readonly transactionId: string;
  readonly body: ClassificationWrite;
};

export function useCorrectHouseholdTransaction(): UseMutationResult<
  HouseholdClassificationResponse,
  Error,
  CorrectTransactionVariables
> {
  return useHouseholdMutation(({ transactionId, body }) =>
    correctHouseholdTransaction(transactionId, body),
  );
}

type UndoTransactionVariables = {
  readonly transactionId: string;
  readonly body: UndoWrite;
};

export function useUndoHouseholdTransaction(): UseMutationResult<
  HouseholdClassificationResponse,
  Error,
  UndoTransactionVariables
> {
  return useHouseholdMutation(({ transactionId, body }) =>
    undoHouseholdTransaction(transactionId, body),
  );
}
