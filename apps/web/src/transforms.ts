/** Chart-series transforms from validated API payloads to ECharts inputs. */

import { parseDecimal } from "./money";
import type { AllocationSlice, CashflowPoint, NetWorthTotalPoint } from "./api/schemas";

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
