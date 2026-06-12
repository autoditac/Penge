/** Performance dashboard v2 (#204, #206).
 *
 * v1: range-selectable net-worth trend with drawdown shading, rolling
 * savings rate, allocation drift vs configured targets, and per-account /
 * per-asset-class drill-down. v2 adds the returns-engine views (#205):
 * TWR index lines per account/asset class with benchmark overlay, MWR/TWR
 * summary cards, contribution-vs-growth decomposition, and fee drag.
 */

import { useMemo, useState } from "react";

import {
  useAccounts,
  useAllocation,
  useBenchmarkDaily,
  useBenchmarks,
  useCashflowDaily,
  useFees,
  useNetWorthByAccount,
  useNetWorthTotal,
  useReturnsDaily,
  useReturnsSummary,
} from "../api/queries";
import { EChart } from "../components/EChart";
import type { EChartOption } from "../components/EChart";
import { EmptyState, ErrorState, KpiCard, LoadingState, MoneyPair } from "../components/primitives";
import { liquidKinds, targetWeightsByKind } from "../config/targets";
import { formatCompact, formatMoney, formatShare, isoDaysAgo, parseDecimal } from "../money";
import { chartPalette, chartTextColor } from "../theme";
import {
  allocationDrift,
  benchmarkIndexSeries,
  contributionGrowthSeries,
  drawdownSeries,
  feeDragByYear,
  kindWeightHistory,
  latestNetWorth,
  liquidShare,
  maxDrawdown,
  monthOverMonthChange,
  monthlyCashflow,
  netWorthSeries,
  perAccountSeries,
  perKindSeries,
  savingsRateSeries,
  twrIndexByKey,
} from "../transforms";
import type { LabelledSeries } from "../transforms";

const rangeDays = {
  "1M": 31,
  "3M": 92,
  "1Y": 365,
  "5Y": 1827,
  All: 36525,
} as const;

type RangeKey = keyof typeof rangeDays;

const rangeKeys = Object.keys(rangeDays) as RangeKey[];

export function PerformancePage(): React.JSX.Element {
  const [range, setRange] = useState<RangeKey>("1Y");

  return (
    <>
      <section className="pageIntro">
        <h1>Performance</h1>
        <p>
          Net-worth development, time- and money-weighted returns, benchmark comparison, savings
          rate, and fee drag from the analytics marts (ADR-0039).
        </p>
      </section>
      <KpiHeader />
      <TrendSection range={range} onRangeChange={setRange} />
      <ReturnsSection range={range} />
      <div className="twoColumn">
        <ContributionSection range={range} />
        <FeeDragSection />
      </div>
      <SavingsRateSection />
      <div className="twoColumn">
        <DriftSection range={range} />
        <DrilldownSection range={range} />
      </div>
    </>
  );
}

function RangeSelector({
  range,
  onRangeChange,
}: {
  readonly range: RangeKey;
  readonly onRangeChange: (range: RangeKey) => void;
}): React.JSX.Element {
  return (
    <div className="segmented" role="group" aria-label="History range">
      {rangeKeys.map((key) => (
        <button
          key={key}
          type="button"
          className={key === range ? "segmentActive" : undefined}
          aria-pressed={key === range}
          onClick={() => {
            onRangeChange(key);
          }}
        >
          {key}
        </button>
      ))}
    </div>
  );
}

