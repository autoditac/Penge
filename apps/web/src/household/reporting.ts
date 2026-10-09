import { parseDecimal } from "../money";
import type { Currency } from "../money";
import type { ReportCurrencyAmount } from "../components/household/ReportingMoneyPair";
import type { HouseholdFilters } from "./types";
import type {
  HouseholdReportCategoriesResponse as ReportCategoriesResponse,
  HouseholdReportSummaryResponse as ReportSummaryResponse,
} from "../api/schemas";

export type HouseholdReportTotals = {
  readonly income: ReportCurrencyPair;
  readonly grossExpenses: ReportCurrencyPair;
  readonly refunds: ReportCurrencyPair;
  readonly netExpenses: ReportCurrencyPair;
  readonly surplus: ReportCurrencyPair;
};

export type ReportCurrencyPair = {
  readonly eur: ReportCurrencyAmount;
  readonly dkk: ReportCurrencyAmount;
};

export type HouseholdTrendPoint = HouseholdReportTotals & {
  readonly periodStart: string;
  readonly periodEnd: string;
};

export type HouseholdCategoryRollup = {
  readonly id: string;
  readonly label: string;
  readonly kind: "income" | "expense";
  readonly depth: number;
  readonly totals: HouseholdReportTotals;
};

export type HouseholdReportCoverage = {
  readonly historyCompleteness: "unknown";
  readonly historyStart: string | null;
  readonly bankTransactionCount: number;
  readonly includedTransactionCount: number;
  readonly unclassifiedTransactionCount: number;
  readonly unclassifiedExpenseCount: number;
  readonly unclassifiedExpenseAmount: ReportCurrencyPair;
  readonly transferExcludedCount: number;
  readonly excludedTransactionCount: number;
  readonly classificationReviewCount: number;
  readonly sourceSnapshotDriftCount: number;
  readonly allocationMismatchCount: number;
  readonly missingFxAllocationCount: number;
  readonly paymentDetailLinkCount: number;
  readonly paymentDetailReconciledCount: number;
  readonly paymentDetailReviewCount: number;
  readonly paymentDetailStaleCount: number;
  readonly paymentDetailUnmatchedCount: number;
};

export type HouseholdReportFreshness = {
  readonly reportGeneratedAt: string;
  readonly latestBankBookingDate: string | null;
  readonly latestBankImportAt: string | null;
  readonly latestFxRateDate: string | null;
  readonly latestPaymentDetailSyncAt: string | null;
};

export type HouseholdReportData = {
  readonly current: HouseholdReportTotals;
  readonly previous: HouseholdReportTotals;
  readonly change: HouseholdReportTotals;
  readonly points: readonly HouseholdTrendPoint[];
  readonly categories: readonly HouseholdCategoryRollup[];
  readonly coverage: HouseholdReportCoverage;
  readonly freshness: HouseholdReportFreshness;
};

export type HouseholdTrendSeries = {
  readonly income: readonly (number | null)[];
  readonly netExpenses: readonly (number | null)[];
  readonly surplus: readonly (number | null)[];
};

export function householdTrendSeries(
  points: readonly HouseholdTrendPoint[],
  currency: Currency,
): HouseholdTrendSeries {
  return {
    income: points.map((point) => amountForChart(point.income[currencyKey(currency)])),
    netExpenses: points.map((point) => amountForChart(point.netExpenses[currencyKey(currency)])),
    surplus: points.map((point) => amountForChart(point.surplus[currencyKey(currency)])),
  };
}

function currencyKey(currency: Currency): "eur" | "dkk" {
  return currency === "EUR" ? "eur" : "dkk";
}

function amountForChart(value: ReportCurrencyAmount): number | null {
  return value.complete ? parseDecimal(value.amount) : null;
}

export function periodDrilldownFilters(
  filters: HouseholdFilters,
  period: Pick<HouseholdTrendPoint, "periodStart" | "periodEnd">,
): HouseholdFilters {
  return {
    ...filters,
    since: period.periodStart,
    until: period.periodEnd,
  };
}

export function categoryDrilldownFilters(
  filters: HouseholdFilters,
  categoryId: string,
): HouseholdFilters {
  return { ...filters, categoryId };
}

