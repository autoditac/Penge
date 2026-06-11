/** Performance: zoomable net-worth trend + monthly cashflow bars.
 *
 * TWR/MWR return calculations land with the returns engine (#205) and
 * dashboard v2 (#206); this page reports what the marts already support.
 */

import { useMemo } from "react";

import { useCashflowDaily, useNetWorthTotal } from "../api/queries";
import { EChart } from "../components/EChart";
import type { EChartOption } from "../components/EChart";
import { EmptyState, ErrorState, KpiCard, LoadingState } from "../components/primitives";
import { formatCompact, formatMoney, isoDaysAgo } from "../money";
import { chartPalette, chartTextColor } from "../theme";
import { monthlyCashflow, netWorthSeries } from "../transforms";

export function PerformancePage(): React.JSX.Element {
  return (
    <>
      <section className="pageIntro">
        <h1>Performance</h1>
        <p>
          Net-worth development with zoomable history and monthly cashflow. Time-weighted and
          money-weighted returns arrive with the returns engine (#205).
        </p>
      </section>
      <TrendSection />
      <CashflowSection />
    </>
  );
}

function TrendSection(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(1095), limit: 5000 }), []);
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

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: chartTextColor() } },
    grid: { left: 70, right: 24, top: 40, bottom: 76 },
    xAxis: { type: "time", axisLabel: { color: chartTextColor() } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: chartTextColor(), formatter: (value: number) => formatCompact(value) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    dataZoom: [
      { type: "inside", throttle: 50 },
      { type: "slider", height: 24, bottom: 12 },
    ],
    series: [
      {
        name: "Net worth (DKK)",
        type: "line",
        showSymbol: false,
        data: dkkSeries.map((point) => [...point]),
        areaStyle: { opacity: 0.06 },
      },
      {
        name: "Net worth (EUR)",
        type: "line",
        showSymbol: false,
        data: eurSeries.map((point) => [...point]),
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Trend — up to 3 years</p>
          <h2>Net-worth development</h2>
        </div>
        <span className="pill">{netWorth.data.points.length} daily points</span>
      </div>
      <EChart option={option} height={360} ariaLabel="Zoomable net worth trend in DKK and EUR" />
    </section>
  );
}

function CashflowSection(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(365), limit: 10000 }), []);
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

  const latest = months[months.length - 1];
  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: chartTextColor() } },
    grid: { left: 70, right: 24, top: 40, bottom: 36 },
    xAxis: {
      type: "category",
      data: months.map((month) => month.month),
      axisLabel: { color: chartTextColor() },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: chartTextColor(), formatter: (value: number) => formatCompact(value) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series: [
      { name: "Inflow (EUR)", type: "bar", data: months.map((month) => month.inflowEur) },
      {
        name: "Outflow (EUR)",
        type: "bar",
        data: months.map((month) => -month.outflowEur),
      },
      {
        name: "Net (EUR)",
        type: "line",
        showSymbol: false,
        data: months.map((month) => month.netEur),
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Cashflow — last 12 months</p>
          <h2>Monthly in/out (EUR leg)</h2>
        </div>
        {latest !== undefined ? (
          <KpiCard label={`Net ${latest.month}`} tone={latest.netEur < 0 ? "watch" : "good"}>
            {formatMoney(latest.netEur, "EUR")}
          </KpiCard>
        ) : null}
      </div>
      <EChart option={option} height={300} ariaLabel="Monthly cashflow bars in EUR" />
    </section>
  );
}
