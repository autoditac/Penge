/** Overview: net-worth trend, allocation donut, account dimension. */

import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import {
  useAccounts,
  useAllocation,
  useAllNetWorthByAccount,
  useNetWorthTotal,
} from "../api/queries";
import type { AccountSummary, AllocationDimension, NetWorthPoint } from "../api/schemas";
import { EChart } from "../components/EChart";
import type { EChartOption } from "../components/EChart";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  MoneyPair,
  PageHeader,
  Panel,
  Pill,
  SegmentedControl,
  TableScroll,
} from "../components/primitives";
import type { SegmentedOption } from "../components/primitives";
import {
  formatCompact,
  formatMoney,
  formatShare,
  formatSignedMoney,
  isoDaysAgo,
  parseDecimal,
} from "../money";
import type { Currency } from "../money";
import { chartPalette, chartTextColor } from "../theme";
import {
  accountBalanceSnapshots,
  allocationData,
  latestNetWorth,
  netWorthSeries,
  periodChange,
} from "../transforms";
import type { AccountBalanceSnapshot } from "../transforms";

const dimensionLabels: Record<AllocationDimension, string> = {
  kind: "Asset kind",
  currency: "Currency",
  entity: "Household member",
};

const dimensionOptions: readonly SegmentedOption<AllocationDimension>[] = (
  Object.keys(dimensionLabels) as AllocationDimension[]
).map((key) => ({ value: key, label: dimensionLabels[key] }));

export function OverviewPage(): React.JSX.Element {
  return (
    <>
      <PageHeader
        title="Overview"
        description="Deterministic reporting from the analytics marts. EUR and DKK stay side by side; AI explanations remain on the Planning surface."
      />
      <NetWorthSection />
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "1fr", lg: "repeat(12, minmax(0, 1fr))" },
          alignItems: "start",
        }}
      >
        <Box sx={{ gridColumn: { lg: "span 5" }, minWidth: 0 }}>
          <AllocationSection />
        </Box>
        <Box sx={{ gridColumn: { lg: "span 7" }, minWidth: 0 }}>
          <AccountsSection />
        </Box>
      </Box>
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
    <Panel
      eyebrow="Net worth — last 365 days"
      title="Household net worth"
      actions={
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
          <MetricCard label="Latest" tone="good">
            <MoneyPair
              dkk={latest !== null ? parseDecimal(latest.balance_dkk) : null}
              eur={latest !== null ? parseDecimal(latest.balance_eur) : null}
            />
          </MetricCard>
          <MetricCard
            label="Change in window"
            tone={change !== null && change < 0 ? "watch" : "good"}
            detail="DKK series"
          >
            {formatShare(change)}
          </MetricCard>
        </Stack>
      }
    >
      <EChart option={option} height={320} ariaLabel="Net worth over time in DKK and EUR" />
    </Panel>
  );
}

function AllocationSection(): React.JSX.Element {
  const [dimension, setDimension] = useState<AllocationDimension>("kind");
  const allocation = useAllocation(dimension);

  return (
    <Panel
      eyebrow="Current allocation"
      title="Where the money sits"
      actions={
        <SegmentedControl
          options={dimensionOptions}
          value={dimension}
          onChange={setDimension}
          ariaLabel="Allocation dimension"
        />
      }
    >
      <AllocationBody dimension={dimension} state={allocation} />
    </Panel>
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
      <TableScroll>
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
      </TableScroll>
    </>
  );
}

function AccountsSection(): React.JSX.Element {
  const accounts = useAccounts();
  const historyParams = useMemo(() => ({ since: isoDaysAgo(400), limit: 10_000 }), []);
  const balances = useAllNetWorthByAccount(historyParams);

  if (accounts.isPending || balances.isPending) {
    return <LoadingState label="accounts" />;
  }
  if (accounts.isError || balances.isError) {
    const error =
      accounts.error ??
      balances.error ??
      new Error("The accounts query failed without providing error details.");
    return (
      <ErrorState
        label="accounts"
        error={error}
        onRetry={() => {
          void accounts.refetch();
          void balances.refetch();
        }}
      />
    );
  }
  if (accounts.data.length === 0) {
    return <EmptyState label="accounts" />;
  }

  return (
    <Panel
      eyebrow="Accounts"
      title="Tracked accounts"
      actions={<Pill>{accounts.data.length} accounts</Pill>}
    >
      <AccountOverview accounts={accounts.data} points={balances.data.points} />
    </Panel>
  );
}

type AccountOverviewProps = {
  readonly accounts: readonly AccountSummary[];
  readonly points: readonly NetWorthPoint[];
};

function supportedCurrency(value: string): Currency | null {
  return value === "EUR" || value === "DKK" ? value : null;
}

function balanceLabel(snapshot: AccountBalanceSnapshot | undefined, currencyCode: string): string {
  if (snapshot === undefined) {
    return "—";
  }
  const currency = supportedCurrency(currencyCode);
  return currency === null
    ? `${formatCompact(snapshot.balance)} ${currencyCode}`
    : formatMoney(snapshot.balance, currency);
}

const updateDateFormat = new Intl.DateTimeFormat("en-DK", {
  dateStyle: "medium",
  timeStyle: "short",
});