function KpiHeader(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(365), limit: 1000 }), []);
  const netWorth = useNetWorthTotal(params);
  const allocation = useAllocation("kind");

  if (netWorth.isPending || allocation.isPending) {
    return <LoadingState label="key figures" />;
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="key figures"
        error={netWorth.error}
        onRetry={() => {
          void netWorth.refetch();
        }}
      />
    );
  }
  if (allocation.isError) {
    return (
      <ErrorState
        label="key figures"
        error={allocation.error}
        onRetry={() => {
          void allocation.refetch();
        }}
      />
    );
  }

  const points = netWorth.data.points;
  const latest = latestNetWorth(points);
  const momChange = monthOverMonthChange(netWorthSeries(points, "DKK"));
  const liquid = liquidShare(allocation.data.slices, liquidKinds);

  return (
    <section className="kpiRow" aria-label="Key figures">
      <KpiCard label="Net worth" tone="good">
        <MoneyPair
          dkk={latest !== null ? parseDecimal(latest.balance_dkk) : null}
          eur={latest !== null ? parseDecimal(latest.balance_eur) : null}
        />
      </KpiCard>
      <KpiCard
        label="Month over month"
        tone={momChange !== null && momChange < 0 ? "watch" : "good"}
        detail="vs. previous month end, DKK series"
      >
        {formatShare(momChange)}
      </KpiCard>
      <KpiCard
        label="Liquid share"
        tone={liquid !== null && liquid < 0.1 ? "watch" : "info"}
        detail="checking + savings + investment, EUR leg"
      >
        {formatShare(liquid)}
      </KpiCard>
    </section>
  );
}

function TrendSection({
  range,
  onRangeChange,
}: {
  readonly range: RangeKey;
  readonly onRangeChange: (range: RangeKey) => void;
}): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(rangeDays[range]), limit: 10000 }), [range]);
  const netWorth = useNetWorthTotal(params);

  if (netWorth.isPending) {
    return <LoadingState label="net-worth history" />;
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="net-worth history"
        error={netWorth.error}
        onRetry={() => {
          void netWorth.refetch();
        }}
      />
    );
  }
  if (netWorth.data.points.length === 0) {
    return <EmptyState label="net-worth history" />;
  }

  const dkkSeries = netWorthSeries(netWorth.data.points, "DKK");
  const eurSeries = netWorthSeries(netWorth.data.points, "EUR");
  const drawdown = drawdownSeries(dkkSeries);
  const deepest = maxDrawdown(dkkSeries);
  const truncated = netWorth.data.total > netWorth.data.points.length;
  const textColor = chartTextColor();

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: textColor } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 70, right: 24, top: 44, height: 216 },
      { left: 70, right: 24, top: 300, height: 80 },
    ],
    xAxis: [
      { type: "time", gridIndex: 0, axisLabel: { show: false } },
      { type: "time", gridIndex: 1, axisLabel: { color: textColor } },
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        scale: true,
        axisLabel: { color: textColor, formatter: (value: number) => formatCompact(value) },
        splitLine: { lineStyle: { opacity: 0.15 } },
      },
      {
        type: "value",
        gridIndex: 1,
        max: 0,
        splitNumber: 3,
        axisLabel: {
          color: textColor,
          formatter: (value: number) => `${(value * 100).toFixed(1)}%`,
        },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], throttle: 50 },
      { type: "slider", xAxisIndex: [0, 1], height: 24, bottom: 12 },
    ],
    series: [
      {
        name: "Net worth (DKK)",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        data: dkkSeries.map((point) => [...point]),
        areaStyle: { opacity: 0.06 },
      },
      {
        name: "Net worth (EUR)",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        data: eurSeries.map((point) => [...point]),
      },
      {
        name: "Drawdown (DKK)",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        color: "#e5484d",
        data: drawdown.map((point) => [...point]),
        areaStyle: { opacity: 0.25 },
        tooltip: { valueFormatter: (value) => formatShare(Number(value)) },
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Trend — {range === "All" ? "full history" : `last ${range}`}</p>
          <h2>Net-worth development</h2>
        </div>
        <div className="kpiRow">
          {truncated ? <span className="pill">window truncated — narrow the range</span> : null}
          <KpiCard
            label="Max drawdown"
            tone={deepest !== null && deepest < -0.1 ? "watch" : "info"}
            detail="DKK series, from running peak"
          >
            {formatShare(deepest)}
          </KpiCard>
          <RangeSelector range={range} onRangeChange={onRangeChange} />
        </div>
      </div>
      <EChart
        option={option}
        height={460}
        ariaLabel="Zoomable net worth trend in DKK and EUR with drawdown shading"
      />
    </section>
  );
}

