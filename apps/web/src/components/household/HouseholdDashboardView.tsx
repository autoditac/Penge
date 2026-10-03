import { useMemo } from "react";
import AccountBalanceWalletOutlinedIcon from "@mui/icons-material/AccountBalanceWalletOutlined";
import ArrowDownwardOutlinedIcon from "@mui/icons-material/ArrowDownwardOutlined";
import ArrowUpwardOutlinedIcon from "@mui/icons-material/ArrowUpwardOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import type { EChartOption } from "../EChart";
import { EChart } from "../EChart";
import { HouseholdFilters } from "./HouseholdFilters";
import { ReportingMoneyPair } from "./ReportingMoneyPair";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  Panel,
  TableScroll,
} from "../primitives";
import type { HouseholdReportData, HouseholdTrendPoint } from "../../household/reporting";
import {
  categoryDrilldownFilters,
  householdTrendSeries,
  periodDrilldownFilters,
  reportCurrencyView,
} from "../../household/reporting";
import type {
  HouseholdFilterOptions,
  HouseholdFilters as HouseholdFilterValues,
} from "../../household/types";
import { formatCompact } from "../../money";
import { formatHouseholdSourceAmount } from "../../household/money";
import type { HouseholdReportTransaction } from "../../api/schemas";
import { chartPalette, chartTextColor } from "../../theme";

type HouseholdDashboardViewProps = {
  readonly filters: HouseholdFilterValues;
  readonly filterOptions: HouseholdFilterOptions;
  readonly report: HouseholdReportData;
  readonly onFiltersChange: (filters: HouseholdFilterValues) => void;
  readonly onDrilldown: (filters: HouseholdFilterValues) => void;
  readonly transactions?: readonly HouseholdReportTransaction[] | undefined;
  readonly transactionTotal?: number | undefined;
  readonly transactionOffset?: number | undefined;
  readonly onLoadMoreTransactions?: (() => void) | undefined;
  readonly showTransactions?: boolean | undefined;
  readonly transactionsLoading?: boolean | undefined;
  readonly transactionsError?: Error | null | undefined;
  readonly onRetryTransactions?: (() => void) | undefined;
};

