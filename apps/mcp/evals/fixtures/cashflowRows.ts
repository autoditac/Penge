/**
 * Synthetic cashflow mart rows used by the golden-question harness.
 *
 * The fixtures pre-compute the same household's January 2024 activity
 * at three rollups (`day`, `month`, `year`) and in two currencies so
 * the harness can check that:
 *
 *   - monthly aggregation equals the sum of daily rows,
 *   - granularity rollups conserve the net total, and
 *   - the cross-currency net keeps its sign.
 *
 * Daily rows are synthesised by repeating a fixed pattern across each
 * January 2024 day so the totals are exact integers.
 */

export interface CashflowBucketRow {
  period_start: string;
  period_end: string;
  inflow: number;
  outflow: number;
  net: number;
}

const JAN_DAYS = 31;
const DAILY_INFLOW_EUR = 100;
const DAILY_OUTFLOW_EUR = 40;
const DAILY_NET_EUR = DAILY_INFLOW_EUR - DAILY_OUTFLOW_EUR;

function makeDailyRows(): CashflowBucketRow[] {
  const rows: CashflowBucketRow[] = [];
  for (let day = 1; day <= JAN_DAYS; day++) {
    const iso = `2024-01-${String(day).padStart(2, "0")}`;
    rows.push({
      period_start: iso,
      period_end: iso,
      inflow: DAILY_INFLOW_EUR,
      outflow: DAILY_OUTFLOW_EUR,
      net: DAILY_NET_EUR,
    });
  }
  return rows;
}

export const CF_DAILY_EUR: CashflowBucketRow[] = makeDailyRows();

export const CF_MONTHLY_EUR: CashflowBucketRow[] = [
  {
    period_start: "2024-01-01",
    period_end: "2024-01-31",
    inflow: DAILY_INFLOW_EUR * JAN_DAYS,
    outflow: DAILY_OUTFLOW_EUR * JAN_DAYS,
    net: DAILY_NET_EUR * JAN_DAYS,
  },
];

export const CF_YEARLY_EUR: CashflowBucketRow[] = [
  {
    period_start: "2024-01-01",
    period_end: "2024-01-31",
    inflow: DAILY_INFLOW_EUR * JAN_DAYS,
    outflow: DAILY_OUTFLOW_EUR * JAN_DAYS,
    net: DAILY_NET_EUR * JAN_DAYS,
  },
];

// Same activity in DKK at the fixed rate from the net-worth fixture.
// The sign of net must equal the sign in EUR (both positive here).
const FX_DKK_PER_EUR = 7.46;
export const CF_MONTHLY_DKK: CashflowBucketRow[] = [
  {
    period_start: "2024-01-01",
    period_end: "2024-01-31",
    inflow: Math.round(DAILY_INFLOW_EUR * JAN_DAYS * FX_DKK_PER_EUR),
    outflow: Math.round(DAILY_OUTFLOW_EUR * JAN_DAYS * FX_DKK_PER_EUR),
    net: Math.round(DAILY_NET_EUR * JAN_DAYS * FX_DKK_PER_EUR),
  },
];

export const CF_RANGE = { from: "2024-01-01", to: "2024-01-31" } as const;
export const CF_DAYS_IN_MONTH = JAN_DAYS;
export const CF_DAILY_NET_EUR = DAILY_NET_EUR;
