/** Deterministic synthetic fixtures for demo mode and tests.
 *
 * Loaded only via dynamic import when `VITE_PENGE_DEMO=true`, so the fixtures
 * stay out of the production code path (issue #203). Values are invented and
 * follow the Decimal-as-string wire contract of the read API.
 */

import type {
  AccountSummary,
  AllocationDimension,
  AllocationResponse,
  CashflowSeriesResponse,
  FreshnessResponse,
  NetWorthSeriesResponse,
  NetWorthTotalSeriesResponse,
} from "../api/schemas";

export const demoAccounts: readonly AccountSummary[] = [
  {
    account_id: "acct-gls-giro",
    currency: "EUR",
    entity_id: "person-a",
    entity_name: "Person A",
    iban_masked: "****1234",
    kind: "checking",
    name: "GLS Giro ****ro",
    provider: "gls",
  },
  {
    account_id: "acct-lunar-daily",
    currency: "DKK",
    entity_id: "person-b",
    entity_name: "Person B",
    iban_masked: "****5678",
    kind: "checking",
    name: "Lunar Daily ****ly",
    provider: "lunar",
  },
  {
    account_id: "acct-nordnet-ask",
    currency: "DKK",
    entity_id: "person-b",
    entity_name: "Person B",
    iban_masked: "****9012",
    kind: "investment",
    name: "Nordnet ASK ****SK",
    provider: "nordnet",
  },
  {
    account_id: "acct-growney-depot",
    currency: "EUR",
    entity_id: "person-a",
    entity_name: "Person A",
    iban_masked: "****3456",
    kind: "investment",
    name: "Growney Depot ****ot",
    provider: "growney",
  },
];

function netWorthPoints(): NetWorthTotalSeriesResponse["points"] {
  const points: { as_of: string; balance_dkk: string | null; balance_eur: string | null }[] = [];
  const start = Date.UTC(2025, 10, 1);
  for (let day = 0; day < 180; day += 1) {
    const date = new Date(start + day * 24 * 60 * 60 * 1000);
    const drift = day * 3_100;
    const wobble = Math.round(Math.sin(day / 9) * 42_000);
    const dkk = 8_740_000 + drift + wobble;
    const eur = Math.round(dkk / 7.46);
    points.push({
      as_of: date.toISOString().slice(0, 10),
      balance_dkk: `${dkk}.0000`,
      balance_eur: `${eur}.0000`,
    });
  }
  return points;
}

export const demoNetWorthTotal: NetWorthTotalSeriesResponse = {
  limit: 1000,
  offset: 0,
  points: netWorthPoints(),
  total: 180,
};

const accountBaseEur: Readonly<Record<string, number>> = {
  "acct-gls-giro": 18_000,
  "acct-lunar-daily": 9_500,
  "acct-nordnet-ask": 310_000,
  "acct-growney-depot": 240_000,
};

function netWorthByAccountPoints(): NetWorthSeriesResponse["points"] {
  const points: NetWorthSeriesResponse["points"][number][] = [];
  const start = Date.UTC(2025, 10, 1);
  for (let day = 0; day < 180; day += 1) {
    const date = new Date(start + day * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    for (const account of demoAccounts) {
      const base = accountBaseEur[account.account_id] ?? 10_000;
      const growth = account.kind === "investment" ? day * 90 : day * 4;
      const wobble =
        account.kind === "investment" ? Math.round(Math.sin(day / 7) * 4_500) : (day % 11) * 30;
      const eur = base + growth + wobble;
      const dkk = Math.round(eur * 7.46);
      const acctCcy = account.currency === "DKK" ? dkk : eur;
      points.push({
        account_currency: account.currency,
        account_id: account.account_id,
        as_of: date,
        balance_acct_ccy: `${acctCcy}.0000`,
        balance_dkk: `${dkk}.0000`,
        balance_eur: `${eur}.0000`,
        entity_id: account.entity_id,
      });
    }
  }
  return points;
}

export const demoNetWorthByAccount: NetWorthSeriesResponse = {
  limit: 10000,
  offset: 0,
  points: netWorthByAccountPoints(),
  total: 720,
};

export const demoAllocationByKind: AllocationResponse = {
  as_of: "2026-04-29",
  by: "kind",
  slices: [
    {
      balance_dkk: "1450000.0000",
      balance_eur: "194370.0000",
      label: "checking",
      weight_eur: "0.1583",
    },
    {
      balance_dkk: "4300000.0000",
      balance_eur: "576407.0000",
      label: "pension",
      weight_eur: "0.4694",
    },
    {
      balance_dkk: "2990000.0000",
      balance_eur: "400804.0000",
      label: "investment",
      weight_eur: "0.3264",
    },
    {
      balance_dkk: "420000.0000",
      balance_eur: "56300.0000",
      label: "real_estate",
      weight_eur: "0.0459",
    },
  ],
};

function cashflowPoints(): CashflowSeriesResponse["points"] {
  const points: CashflowSeriesResponse["points"][number][] = [];
  const start = Date.UTC(2025, 2, 1);
  for (let day = 0; day < 425; day += 3) {
    const date = new Date(start + day * 24 * 60 * 60 * 1000);
    const inflow = day % 9 === 0 ? 52_000 : 1_200;
    const outflow = 9_400 + (day % 5) * 850;
    points.push({
      account_currency: "DKK",
      account_id: "acct-lunar-daily",
      as_of: date.toISOString().slice(0, 10),
      entity_id: "person-b",
      inflow_acct_ccy: `${inflow}.0000`,
      inflow_dkk: `${inflow}.0000`,
      inflow_eur: `${Math.round(inflow / 7.46)}.0000`,
      net_acct_ccy: `${inflow - outflow}.0000`,
      net_dkk: `${inflow - outflow}.0000`,
      net_eur: `${Math.round((inflow - outflow) / 7.46)}.0000`,
      outflow_acct_ccy: `${outflow}.0000`,
      outflow_dkk: `${outflow}.0000`,
      outflow_eur: `${Math.round(outflow / 7.46)}.0000`,
    });
  }
  return points;
}

export const demoCashflowDaily: CashflowSeriesResponse = {
  limit: 1000,
  offset: 0,
  points: cashflowPoints(),
  total: 142,
};

export const demoFreshness: FreshnessResponse = {
  marts: [
    { latest_as_of: "2026-04-29", mart: "mart_net_worth_daily", row_count: 48_211 },
    { latest_as_of: "2026-04-29", mart: "mart_cashflow_daily", row_count: 12_904 },
  ],
};

export function demoAllocation(by: AllocationDimension): AllocationResponse {
  if (by === "kind") {
    return demoAllocationByKind;
  }
  return {
    ...demoAllocationByKind,
    by,
    slices:
      by === "currency"
        ? [
            {
              balance_dkk: "6170000.0000",
              balance_eur: "827077.0000",
              label: "DKK",
              weight_eur: "0.6736",
            },
            {
              balance_dkk: "2990000.0000",
              balance_eur: "400804.0000",
              label: "EUR",
              weight_eur: "0.3264",
            },
          ]
        : [
            {
              balance_dkk: "5210000.0000",
              balance_eur: "698391.0000",
              label: "Person B",
              weight_eur: "0.5688",
            },
            {
              balance_dkk: "3950000.0000",
              balance_eur: "529490.0000",
              label: "Person A",
              weight_eur: "0.4312",
            },
          ],
  };
}
