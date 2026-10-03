import { getJson } from "./client";
import type { HouseholdFilters } from "../household/types";
import {
  householdReportCategoriesSchema,
  householdReportSummarySchema,
  householdReportTransactionsSchema,
} from "./schemas";
import type {
  HouseholdReportCategoriesResponse,
  HouseholdReportSummaryResponse,
  HouseholdReportTransactionsResponse,
} from "./schemas";

function reportParams(
  filters: HouseholdFilters,
): Readonly<Record<string, string | number | readonly string[] | undefined>> {
  return {
    account_id: filters.accountIds,
    category_id: filters.categoryId ?? undefined,
    entity_id: filters.entityIds,
    granularity: filters.granularity,
    since: filters.since,
    until: filters.until,
  };
}

export function fetchHouseholdReportSummary(
  filters: HouseholdFilters,
): Promise<HouseholdReportSummaryResponse> {
  return getJson("/household/reports/summary", reportParams(filters), householdReportSummarySchema);
}

export function fetchHouseholdReportCategories(
  filters: HouseholdFilters,
): Promise<HouseholdReportCategoriesResponse> {
  return getJson(
    "/household/reports/categories",
    reportParams(filters),
    householdReportCategoriesSchema,
  );
}

export function fetchHouseholdReportTransactions(
  filters: HouseholdFilters,
  limit: number,
  offset: number,
  search?: string,
): Promise<HouseholdReportTransactionsResponse> {
  return getJson(
    "/household/reports/transactions",
    { ...reportParams(filters), limit, offset, search },
    householdReportTransactionsSchema,
  );
}
