/**
 * Synthetic staged import rows for the `suggest_import_mapping` golden
 * questions. Mirrors the payload shapes produced by
 * `penge.api.imports.staging` for Nordnet transaction CSVs — entirely
 * synthetic values, never copied from a real statement.
 */

export const IMPORT_SESSION_ID = "0b6c1a52-9d9e-4f7d-8a8e-2f5c6d7e8f90";

export const IMPORT_SESSION_ROW = {
  id: IMPORT_SESSION_ID,
  source: "nordnet_transactions",
  status: "staged",
};

/** One buy, one dividend, one internal transfer with an account number in free text. */
export const IMPORT_ROWS: ReadonlyArray<Record<string, unknown>> = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    row_index: 0,
    kind: "transaction",
    payload: {
      nordnet_id: "900000001",
      canonical_kind: "buy",
      instrument_name: "iShares   Core MSCI World UCITS ETF",
      isin: "IE00B4L5Y983",
      amount: "-1000.00",
      amount_currency: "DKK",
      text: "KØBT 10 stk",
    },
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    row_index: 1,
    kind: "transaction",
    payload: {
      nordnet_id: "900000002",
      canonical_kind: "dividend",
      instrument_name: "Vanguard FTSE All-World UCITS ETF",
      amount: "42.50",
      amount_currency: "DKK",
      text: "UDBYTTE",
    },
  },
  {
    id: "33333333-3333-4333-8333-333333333333",
    row_index: 2,
    kind: "transaction",
    payload: {
      nordnet_id: "900000003",
      canonical_kind: "internal_transfer",
      amount: "500.00",
      amount_currency: "DKK",
      text: "Internal from 60109543",
      counter_account: "60109543",
    },
  },
];

/** Expected category values keyed by row id (canonical-kind rule, 0.9). */
export const EXPECTED_CATEGORIES: Readonly<Record<string, string>> = {
  "11111111-1111-4111-8111-111111111111": "investment.trade.buy",
  "22222222-2222-4222-8222-222222222222": "investment.income.dividend",
  "33333333-3333-4333-8333-333333333333": "transfer.internal",
};