function LastUpdated({
  value,
  prefix = false,
}: {
  readonly value: string | null;
  readonly prefix?: boolean;
}): React.JSX.Element {
  if (value === null) {
    return (
      <Box component="span" aria-label="Last data import unavailable" color="text.secondary">
        {prefix ? "Updated unavailable" : "—"}
      </Box>
    );
  }
  const formatted = updateDateFormat.format(new Date(value));
  return (
    <time dateTime={value} aria-label={`Last data import ${formatted}`}>
      {prefix ? `Updated ${formatted}` : formatted}
    </time>
  );
}

function DeltaValue({
  snapshot,
  currencyCode,
}: {
  readonly snapshot: AccountBalanceSnapshot | undefined;
  readonly currencyCode: string;
}): React.JSX.Element {
  if (snapshot?.monthDelta === null || snapshot === undefined) {
    return (
      <Box
        component="span"
        aria-label="Monthly change unavailable"
        sx={{ color: "text.secondary" }}
      >
        —
      </Box>
    );
  }

  const currency = supportedCurrency(currencyCode);
  const value =
    currency === null
      ? `${snapshot.monthDelta >= 0 ? "+" : ""}${formatCompact(snapshot.monthDelta)} ${currencyCode}`
      : formatSignedMoney(snapshot.monthDelta, currency);
  const direction =
    snapshot.monthDelta > 0 ? "Increased" : snapshot.monthDelta < 0 ? "Decreased" : "Unchanged";

  return (
    <Box
      component="span"
      aria-label={`${direction} by ${value} since ${snapshot.comparisonAsOf ?? "last month"}`}
      title={`Compared with ${snapshot.comparisonAsOf ?? "last month"}`}
      sx={{
        color:
          snapshot.monthDelta > 0
            ? "success.main"
            : snapshot.monthDelta < 0
              ? "error.main"
              : "text.secondary",
        fontVariantNumeric: "tabular-nums",
        fontWeight: 600,
      }}
    >
      {value}
    </Box>
  );
}

export function AccountOverview({ accounts, points }: AccountOverviewProps): React.JSX.Element {
  const snapshots = useMemo(() => accountBalanceSnapshots(points), [points]);

  return (
    <Box
      component="section"
      role="list"
      aria-label="Tracked accounts"
      sx={{
        display: "grid",
        gap: 1.25,
        gridTemplateColumns: {
          xs: "1fr",
          sm: "repeat(2, minmax(0, 1fr))",
          xl: "repeat(3, minmax(0, 1fr))",
        },
        mt: 1.5,
      }}
    >
      {accounts.map((account) => {
        const snapshot = snapshots.get(account.account_id);
        return <AccountCard key={account.account_id} account={account} snapshot={snapshot} />;
      })}
    </Box>
  );
}

function AccountCard({
  account,
  snapshot,
}: {
  readonly account: AccountSummary;
  readonly snapshot: AccountBalanceSnapshot | undefined;
}): React.JSX.Element {
  return (
    <Paper
      component="article"
      role="listitem"
      variant="outlined"
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
        minWidth: 0,
        p: 1.5,
        borderRadius: 3,
        bgcolor: "background.default",
        backgroundImage: (theme) =>
          `linear-gradient(135deg, color-mix(in srgb, ${theme.palette.primary.main} 7%, transparent), transparent 52%)`,
        boxShadow: "none",
      }}
    >
      <Stack direction="row" spacing={1.5} sx={{ justifyContent: "space-between", minWidth: 0 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            component="h3"
            title={account.name}
            sx={{
              fontSize: "0.95rem",
              fontWeight: 700,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {account.name}
          </Typography>
          <Typography
            title={account.provider}
            sx={{
              color: "text.secondary",
              fontSize: "0.78rem",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {account.provider}
          </Typography>
        </Box>
        <Box sx={{ flexShrink: 0, textAlign: "right" }}>
          <Typography
            title={snapshot ? `Balance as of ${snapshot.asOf}` : undefined}
            sx={{ fontWeight: 800, fontVariantNumeric: "tabular-nums", lineHeight: 1.25 }}
          >
            {balanceLabel(snapshot, account.currency)}
          </Typography>
          <Typography component="div" sx={{ fontSize: "0.82rem", lineHeight: 1.25 }}>
            <DeltaValue snapshot={snapshot} currencyCode={account.currency} />
          </Typography>
        </Box>
      </Stack>

      <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: "wrap" }}>
        <Chip size="small" label={account.entity_name} variant="outlined" />
        <Chip size="small" label={account.kind} variant="outlined" />
        <Chip size="small" label={account.currency} variant="outlined" />
      </Stack>

      <Box
        component="dl"
        sx={{
          display: "grid",
          gridTemplateColumns: "auto minmax(0, 1fr)",
          columnGap: 1,
          rowGap: 0.45,
          color: "text.secondary",
          fontSize: "0.76rem",
          m: 0,
          mt: "auto",
          "& dt": {
            color: "text.disabled",
            fontWeight: 700,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          },
          "& dd": {
            m: 0,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          },
        }}
      >
        <Box component="dt">IBAN</Box>
        <Box component="dd" className="mono">
          {account.iban_masked === "" ? (
            <Box component="span" aria-label="IBAN not applicable">
              —
            </Box>
          ) : (
            account.iban_masked
          )}
        </Box>
        <Box component="dt">Freshness</Box>
        <Box component="dd">
          <LastUpdated value={account.last_updated_at} prefix />
        </Box>
      </Box>
    </Paper>
  );
}
