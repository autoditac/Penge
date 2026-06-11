/** Chart-series transforms from validated API payloads to ECharts inputs. */

import { parseDecimal } from "./money";
import type {
  AccountSummary,
  AllocationSlice,
  CashflowPoint,
  NetWorthPoint,
  NetWorthTotalPoint,
} from "./api/schemas";

export type SeriesPoint = readonly [string, number];

/** Build [date, value] pairs for one currency leg of the net-worth series. */
export function netWorthSeries(
  points: readonly NetWorthTotalPoint[],
  currency: "EUR" | "DKK",
): SeriesPoint[] {
  const series: SeriesPoint[] = [];
  for (const point of points) {
    const value = parseDecimal(currency === "EUR" ? point.balance_eur : point.balance_dkk);
    if (value !== null) {
      series.push([point.as_of, value]);
    }
  }
  return series;
}

export type AllocationDatum = {
  readonly name: string;
  readonly value: number;
  readonly share: number | null;
};

/** Donut data from allocation slices, using the EUR leg for comparability. */
export function allocationData(slices: readonly AllocationSlice[]): AllocationDatum[] {
  const data: AllocationDatum[] = [];
  for (const slice of slices) {
    const value = parseDecimal(slice.balance_eur);
    if (value !== null) {
      data.push({ name: slice.label, value, share: parseDecimal(slice.weight_eur) });
    }
  }
  return data.sort((a, b) => b.value - a.value);
}

export type MonthlyCashflow = {
  readonly month: string;
  readonly inflowEur: number;
  readonly outflowEur: number;
  readonly netEur: number;
};

/** Aggregate account-day cashflow points into calendar months (EUR leg). */
export function monthlyCashflow(points: readonly CashflowPoint[]): MonthlyCashflow[] {
  const byMonth = new Map<string, { inflow: number; outflow: number; net: number }>();
  for (const point of points) {
    const month = point.as_of.slice(0, 7);
    const bucket = byMonth.get(month) ?? { inflow: 0, outflow: 0, net: 0 };
    bucket.inflow += parseDecimal(point.inflow_eur) ?? 0;
    bucket.outflow += parseDecimal(point.outflow_eur) ?? 0;
    bucket.net += parseDecimal(point.net_eur) ?? 0;
    byMonth.set(month, bucket);
  }
  return [...byMonth.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, bucket]) => ({
      month,
      inflowEur: bucket.inflow,
      outflowEur: bucket.outflow,
      netEur: bucket.net,
    }));
}

/** Latest point of the net-worth series, or null when empty. */
export function latestNetWorth(points: readonly NetWorthTotalPoint[]): NetWorthTotalPoint | null {
  return points.length > 0 ? (points[points.length - 1] ?? null) : null;
}

/** Percentage change between the first and last value of a series, or null. */
export function periodChange(series: readonly SeriesPoint[]): number | null {
  const first = series[0];
  const last = series[series.length - 1];
  if (first === undefined || last === undefined || first[1] === 0) {
    return null;
  }
  return (last[1] - first[1]) / Math.abs(first[1]);
}

/** Running-peak drawdown per date: 0 at peaks, negative while under water. */
export function drawdownSeries(series: readonly SeriesPoint[]): SeriesPoint[] {
  const result: SeriesPoint[] = [];
  let peak = Number.NEGATIVE_INFINITY;
  for (const [date, value] of series) {
    peak = Math.max(peak, value);
    result.push([date, peak > 0 ? value / peak - 1 : 0]);
  }
  return result;
}

/** Deepest drawdown of a series (most negative value), or null when empty. */
export function maxDrawdown(series: readonly SeriesPoint[]): number | null {
  const drawdowns = drawdownSeries(series);
  if (drawdowns.length === 0) {
    return null;
  }
  return drawdowns.reduce((deepest, [, value]) => Math.min(deepest, value), 0);
}

export type SavingsRatePoint = {
  readonly month: string;
  readonly rate: number | null;
};

/** Rolling savings rate per month: (Σ inflow − Σ outflow) / Σ inflow over the
 * trailing `windowMonths` calendar months; null when the window has no inflow. */
export function savingsRateSeries(
  months: readonly MonthlyCashflow[],
  windowMonths: number,
): SavingsRatePoint[] {
  return months.map((entry, index) => {
    const window = months.slice(Math.max(0, index - windowMonths + 1), index + 1);
    const inflow = window.reduce((sum, item) => sum + item.inflowEur, 0);
    const outflow = window.reduce((sum, item) => sum + item.outflowEur, 0);
    return { month: entry.month, rate: inflow > 0 ? (inflow - outflow) / inflow : null };
  });
}

export type LabelledSeries = {
  readonly label: string;
  readonly series: SeriesPoint[];
};

function eurByDate(points: readonly NetWorthPoint[]): Map<string, Map<string, number>> {
  const byAccount = new Map<string, Map<string, number>>();
  for (const point of points) {
    const value = parseDecimal(point.balance_eur);
    if (value === null) {
      continue;
    }
    const dates = byAccount.get(point.account_id) ?? new Map<string, number>();
    dates.set(point.as_of, value);
    byAccount.set(point.account_id, dates);
  }
  return byAccount;
}