export function reportCurrencyView(
  amount: ReportSummaryResponse["current"]["totals"]["income"]["eur"],
): ReportCurrencyAmount {
  if (amount.complete && amount.amount !== null) {
    return { complete: true, amount: amount.amount, knownSubtotal: amount.known_subtotal };
  }
  if (!amount.complete && amount.amount === null) {
    return { complete: false, amount: null, knownSubtotal: amount.known_subtotal };
  }
  throw new Error("Household report currency amount contradicts its completeness flag.");
}

export function householdReportViewData(
  summary: ReportSummaryResponse,
  categoryReport: ReportCategoriesResponse,
): HouseholdReportData {
  const mapTotals = (
    totals: ReportSummaryResponse["current"]["totals"],
  ): HouseholdReportTotals => ({
    income: mapPair(totals.income),
    grossExpenses: mapPair(totals.gross_expenses),
    refunds: mapPair(totals.refunds),
    netExpenses: mapPair(totals.net_expenses),
    surplus: mapPair(totals.surplus),
  });
  const mapPair = (
    pair: ReportSummaryResponse["current"]["totals"]["income"],
  ): ReportCurrencyPair => ({
    eur: mapAmount(pair.eur),
    dkk: mapAmount(pair.dkk),
  });
  const mapAmount = (
    amount: ReportSummaryResponse["current"]["totals"]["income"]["eur"],
  ): ReportCurrencyAmount => {
    if (amount.complete) {
      if (amount.amount === null) {
        throw new Error("Complete household report currency amount is missing.");
      }
      return {
        complete: true,
        amount: amount.amount,
        knownSubtotal: amount.known_subtotal,
      };
    }
    if (amount.amount !== null) {
      throw new Error("Household report currency amount contradicts its completeness flag.");
    }
    return {
      complete: false,
      amount: null,
      knownSubtotal: amount.known_subtotal,
    };
  };
  const categories: HouseholdCategoryRollup[] = [];
  const visit = (
    nodes: readonly ReportCategoriesResponse["categories"][number][],
    depth: number,
  ): void => {
    for (const node of nodes) {
      categories.push({
        id: node.category_id,
        label: node.name,
        kind: node.kind,
        depth,
        totals: mapTotals(node.totals),
      });
      visit(node.children, depth + 1);
    }
  };
  visit(categoryReport.categories, 0);

  const coverage = summary.coverage;
  const freshness = summary.freshness;
  return {
    current: mapTotals(summary.current.totals),
    previous: mapTotals(summary.previous.totals),
    change: mapTotals(summary.change),
    points: summary.points.map((point) => ({
      ...mapTotals(point.totals),
      periodStart: point.period_start,
      periodEnd: point.period_end,
    })),
    categories,
    coverage: {
      historyCompleteness: coverage.history_completeness,
      historyStart: coverage.history_start,
      bankTransactionCount: coverage.bank_transaction_count,
      includedTransactionCount: coverage.included_transaction_count,
      unclassifiedTransactionCount: coverage.unclassified_transaction_count,
      unclassifiedExpenseCount: coverage.unclassified_expense_count,
      unclassifiedExpenseAmount: mapPair(coverage.unclassified_expense_amount),
      transferExcludedCount: coverage.transfer_excluded_count,
      excludedTransactionCount: coverage.excluded_transaction_count,
      classificationReviewCount: coverage.classification_review_count,
      sourceSnapshotDriftCount: coverage.source_snapshot_drift_count,
      allocationMismatchCount: coverage.allocation_mismatch_count,
      missingFxAllocationCount: coverage.missing_fx_allocation_count,
      paymentDetailLinkCount: coverage.payment_detail_link_count,
      paymentDetailReconciledCount: coverage.payment_detail_reconciled_count,
      paymentDetailReviewCount: coverage.payment_detail_review_count,
      paymentDetailStaleCount: coverage.payment_detail_stale_count,
      paymentDetailUnmatchedCount: coverage.payment_detail_unmatched_count,
    },
    freshness: {
      reportGeneratedAt: freshness.report_generated_at,
      latestBankBookingDate: freshness.latest_bank_booking_date,
      latestBankImportAt: freshness.latest_bank_import_at,
      latestFxRateDate: freshness.latest_fx_rate_date,
      latestPaymentDetailSyncAt: freshness.latest_payment_detail_sync_at,
    },
  };
}