export function HouseholdDashboardView({
  filters,
  filterOptions,
  report,
  onFiltersChange,
  onDrilldown,
  transactions,
  transactionTotal,
  transactionOffset = 0,
  onLoadMoreTransactions,
  showTransactions = false,
  transactionsLoading = false,
  transactionsError = null,
  onRetryTransactions,
}: HouseholdDashboardViewProps): React.JSX.Element {
  return (
    <>
      <Panel title="Report filters">
        <HouseholdFilters value={filters} options={filterOptions} onChange={onFiltersChange} />
      </Panel>
      <CoverageNotice coverage={report.coverage} filters={filters} freshness={report.freshness} />
      <Panel title="Income, expenses and surplus">
        <SummaryMetrics
          current={report.current}
          previous={report.previous}
          change={report.change}
        />
      </Panel>
      <Panel title="Cash flow over time">
        {report.points.length === 0 ? (
          <EmptyState label="household cash-flow history" />
        ) : (
          <TrendCharts points={report.points} filters={filters} onDrilldown={onDrilldown} />
        )}
      </Panel>
      <Panel title="Category breakdown">
        {report.categories.length === 0 ? (
          <EmptyState label="category rollups" />
        ) : (
          <CategoryRollupTable
            categories={report.categories}
            filters={filters}
            onDrilldown={onDrilldown}
          />
        )}
      </Panel>
      {showTransactions ? (
        <Panel title="Matching bank transactions">
          {transactionsLoading ? (
            <LoadingState label="matching household bank transactions" />
          ) : transactionsError !== null ? (
            <ErrorState
              label="matching household bank transactions"
              error={transactionsError}
              {...(onRetryTransactions === undefined ? {} : { onRetry: onRetryTransactions })}
            />
          ) : transactions === undefined || transactions.length === 0 ? (
            <EmptyState label="matching household bank transactions" />
          ) : (
            <TableScroll>
              <Table size="small" aria-label="Matching household bank transactions">
                <TableHead>
                  <TableRow>
                    <TableCell>Date</TableCell>
                    <TableCell>Transaction</TableCell>
                    <TableCell>Treatment</TableCell>
                    <TableCell align="right">Full bank amount</TableCell>
                    <TableCell align="right">Category-matching allocation</TableCell>
                    <TableCell>Payment detail</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {transactions.map((transaction) => (
                    <TableRow key={transaction.transaction_id} hover>
                      <TableCell>{transaction.value_date}</TableCell>
                      <TableCell>
                        <Typography sx={{ fontWeight: 600 }}>
                          {transaction.merchant_name ??
                            transaction.counterparty ??
                            transaction.description ??
                            "Bank transaction"}
                        </Typography>
                        {transaction.description !== null ? (
                          <Typography variant="caption" color="text.secondary">
                            {transaction.description}
                          </Typography>
                        ) : null}
                      </TableCell>
                      <TableCell>{transaction.treatment}</TableCell>
                      <TableCell align="right">
                        <Typography>
                          {formatHouseholdSourceAmount(
                            transaction.signed_amount_native,
                            transaction.currency,
                          )}
                        </Typography>
                        <ReportingMoneyPair
                          eur={reportCurrencyView(transaction.amount_reporting.eur)}
                          dkk={reportCurrencyView(transaction.amount_reporting.dkk)}
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Typography>
                          {formatHouseholdSourceAmount(
                            transaction.matching_split_amount_native,
                            transaction.currency,
                          )}
                        </Typography>
                        <ReportingMoneyPair
                          eur={reportCurrencyView(transaction.matching_split_amount_reporting.eur)}
                          dkk={reportCurrencyView(transaction.matching_split_amount_reporting.dkk)}
                        />
                      </TableCell>
                      <TableCell>
                        {transaction.payment_details.length === 0
                          ? transaction.payment_reconciliation_status
                          : transaction.payment_details
                              .map(
                                (detail) =>
                                  `${detail.merchant_name ?? "Payment detail"} · ${detail.event_kind} · ${detail.reconciliation_status}`,
                              )
                              .join("; ")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableScroll>
          )}
          {!transactionsLoading &&
          transactions !== undefined &&
          transactionsError === null &&
          transactionTotal !== undefined ? (
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 1 }}>
              <Typography color="text.secondary" aria-live="polite">
                Showing {transactionOffset + transactions.length} of {transactionTotal}
              </Typography>
              {onLoadMoreTransactions !== undefined &&
              transactionOffset + transactions.length < transactionTotal ? (
                <Button onClick={onLoadMoreTransactions} sx={{ minHeight: 44 }}>
                  Load more matching transactions
                </Button>
              ) : null}
            </Stack>
          ) : null}
        </Panel>
      ) : null}
    </>
  );
}

function SummaryMetrics({
  current,
  previous,
  change,
}: {
  readonly current: HouseholdReportData["current"];
  readonly previous: HouseholdReportData["previous"];
  readonly change: HouseholdReportData["change"];
}): React.JSX.Element {
  const metrics = [
    {
      label: "Income",
      current: current.income,
      previous: previous.income,
      change: change.income,
      tone: "good" as const,
    },
    {
      label: "Gross expenses",
      current: current.grossExpenses,
      previous: previous.grossExpenses,
      change: change.grossExpenses,
      tone: "watch" as const,
    },
    {
      label: "Refunds",
      current: current.refunds,
      previous: previous.refunds,
      change: change.refunds,
      tone: "info" as const,
    },
    {
      label: "Net expenses",
      current: current.netExpenses,
      previous: previous.netExpenses,
      change: change.netExpenses,
      tone: "watch" as const,
    },
    {
      label: "Surplus",
      current: current.surplus,
      previous: previous.surplus,
      change: change.surplus,
      tone: "info" as const,
    },
  ];

  return (
    <Box
      sx={{
        display: "grid",
        gap: 1.25,
        gridTemplateColumns: {
          xs: "1fr",
          sm: "repeat(2, minmax(0, 1fr))",
          xl: "repeat(3, minmax(0, 1fr))",
        },
      }}
    >
      {metrics.map((metric) => (
        <MetricCard
          key={metric.label}
          label={metric.label}
          tone={metric.tone}
          detail="Current period"
        >
          <ReportingMoneyPair eur={metric.current.eur} dkk={metric.current.dkk} />
          <Box
            component="span"
            sx={{ display: "block", mt: 0.75, fontSize: "0.75rem", color: "text.secondary" }}
          >
            Change vs previous period
          </Box>
          <ReportingMoneyPair eur={metric.change.eur} dkk={metric.change.dkk} />
          <Box
            component="span"
            sx={{ display: "block", mt: 0.75, fontSize: "0.75rem", color: "text.secondary" }}
          >
            Previous equal-length period
          </Box>
          <ReportingMoneyPair eur={metric.previous.eur} dkk={metric.previous.dkk} />
        </MetricCard>
      ))}
    </Box>
  );
}

function TrendCharts({
  points,
  filters,
  onDrilldown,
}: {
  readonly points: readonly HouseholdTrendPoint[];
  readonly filters: HouseholdFilterValues;
  readonly onDrilldown: (filters: HouseholdFilterValues) => void;
}): React.JSX.Element {
  const dkkOption = useTrendOption(points, "DKK");
  const eurOption = useTrendOption(points, "EUR");
  const onPointClick = (index: number): void => {
    const point = points[index];
    if (point !== undefined) {
      onDrilldown(periodDrilldownFilters(filters, point));
    }
  };

  return (
    <Box>
      <Typography color="text.secondary" sx={{ mb: 1 }}>
        Incomplete currency values appear as gaps. Select a point to review its transactions.
      </Typography>
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", xl: "repeat(2, minmax(0, 1fr))" },
        }}
      >
        <Box>
          <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700 }}>
            DKK
          </Typography>
          <EChart
            option={dkkOption}
            height={280}
            ariaLabel="Household income, net expenses and surplus over time in Danish kroner"
            onDataPointClick={onPointClick}
          />
        </Box>
        <Box>
          <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 700 }}>
            EUR
          </Typography>
          <EChart
            option={eurOption}
            height={280}
            ariaLabel="Household income, net expenses and surplus over time in euros"
            onDataPointClick={onPointClick}
          />
        </Box>
      </Box>
      <Stack spacing={0.5} sx={{ mt: 1 }}>
        {points.map((point) => (
          <Button
            key={`${point.periodStart}:${point.periodEnd}`}
            onClick={() => onDrilldown(periodDrilldownFilters(filters, point))}
            sx={{ alignSelf: "flex-start", minHeight: 44, textTransform: "none" }}
          >
            Review {point.periodStart} to {point.periodEnd}
          </Button>
        ))}
      </Stack>
    </Box>
  );
}