function accountLabel(accounts: readonly AccountSummary[], accountId: string): string {
  return accounts.find((account) => account.account_id === accountId)?.name ?? accountId;
}

function accountKind(accounts: readonly AccountSummary[], accountId: string): string {
  return accounts.find((account) => account.account_id === accountId)?.kind ?? "unknown";
}

/** One EUR series per account (labelled with the masked account name). */
export function perAccountSeries(
  points: readonly NetWorthPoint[],
  accounts: readonly AccountSummary[],
): LabelledSeries[] {
  const byAccount = eurByDate(points);
  return [...byAccount.entries()]
    .map(([accountId, dates]) => ({
      label: accountLabel(accounts, accountId),
      series: [...dates.entries()].sort(([a], [b]) => a.localeCompare(b)) as SeriesPoint[],
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** One EUR series per account kind (balances summed within each kind). */
export function perKindSeries(
  points: readonly NetWorthPoint[],
  accounts: readonly AccountSummary[],
): LabelledSeries[] {
  const byKind = new Map<string, Map<string, number>>();
  for (const point of points) {
    const value = parseDecimal(point.balance_eur);
    if (value === null) {
      continue;
    }
    const kind = accountKind(accounts, point.account_id);
    const dates = byKind.get(kind) ?? new Map<string, number>();
    dates.set(point.as_of, (dates.get(point.as_of) ?? 0) + value);
    byKind.set(kind, dates);
  }
  return [...byKind.entries()]
    .map(([kind, dates]) => ({
      label: kind,
      series: [...dates.entries()].sort(([a], [b]) => a.localeCompare(b)) as SeriesPoint[],
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export type KindWeightHistory = {
  readonly dates: string[];
  readonly kinds: string[];
  /** weights[kindIndex][dateIndex], each column summing to 1 (or 0 when the
   * household total for that day is not positive). */
  readonly weights: number[][];
};

/** Share of each account kind in total EUR net worth, per date. */
export function kindWeightHistory(
  points: readonly NetWorthPoint[],
  accounts: readonly AccountSummary[],
): KindWeightHistory {
  const series = perKindSeries(points, accounts);
  const dates = [...new Set(points.map((point) => point.as_of))].sort((a, b) => a.localeCompare(b));
  const kinds = series.map((entry) => entry.label);
  const valueByKindDate = series.map((entry) => new Map(entry.series));
  const weights = kinds.map(() => new Array<number>(dates.length).fill(0));
  dates.forEach((date, dateIndex) => {
    const values = valueByKindDate.map((byDate) => byDate.get(date) ?? 0);
    const total = values.reduce((sum, value) => sum + value, 0);
    if (total > 0) {
      values.forEach((value, kindIndex) => {
        const row = weights[kindIndex];
        if (row !== undefined) {
          row[dateIndex] = value / total;
        }
      });
    }
  });
  return { dates, kinds, weights };
}

export type DriftEntry = {
  readonly kind: string;
  readonly current: number;
  readonly target: number;
  readonly drift: number;
};

/** Current kind weights versus the configured targets (drift = current − target). */
export function allocationDrift(
  history: KindWeightHistory,
  targets: Readonly<Record<string, number>>,
): DriftEntry[] {
  const lastIndex = history.dates.length - 1;
  if (lastIndex < 0) {
    return [];
  }
  const kinds = [...new Set([...history.kinds, ...Object.keys(targets)])].sort((a, b) =>
    a.localeCompare(b),
  );
  return kinds.map((kind) => {
    const kindIndex = history.kinds.indexOf(kind);
    const current = kindIndex >= 0 ? (history.weights[kindIndex]?.[lastIndex] ?? 0) : 0;
    const target = targets[kind] ?? 0;
    return { kind, current, target, drift: current - target };
  });
}

/** Latest value versus the last point of the previous calendar month, or null. */
export function monthOverMonthChange(series: readonly SeriesPoint[]): number | null {
  const last = series[series.length - 1];
  if (last === undefined) {
    return null;
  }
  const currentMonth = last[0].slice(0, 7);
  let reference: SeriesPoint | undefined;
  for (const point of series) {
    if (point[0].slice(0, 7) < currentMonth) {
      reference = point;
    }
  }
  if (reference === undefined || reference[1] === 0) {
    return null;
  }
  return (last[1] - reference[1]) / Math.abs(reference[1]);
}

/** Share of the EUR total sitting in liquid account kinds, or null. */
export function liquidShare(
  slices: readonly AllocationSlice[],
  liquid: ReadonlySet<string>,
): number | null {
  let total = 0;
  let liquidTotal = 0;
  for (const slice of slices) {
    const value = parseDecimal(slice.balance_eur);
    if (value === null) {
      continue;
    }
    total += value;
    if (liquid.has(slice.label)) {
      liquidTotal += value;
    }
  }
  return total > 0 ? liquidTotal / total : null;
}
