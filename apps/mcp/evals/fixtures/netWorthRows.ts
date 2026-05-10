/**
 * Synthetic net-worth mart rows used by the golden-question harness.
 *
 * The numbers are deliberately round and trace a single date so each
 * invariant (sum-of-accounts, asset-class rollup, cross-currency
 * parity) can be expressed without floating-point bookkeeping.
 *
 * Fixed FX rate used by the cross-currency parity golden:
 *   1 EUR = 7.46 DKK   ⇒   1 DKK = 0.134048257 EUR
 *
 * `total_dkk` is the rounded image of `total_eur` at that rate so
 * both currencies agree to well within 0.5 %.
 */

export interface MartRow {
  date: string;
  breakdown_key: string | null;
  value: number;
}

const DATE = "2024-01-31";

// All accounts in the synthetic household for the date `DATE`.
//   - bank cash:           50 000 EUR
//   - brokerage portfolio: 350 000 EUR
//   - pension wrapper:     200 000 EUR
// Total household:        600 000 EUR.
export const NW_TOTAL_EUR: MartRow[] = [{ date: DATE, breakdown_key: null, value: 600_000 }];

export const NW_BY_ACCOUNT_EUR: MartRow[] = [
  { date: DATE, breakdown_key: "acct-bank-1", value: 50_000 },
  { date: DATE, breakdown_key: "acct-broker-1", value: 350_000 },
  { date: DATE, breakdown_key: "acct-pension-1", value: 200_000 },
];

export const NW_BY_ASSET_CLASS_EUR: MartRow[] = [
  { date: DATE, breakdown_key: "bank", value: 50_000 },
  { date: DATE, breakdown_key: "brokerage", value: 350_000 },
  { date: DATE, breakdown_key: "pension", value: 200_000 },
];

// 600 000 EUR × 7.46 DKK/EUR = 4 476 000 DKK.
export const NW_TOTAL_DKK: MartRow[] = [{ date: DATE, breakdown_key: null, value: 4_476_000 }];

export const NW_DATE = DATE;
export const NW_FX_EUR_PER_DKK = 1 / 7.46;
