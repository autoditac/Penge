import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { InfiniteData, UseInfiniteQueryResult, UseQueryResult } from "@tanstack/react-query";

import {
  fetchHouseholdReportCategories,
  fetchHouseholdReportSummary,
  fetchHouseholdReportTransactions,
} from "./householdReportsClient";
import type { HouseholdFilters } from "../household/types";
import type {
  HouseholdReportCategoriesResponse,
  HouseholdReportSummaryResponse,
  HouseholdReportTransactionsResponse,
} from "./schemas";

const staleTime = 30_000;

export function useHouseholdReportSummary(
  filters: HouseholdFilters,
): UseQueryResult<HouseholdReportSummaryResponse, Error> {
  return useQuery({
    queryKey: ["household", "reports", "summary", filters],
    queryFn: () => fetchHouseholdReportSummary(filters),
    staleTime,
  });
}

export function useHouseholdReportCategories(
  filters: HouseholdFilters,
): UseQueryResult<HouseholdReportCategoriesResponse, Error> {
  return useQuery({
    queryKey: ["household", "reports", "categories", filters],
    queryFn: () => fetchHouseholdReportCategories(filters),
    staleTime,
  });
}

export function useHouseholdReportTransactions(
  filters: HouseholdFilters,
  limit: number,
  enabled = true,
): UseInfiniteQueryResult<InfiniteData<HouseholdReportTransactionsResponse>, Error> {
  return useInfiniteQuery({
    queryKey: ["household", "reports", "transactions", filters, limit],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => fetchHouseholdReportTransactions(filters, limit, pageParam),
    getNextPageParam: (lastPage) => {
      const nextOffset = lastPage.offset + lastPage.items.length;
      return nextOffset < lastPage.total ? nextOffset : undefined;
    },
    staleTime,
    enabled,
  });
}