function useTrendOption(
  points: readonly HouseholdTrendPoint[],
  currency: "EUR" | "DKK",
): EChartOption {
  return useMemo(() => {
    const series = householdTrendSeries(points, currency);
    const palette = chartPalette();
    return {
      color: [...palette],
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: chartTextColor() } },
      grid: { left: 64, right: 20, top: 36, bottom: 42 },
      xAxis: {
        type: "category",
        data: points.map(({ periodStart }) => periodStart),
        axisLabel: { color: chartTextColor(), hideOverlap: true },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: chartTextColor(),
          formatter: (value: number) => formatCompact(value),
        },
        splitLine: { lineStyle: { opacity: 0.15 } },
      },
      series: [
        {
          name: "Income",
          type: "line",
          showSymbol: true,
          connectNulls: false,
          data: [...series.income],
        },
        {
          name: "Net expenses",
          type: "line",
          showSymbol: true,
          connectNulls: false,
          data: [...series.netExpenses],
        },
        {
          name: "Surplus",
          type: "line",
          showSymbol: true,
          connectNulls: false,
          data: [...series.surplus],
        },
      ],
    };
  }, [currency, points]);
}

function CategoryRollupTable({
  categories,
  filters,
  onDrilldown,
}: {
  readonly categories: HouseholdReportData["categories"];
  readonly filters: HouseholdFilterValues;
  readonly onDrilldown: (filters: HouseholdFilterValues) => void;
}): React.JSX.Element {
  return (
    <TableScroll>
      <Table size="small" aria-label="Household income and expense category rollups">
        <TableHead>
          <TableRow>
            <TableCell>Category</TableCell>
            <TableCell>Type</TableCell>
            <TableCell align="right">Income</TableCell>
            <TableCell align="right">Net expenses</TableCell>
            <TableCell align="right">Surplus</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {categories.map((category) => (
            <TableRow key={category.id} hover>
              <TableCell>
                <Button
                  onClick={() => onDrilldown(categoryDrilldownFilters(filters, category.id))}
                  sx={{
                    justifyContent: "flex-start",
                    pl: Math.min(category.depth, 5) * 2,
                    textTransform: "none",
                  }}
                >
                  {category.label}
                </Button>
              </TableCell>
              <TableCell>
                <Chip
                  size="small"
                  icon={
                    category.kind === "income" ? (
                      <ArrowUpwardOutlinedIcon />
                    ) : (
                      <ArrowDownwardOutlinedIcon />
                    )
                  }
                  label={category.kind}
                />
              </TableCell>
              <TableCell align="right">
                <ReportingMoneyPair
                  eur={category.totals.income.eur}
                  dkk={category.totals.income.dkk}
                />
              </TableCell>
              <TableCell align="right">
                <ReportingMoneyPair
                  eur={category.totals.netExpenses.eur}
                  dkk={category.totals.netExpenses.dkk}
                />
              </TableCell>
              <TableCell align="right">
                <ReportingMoneyPair
                  eur={category.totals.surplus.eur}
                  dkk={category.totals.surplus.dkk}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableScroll>
  );
}

function CoverageNotice({
  coverage,
  filters,
  freshness,
}: {
  readonly coverage: HouseholdReportData["coverage"];
  readonly filters: HouseholdFilterValues;
  readonly freshness: HouseholdReportData["freshness"];
}): React.JSX.Element {
  const startsAfterWindow = coverage.historyStart !== null && coverage.historyStart > filters.since;
  const incomplete =
    startsAfterWindow ||
    coverage.historyCompleteness === "unknown" ||
    coverage.unclassifiedTransactionCount > 0 ||
    coverage.missingFxAllocationCount > 0 ||
    coverage.paymentDetailReviewCount > 0 ||
    coverage.paymentDetailStaleCount > 0 ||
    coverage.sourceSnapshotDriftCount > 0 ||
    coverage.allocationMismatchCount > 0;
  const headline = incomplete ? "Coverage is partial" : "Report coverage";
  const secondaryText =
    coverage.historyStart === null
      ? "Transaction history start is not available."
      : `Available transaction history starts ${coverage.historyStart}.`;

  return (
    <Panel title={headline}>
      <Stack spacing={1}>
        {coverage.historyCompleteness === "unknown" ? (
          <Typography color="warning.main">
            The available API cannot certify complete history coverage; available transactions start{" "}
            {coverage.historyStart ?? "at an unknown date"}.
          </Typography>
        ) : null}
        {startsAfterWindow ? (
          <Typography color="warning.main">
            The selected period begins before the available transaction history; earlier activity is
            not included.
          </Typography>
        ) : null}
        {coverage.missingFxAllocationCount > 0 ? (
          <Typography color="warning.main">
            {coverage.missingFxAllocationCount} allocations lack a complete currency conversion.
            Incomplete values are shown as gaps or known subtotals, never as zero.
          </Typography>
        ) : null}
        {coverage.unclassifiedTransactionCount > 0 ? (
          <Typography color="warning.main">
            {coverage.unclassifiedTransactionCount} unclassified transactions, including{" "}
            {coverage.unclassifiedExpenseCount} unclassified expenses, remain included.
          </Typography>
        ) : null}
        {coverage.paymentDetailReviewCount + coverage.paymentDetailStaleCount > 0 ? (
          <Typography color="warning.main">
            {coverage.paymentDetailReviewCount} payment details need review and{" "}
            {coverage.paymentDetailStaleCount} are stale; details do not add extra spending.
          </Typography>
        ) : null}
        <Typography color="text.secondary">{secondaryText}</Typography>
        <Stack direction="row" useFlexGap spacing={1} sx={{ flexWrap: "wrap" }}>
          <Chip
            icon={<AccountBalanceWalletOutlinedIcon />}
            label={`${coverage.includedTransactionCount} included of ${coverage.bankTransactionCount} bank transactions`}
            variant="outlined"
          />
          <Chip label={`${coverage.transferExcludedCount} transfers excluded`} variant="outlined" />
          <Chip
            label={`${coverage.classificationReviewCount} classifications need review`}
            variant="outlined"
            color={coverage.classificationReviewCount > 0 ? "warning" : "default"}
          />
          <FreshnessText label="Report generated" value={freshness.reportGeneratedAt} />
          <FreshnessText label="Latest bank booking" value={freshness.latestBankBookingDate} />
          <FreshnessText label="Latest bank import" value={freshness.latestBankImportAt} />
          <FreshnessText label="Latest FX rate" value={freshness.latestFxRateDate} />
          <FreshnessText label="Payment detail sync" value={freshness.latestPaymentDetailSyncAt} />
        </Stack>
      </Stack>
    </Panel>
  );
}

function FreshnessText({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string | null;
}): React.JSX.Element {
  return (
    <Chip
      label={`${label}: ${value ?? "unavailable"}`}
      variant="outlined"
      color={value === null ? "warning" : "default"}
    />
  );
}