const savingsRateWindowMonths = 3;

function SavingsRateSection(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(730), limit: 10000 }), []);
  const cashflow = useCashflowDaily(params);

  if (cashflow.isPending) {
    return <LoadingState label="cashflow" />;
  }
  if (cashflow.isError) {
    return (
      <ErrorState
        label="cashflow"
        error={cashflow.error}
        onRetry={() => {
          void cashflow.refetch();
        }}
      />
    );
  }

  const months = monthlyCashflow(cashflow.data.points);
  if (months.length === 0) {
    return <EmptyState label="cashflow" />;
  }

  const rates = savingsRateSeries(months, savingsRateWindowMonths);
  const latestRate = rates[rates.length - 1];
  const textColor = chartTextColor();

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 70, right: 70, top: 44, bottom: 36 },
    xAxis: {
      type: "category",
      data: months.map((month) => month.month),
      axisLabel: { color: textColor },
    },
    yAxis: [
      {
        type: "value",
        axisLabel: { color: textColor, formatter: (value: number) => formatCompact(value) },
        splitLine: { lineStyle: { opacity: 0.15 } },
      },
      {
        type: "value",
        axisLabel: {
          color: textColor,
          formatter: (value: number) => `${Math.round(value * 100)}%`,
        },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: "Inflow (EUR)", type: "bar", data: months.map((month) => month.inflowEur) },
      {
        name: "Outflow (EUR)",
        type: "bar",
        data: months.map((month) => -month.outflowEur),
      },
      {
        name: `Savings rate (${savingsRateWindowMonths}M rolling)`,
        type: "line",
        yAxisIndex: 1,
        showSymbol: false,
        connectNulls: false,
        data: rates.map((entry) => entry.rate),
        tooltip: { valueFormatter: (value) => formatShare(value === null ? null : Number(value)) },
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Savings rate — last 24 months</p>
          <h2>Monthly in/out and rolling savings rate (EUR leg)</h2>
        </div>
        {latestRate !== undefined ? (
          <KpiCard
            label={`Rate ${latestRate.month}`}
            tone={latestRate.rate !== null && latestRate.rate < 0 ? "watch" : "good"}
            detail={`${savingsRateWindowMonths}-month rolling window`}
          >
            {formatShare(latestRate.rate)}
          </KpiCard>
        ) : null}
      </div>
      <EChart
        option={option}
        height={300}
        ariaLabel="Monthly cashflow bars and rolling savings rate in EUR"
      />
    </section>
  );
}

