/** Overview: net-worth trend, allocation donut, account dimension. */

import { useMemo, useState } from "react";

import { useAccounts, useAllocation, useNetWorthTotal } from "../api/queries";
import type { AllocationDimension } from "../api/schemas";
import { EChart } from "../components/EChart";
import type { EChartOption } from "../components/EChart";
import { EmptyState, ErrorState, KpiCard, LoadingState, MoneyPair } from "../components/primitives";
import { formatCompact, formatShare, isoDaysAgo, parseDecimal } from "../money";
import { chartPalette, chartTextColor } from "../theme";
import { allocationData, latestNetWorth, netWorthSeries, periodChange } from "../transforms";

const dimensionLabels: Record<AllocationDimension, string> = {
  kind: "Asset kind",
  currency: "Currency",
  entity: "Household member",
};

export function OverviewPage(): React.JSX.Element {
  return (
    <>
      <section className="pageIntro">
        <h1>Overview</h1>
        <p>
          Deterministic reporting from the analytics marts. EUR and DKK stay side by side; AI
          explanations remain on the Planning surface.
        </p>
      </section>
      <NetWorthSection />
      <div className="twoColumn">
        <AllocationSection />
        <AccountsSection />
      </div>
    </>
  );
}

function NetWorthSection(): React.JSX.Element {
  const params = useMemo(() => ({ since: isoDaysAgo(365) }), []);
  const netWorth = useNetWorthTotal(params);

  if (netWorth.isPending) {
    return <LoadingState label="net worth" />;
  }
  if (netWorth.isError) {
    return (
      <ErrorState
        label="net worth"
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

  const points = netWorth.data.points;
  const latest = latestNetWorth(points);
  const dkkSeries = netWorthSeries(points, "DKK");
  const eurSeries = netWorthSeries(points, "EUR");
  const change = periodChange(dkkSeries);
  const palette = chartPalette();

  const option: EChartOption = {
    color: [...palette],
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: chartTextColor() } },
    grid: { left: 70, right: 24, top: 40, bottom: 36 },
    xAxis: { type: "time", axisLabel: { color: chartTextColor() } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: chartTextColor(), formatter: (value: number) => formatCompact(value) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    series: [
      {
        name: "Net worth (DKK)",
        type: "line",
        showSymbol: false,
        smooth: true,
        data: dkkSeries.map((point) => [...point]),
        areaStyle: { opacity: 0.08 },
      },
      {
        name: "Net worth (EUR)",
        type: "line",
        showSymbol: false,
        smooth: true,
        data: eurSeries.map((point) => [...point]),
      },
    ],
  };

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Net worth — last 365 days</p>
          <h2>Household net worth</h2>
        </div>
        <div className="kpiRow">
          <KpiCard label="Latest" tone="good">
            <MoneyPair
              dkk={latest !== null ? parseDecimal(latest.balance_dkk) : null}
              eur={latest !== null ? parseDecimal(latest.balance_eur) : null}
            />
          </KpiCard>
          <KpiCard
            label="Change in window"
            tone={change !== null && change < 0 ? "watch" : "good"}
            detail="DKK series"
          >
            {formatShare(change)}
          </KpiCard>
        </div>
      </div>
      <EChart option={option} height={320} ariaLabel="Net worth over time in DKK and EUR" />
    </section>
  );
}

function AllocationSection(): React.JSX.Element {
  const [dimension, setDimension] = useState<AllocationDimension>("kind");
  const allocation = useAllocation(dimension);

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Current allocation</p>
          <h2>Where the money sits</h2>
        </div>
        <div className="segmented" role="group" aria-label="Allocation dimension">
          {(Object.keys(dimensionLabels) as AllocationDimension[]).map((key) => (
            <button
              key={key}
              type="button"
              className={key === dimension ? "segmentActive" : undefined}
              aria-pressed={key === dimension}
              onClick={() => {
                setDimension(key);
              }}
            >
              {dimensionLabels[key]}
            </button>
          ))}
        </div>
      </div>
      <AllocationBody dimension={dimension} state={allocation} />
    </section>
  );
}

function AllocationBody({
  dimension,
  state,
}: {
  readonly dimension: AllocationDimension;
  readonly state: ReturnType<typeof useAllocation>;
}): React.JSX.Element {
  if (state.isPending) {
    return <LoadingState label="allocation" />;
  }
  if (state.isError) {
    return (
      <ErrorState
        label="allocation"
        error={state.error}
        onRetry={() => {
          void state.refetch();
        }}
      />
    );
  }

  const data = allocationData(state.data.slices);
  if (data.length === 0) {
    return <EmptyState label="allocation" />;
  }

  const option: EChartOption = {
    color: [...chartPalette()],
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { color: chartTextColor() } },
    series: [
      {
        name: dimensionLabels[dimension],
        type: "pie",
        radius: ["52%", "78%"],
        center: ["50%", "44%"],
        itemStyle: { borderRadius: 6, borderWidth: 2 },
        label: { show: false },
        data: data.map((datum) => ({ name: datum.name, value: datum.value })),
      },
    ],
  };

  return (
    <>
      <EChart
        option={option}
        height={260}
        ariaLabel={`Allocation by ${dimensionLabels[dimension]} (EUR leg)`}
      />
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">{dimensionLabels[dimension]}</th>
            <th scope="col" className="num">
              Balance (EUR)
            </th>
            <th scope="col" className="num">
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((datum) => (
            <tr key={datum.name}>
              <td>{datum.name}</td>
              <td className="num">{formatCompact(datum.value)}</td>
              <td className="num">{formatShare(datum.share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function AccountsSection(): React.JSX.Element {
  const accounts = useAccounts();

  if (accounts.isPending) {
    return <LoadingState label="accounts" />;
  }
  if (accounts.isError) {
    return (
      <ErrorState
        label="accounts"
        error={accounts.error}
        onRetry={() => {
          void accounts.refetch();
        }}
      />
    );
  }
  if (accounts.data.length === 0) {
    return <EmptyState label="accounts" />;
  }

  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Accounts</p>
          <h2>Tracked accounts</h2>
        </div>
        <span className="pill">{accounts.data.length} accounts</span>
      </div>
      <table className="dataTable">
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col">Owner</th>
            <th scope="col">Provider</th>
            <th scope="col">Kind</th>
            <th scope="col">CCY</th>
            <th scope="col">IBAN</th>
          </tr>
        </thead>
        <tbody>
          {accounts.data.map((account) => (
            <tr key={account.account_id}>
              <td>{account.name}</td>
              <td>{account.entity_name}</td>
              <td>{account.provider}</td>
              <td>{account.kind}</td>
              <td>{account.currency}</td>
              <td className="mono">{account.iban_masked}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
