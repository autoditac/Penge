/** Performance dashboard v1 (#204).
 *
 * Reports what `mart_net_worth_daily` and `mart_cashflow_daily` already
 * support: range-selectable net-worth trend with drawdown shading, rolling
 * savings rate, allocation drift vs configured targets, and per-account /
 * per-asset-class drill-down. TWR/MWR returns and benchmarks land with the
 * returns engine (#205) and dashboard v2 (#206).
 */

import { useMemo, useState } from "react";

import {
  useAccounts,
  useAllocation,
  useCashflowDaily,
  useNetWorthByAccount,
  useNetWorthTotal,
} from "../api/queries";
import { EChart } from "../components/EChart";
import type { EChartOption } from "../components/EChart";
import { EmptyState, ErrorState, KpiCard, LoadingState, MoneyPair } from "../components/primitives";
import { liquidKinds, targetWeightsByKind } from "../config/targets";
import { formatCompact, formatMoney, formatShare, isoDaysAgo, parseDecimal } from "../money";
import { chartPalette, chartTextColor } from "../theme";
import {
  allocationDrift,
  drawdownSeries,
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
          Net-worth development, savings rate, and allocation drift from the analytics marts.
          Time-weighted and money-weighted returns arrive with the returns engine (#205).
        </p>
      </section>
      <KpiHeader />
      <TrendSection range={range} onRangeChange={setRange} />
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