function DriftSection({ range }: { readonly range: RangeKey }): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(rangeDays[range]), limit: 10000 }), [range]);
  const netWorth = useNetWorthByAccount(params);
  const accounts = useAccounts();

  if (netWorth.isPending || accounts.isPending) {
    return <LoadingState label="allocation history" />;
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="allocation history"
        error={netWorth.error}
        onRetry={() => {
          void netWorth.refetch();
        }}
      />
    );
  }
  if (accounts.isError) {
    return (
      <ErrorState
        label="allocation history"
        error={accounts.error}
        onRetry={() => {
          void accounts.refetch();
        }}
      />
    );
  }
  if (netWorth.data.points.length === 0) {
    return <EmptyState label="allocation history" />;
  }

  const history = kindWeightHistory(netWorth.data.points, accounts.data);
  const drift = allocationDrift(history, targetWeightsByKind);
  const truncated = netWorth.data.total > netWorth.data.points.length;
  const textColor = chartTextColor();

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis", valueFormatter: (value) => formatShare(Number(value)) },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 56, right: 24, top: 44, bottom: 36 },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: [...history.dates],
      axisLabel: { color: textColor },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      axisLabel: { color: textColor, formatter: (value: number) => `${Math.round(value * 100)}%` },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series: history.kinds.map((kind, index) => ({
      name: kind,
      type: "line",
      stack: "weights",
      showSymbol: false,
      sampling: "lttb",
      areaStyle: { opacity: 0.35 },
      lineStyle: { width: 1 },
      data: [...(history.weights[index] ?? [])],
    })),
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Allocation drift — EUR leg</p>
          <h2>Asset-class weights over time</h2>
        </div>
        {truncated ? <span className="pill">window truncated — narrow the range</span> : null}
      </div>
      <EChart option={option} height={260} ariaLabel="Asset-class weights over time, EUR leg" />
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">Asset kind</th>
            <th scope="col" className="num">
              Current
            </th>
            <th scope="col" className="num">
              Target
            </th>
            <th scope="col" className="num">
              Drift
            </th>
          </tr>
        </thead>
        <tbody>
          {drift.map((entry) => (
            <tr key={entry.kind}>
              <td>{entry.kind}</td>
              <td className="num">{formatShare(entry.current)}</td>
              <td className="num">{formatShare(entry.target)}</td>
              <td className="num">{formatShare(entry.drift)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="footnote">
        Targets are documented planning defaults (<code>src/config/targets.ts</code>), not a
        persisted household setting yet.
      </p>
    </section>
  );
}

type DrilldownMode = "account" | "kind";

function DrilldownSection({ range }: { readonly range: RangeKey }): React.JSX.Element {
  const [mode, setMode] = useState<DrilldownMode>("kind");
  const params = useMemo(() => ({ since: isoDaysAgo(rangeDays[range]), limit: 10000 }), [range]);
  const netWorth = useNetWorthByAccount(params);
  const accounts = useAccounts();

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Drill-down — EUR leg</p>
          <h2>Per-account and per-asset-class balances</h2>
        </div>
        <div className="segmented" role="group" aria-label="Drill-down dimension">
          <button
            type="button"
            className={mode === "kind" ? "segmentActive" : undefined}
            aria-pressed={mode === "kind"}
            onClick={() => {
              setMode("kind");
            }}
          >
            Asset class
          </button>
          <button
            type="button"
            className={mode === "account" ? "segmentActive" : undefined}
            aria-pressed={mode === "account"}
            onClick={() => {
              setMode("account");
            }}
          >
            Accounts
          </button>
        </div>
      </div>
      <DrilldownBody mode={mode} netWorth={netWorth} accounts={accounts} />
    </section>
  );
}

function DrilldownBody({
  mode,
  netWorth,
  accounts,
}: {
  readonly mode: DrilldownMode;
  readonly netWorth: ReturnType<typeof useNetWorthByAccount>;
  readonly accounts: ReturnType<typeof useAccounts>;
}): React.JSX.Element {
  if (netWorth.isPending || accounts.isPending) {
    return <LoadingState label="account balances" />;
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="account balances"
        error={netWorth.error}
        onRetry={() => {
          void netWorth.refetch();
        }}
      />
    );
  }
  if (accounts.isError) {
    return (
      <ErrorState
        label="account balances"
        error={accounts.error}
        onRetry={() => {
          void accounts.refetch();
        }}
      />
    );
  }
  if (netWorth.data.points.length === 0) {
    return <EmptyState label="account balances" />;
  }

  const series: LabelledSeries[] =
    mode === "account"
      ? perAccountSeries(netWorth.data.points, accounts.data)
      : perKindSeries(netWorth.data.points, accounts.data);
  const latestTotals = series
    .map((entry) => ({
      label: entry.label,
      latest: entry.series[entry.series.length - 1]?.[1] ?? null,
    }))
    .sort((a, b) => (b.latest ?? 0) - (a.latest ?? 0));
  const textColor = chartTextColor();

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 70, right: 24, top: 44, bottom: 36 },
    xAxis: { type: "time", axisLabel: { color: textColor } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: textColor, formatter: (value: number) => formatCompact(value) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series: series.map((entry) => ({
      name: entry.label,
      type: "line",
      showSymbol: false,
      sampling: "lttb",
      data: entry.series.map((point) => [...point]),
    })),
  };

  return (
    <>
      <EChart
        option={option}
        height={260}
        ariaLabel={`Balances over time by ${mode === "account" ? "account" : "asset class"}, EUR leg`}
      />
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">{mode === "account" ? "Account" : "Asset kind"}</th>
            <th scope="col" className="num">
              Latest (EUR)
            </th>
          </tr>
        </thead>
        <tbody>
          {latestTotals.map((entry) => (
            <tr key={entry.label}>
              <td>{entry.label}</td>
              <td className="num">
                {entry.latest !== null ? formatMoney(entry.latest, "EUR") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/* ---- v2 sections (#206) ---- */

type ReturnsScopeMode = "asset_class" | "account";

function ReturnsSection({ range }: { readonly range: RangeKey }): React.JSX.Element {
  const [scope, setScope] = useState<ReturnsScopeMode>("asset_class");
  const [benchmarkId, setBenchmarkId] = useState<string | null>(null);
  const since = isoDaysAgo(rangeDays[range]);
  const dailyParams = useMemo(() => ({ since, limit: 10000, scope }), [since, scope]);
  const summaryParams = useMemo(() => ({ since, scope: "household" as const }), [since]);
  const benchmarkParams = useMemo(() => ({ since, limit: 10000 }), [since]);

  const returns = useReturnsDaily(dailyParams);
  const summary = useReturnsSummary(summaryParams);
  const accounts = useAccounts();
  const benchmarks = useBenchmarks();
  const benchmark = useBenchmarkDaily(benchmarkId, benchmarkParams);

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Returns — {range === "All" ? "full history" : `last ${range}`}</p>
          <h2>Time-weighted return (index, start = 100)</h2>
        </div>
        <div className="kpiRow">
          <div className="segmented" role="group" aria-label="Returns scope">
            <button
              type="button"
              className={scope === "asset_class" ? "segmentActive" : undefined}
              aria-pressed={scope === "asset_class"}
              onClick={() => {
                setScope("asset_class");
              }}
            >
              Asset class
            </button>
            <button
              type="button"
              className={scope === "account" ? "segmentActive" : undefined}
              aria-pressed={scope === "account"}
              onClick={() => {
                setScope("account");
              }}
            >
              Accounts
            </button>
          </div>
          <BenchmarkPicker
            benchmarks={benchmarks.data ?? []}
            selected={benchmarkId}
            onSelect={setBenchmarkId}
          />
        </div>
      </div>
      <HouseholdSummaryCards summary={summary} />
      <ReturnsChart
        returns={returns}
        accounts={accounts}
        scope={scope}
        benchmark={benchmarkId !== null ? benchmark : null}
        benchmarkName={
          benchmarks.data?.find((entry) => entry.instrument_id === benchmarkId)?.name ?? "Benchmark"
        }
      />
      <p className="footnote">
        TWR per ADR-0039: daily factors chain-linked, external flows removed at start-of-day.
        Benchmark lines are price indexes in the instrument&apos;s native currency — growth shape
        comparison only, currency effects are not removed.
      </p>
    </section>
  );
}

function BenchmarkPicker({
  benchmarks,
  selected,
  onSelect,
}: {
  readonly benchmarks: readonly { instrument_id: string; name: string }[];
  readonly selected: string | null;
  readonly onSelect: (id: string | null) => void;
}): React.JSX.Element | null {
  if (benchmarks.length === 0) {
    return null;
  }
  return (
    <label className="fieldLabel">
      <span>Benchmark</span>
      <select
        value={selected ?? ""}
        onChange={(event) => {
          onSelect(event.target.value === "" ? null : event.target.value);
        }}
      >
        <option value="">none</option>
        {benchmarks.map((entry) => (
          <option key={entry.instrument_id} value={entry.instrument_id}>
            {entry.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function HouseholdSummaryCards({
  summary,
}: {
  readonly summary: ReturnType<typeof useReturnsSummary>;
}): React.JSX.Element | null {
  if (summary.isPending || summary.isError) {
    return null; // cards are an enhancement; the chart carries its own states
  }
  const household = summary.data.entries.find((entry) => entry.scope_key === "household");
  if (household === undefined) {
    return null;
  }
  const twrEur = parseDecimal(household.eur.cumulative_return);
  const twrDkk = parseDecimal(household.dkk.cumulative_return);
  return (
    <div className="kpiRow" aria-label="Household return summary">
      <KpiCard
        label="TWR (EUR leg)"
        tone={twrEur !== null && twrEur < 0 ? "watch" : "good"}
        detail={household.eur.error ?? `${String(household.days)} day window`}
      >
        {formatShare(twrEur)}
      </KpiCard>
      <KpiCard
        label="TWR (DKK leg)"
        tone={twrDkk !== null && twrDkk < 0 ? "watch" : "good"}
        detail={household.dkk.error ?? `${String(household.days)} day window`}
      >
        {formatShare(twrDkk)}
      </KpiCard>
      <KpiCard label="TWR annualized" tone="info" detail="EUR leg, windows ≥ 30 days only">
        {formatShare(household.eur.annualized_return)}
      </KpiCard>
      <KpiCard label="MWR / XIRR" tone="info" detail="EUR leg, money-weighted, annualized">
        {formatShare(household.eur.mwr_annualized)}
      </KpiCard>
    </div>
  );
}

function ReturnsChart({
  returns,
  accounts,
  scope,
  benchmark,
  benchmarkName,
}: {
  readonly returns: ReturnType<typeof useReturnsDaily>;
  readonly accounts: ReturnType<typeof useAccounts>;
  readonly scope: ReturnsScopeMode;
  readonly benchmark: ReturnType<typeof useBenchmarkDaily> | null;
  readonly benchmarkName: string;
}): React.JSX.Element {
  if (returns.isPending || accounts.isPending) {
    return <LoadingState label="returns" />;
  }
  if (returns.isError) {
    return (
      <ErrorState
        label="returns"
        error={returns.error}
        onRetry={() => {
          void returns.refetch();
        }}
      />
    );
  }
  if (accounts.isError) {
    return (
      <ErrorState
        label="returns"
        error={accounts.error}
        onRetry={() => {
          void accounts.refetch();
        }}
      />
    );
  }
  if (returns.data.points.length === 0) {
    return <EmptyState label="returns" />;
  }

  const labelFor =
    scope === "account"
      ? (scopeKey: string): string =>
          accounts.data.find((account) => account.account_id === scopeKey)?.name ?? scopeKey
      : (scopeKey: string): string => scopeKey;
  const lines = twrIndexByKey(returns.data.points, "EUR", labelFor);
  const truncated = returns.data.total > returns.data.points.length;
  const textColor = chartTextColor();

  const series: EChartOption["series"] = lines.map((entry) => ({
    name: entry.label,
    type: "line" as const,
    showSymbol: false,
    sampling: "lttb" as const,
    data: entry.series.map((point) => [...point]),
  }));
  if (benchmark !== null && benchmark.isSuccess && benchmark.data.points.length > 0) {
    series.push({
      name: `${benchmarkName} (price index)`,
      type: "line" as const,
      showSymbol: false,
      sampling: "lttb" as const,
      lineStyle: { type: "dashed" as const, width: 2 },
      color: "#8e8e93",
      data: benchmarkIndexSeries(benchmark.data.points).map((point) => [...point]),
    });
  }

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => (typeof value === "number" ? value.toFixed(2) : String(value)),
    },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 56, right: 24, top: 44, bottom: 36 },
    xAxis: { type: "time", axisLabel: { color: textColor } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: textColor },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series,
  };

  return (
    <>
      {truncated ? <span className="pill">window truncated — narrow the range</span> : null}
      <EChart
        option={option}
        height={320}
        ariaLabel={`Time-weighted return index per ${scope === "account" ? "account" : "asset class"}, EUR leg, with optional benchmark overlay`}
      />
    </>
  );
}

function ContributionSection({ range }: { readonly range: RangeKey }): React.JSX.Element {
  const params = useMemo(
    () => ({ since: isoDaysAgo(rangeDays[range]), limit: 10000, scope: "household" as const }),
    [range],
  );
  const returns = useReturnsDaily(params);

  if (returns.isPending) {
    return <LoadingState label="contribution decomposition" />;
  }
  if (returns.isError) {
    return (
      <ErrorState
        label="contribution decomposition"
        error={returns.error}
        onRetry={() => {
          void returns.refetch();
        }}
      />
    );
  }

  const decomposition = contributionGrowthSeries(returns.data.points, "EUR");
  if (decomposition.length === 0) {
    return <EmptyState label="contribution decomposition" />;
  }
  const latest = decomposition[decomposition.length - 1];
  const textColor = chartTextColor();

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis", valueFormatter: (value) => formatCompact(Number(value)) },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 70, right: 24, top: 44, bottom: 36 },
    xAxis: { type: "time", axisLabel: { color: textColor } },
    yAxis: {
      type: "value",
      axisLabel: { color: textColor, formatter: (value: number) => formatCompact(value) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series: [
      {
        name: "Contributions (cum.)",
        type: "line",
        showSymbol: false,
        areaStyle: { opacity: 0.12 },
        data: decomposition.map((point) => [point.date, point.flowsCum]),
      },
      {
        name: "Market growth (cum.)",
        type: "line",
        showSymbol: false,
        areaStyle: { opacity: 0.12 },
        data: decomposition.map((point) => [point.date, point.growthCum]),
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Contribution vs growth — EUR leg</p>
          <h2>What moved net worth</h2>
        </div>
        {latest !== undefined ? (
          <KpiCard
            label="Window split"
            tone="info"
            detail="external flows vs market return since window start"
          >
            {formatCompact(latest.flowsCum)} / {formatCompact(latest.growthCum)}
          </KpiCard>
        ) : null}
      </div>
      <EChart
        option={option}
        height={280}
        ariaLabel="Cumulative external flows versus cumulative market growth, EUR leg"
      />
    </section>
  );
}

function FeeDragSection(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(1827), limit: 10000 }), []);
  const fees = useFees(params);
  const netWorth = useNetWorthTotal(params);

  if (fees.isPending || netWorth.isPending) {
    return <LoadingState label="fee drag" />;
  }
  if (fees.isError) {
    return (
      <ErrorState
        label="fee drag"
        error={fees.error}
        onRetry={() => {
          void fees.refetch();
        }}
      />
    );
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="fee drag"
        error={netWorth.error}
        onRetry={() => {
          void netWorth.refetch();
        }}
      />
    );
  }

  const rows = feeDragByYear(fees.data.rows, netWorth.data.points);
  if (rows.length === 0) {
    return (
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Fee drag — last 5 years</p>
            <h2>Recorded fees per year</h2>
          </div>
        </div>
        <EmptyState label="fees" />
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Fee drag — last 5 years</p>
          <h2>Recorded fees per year</h2>
        </div>
      </div>
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">Year</th>
            <th scope="col" className="num">
              Fees (EUR)
            </th>
            <th scope="col" className="num">
              Fees (DKK)
            </th>
            <th scope="col" className="num">
              Drag
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.year}>
              <td>{row.year}</td>
              <td className="num">{formatMoney(row.feesEur, "EUR")}</td>
              <td className="num">{formatMoney(row.feesDkk, "DKK")}</td>
              <td className="num">{formatShare(row.dragShare)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="footnote">
        Fees as recorded on transactions (explicit fee bookings plus trade fee columns). Drag is the
        year&apos;s fees over that year&apos;s average net worth (EUR leg) — a planning indicator,
        not a TER.
      </p>
    </section>
  );
}
