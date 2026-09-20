/** Responsive tracked-account balance presentation.
 * @vitest-environment jsdom
 */
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AccountSummary, NetWorthPoint } from "../src/api/schemas";
import { renderWithTheme } from "./test-utils";

const useMediaQueryMock = vi.fn();

vi.mock("@mui/material/useMediaQuery", () => ({
  default: () => useMediaQueryMock(),
}));

const { AccountOverview } = await import("../src/pages/Overview");

const accounts: readonly AccountSummary[] = [
  {
    account_id: "cash",
    currency: "EUR",
    entity_id: "person-a",
    entity_name: "Person A",
    iban_masked: "••••1234",
    kind: "checking",
    last_updated_at: "2026-04-01T08:30:00Z",
    name: "Cash account",
    provider: "bank",
  },
  {
    account_id: "depot",
    currency: "DKK",
    entity_id: "person-b",
    entity_name: "Person B",
    iban_masked: "",
    kind: "investment",
    last_updated_at: null,
    name: "Investment depot",
    provider: "broker",
  },
];

function point(accountId: string, asOf: string, balance: string): NetWorthPoint {
  const account = accounts.find((candidate) => candidate.account_id === accountId);
  if (account === undefined) {
    throw new Error(`Missing synthetic account ${accountId}.`);
  }
  return {
    account_currency: account.currency,
    account_id: accountId,
    as_of: asOf,
    balance_acct_ccy: balance,
    balance_dkk: null,
    balance_eur: null,
    entity_id: account.entity_id,
  };
}

const points: readonly NetWorthPoint[] = [
  point("cash", "2026-02-28", "1000"),
  point("cash", "2026-03-31", "1250"),
  point("depot", "2026-03-31", "50000"),
];

describe("AccountOverview", () => {
  afterEach(() => {
    useMediaQueryMock.mockReset();
  });

  it("renders balances, optional IBANs, and monthly deltas in the desktop table", () => {
    useMediaQueryMock.mockReturnValue(true);
    renderWithTheme(<AccountOverview accounts={accounts} points={points} />);

    expect(screen.getByRole("table", { name: "Tracked accounts" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Provider" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Last updated" })).toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-04-01T08:30:00Z"]')).not.toBeNull();
    expect(screen.getByLabelText("Last data import unavailable")).toBeInTheDocument();
    expect(screen.getByText("••••1234")).toBeInTheDocument();
    expect(screen.getByLabelText("IBAN not applicable")).toBeInTheDocument();
    expect(screen.getByLabelText(/Increased by.*250.*since 2026-02-28/)).toBeInTheDocument();
    expect(screen.getByLabelText("Monthly change unavailable")).toBeInTheDocument();
  });

  it("uses account cards on mobile and omits an inapplicable IBAN row", () => {
    useMediaQueryMock.mockReturnValue(false);
    renderWithTheme(<AccountOverview accounts={accounts} points={points} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const articles = screen.getAllByRole("article");
    expect(articles).toHaveLength(2);
    expect(within(articles[0]!).getByText(/IBAN ••••1234/)).toBeInTheDocument();
    expect(within(articles[0]!).getByText(/^Updated /)).toBeInTheDocument();
    expect(within(articles[1]!).queryByText(/^IBAN /)).not.toBeInTheDocument();
    expect(within(articles[1]!).getByText(/50.000/)).toBeInTheDocument();
  });

  it("announces negative and unchanged monthly deltas", () => {
    useMediaQueryMock.mockReturnValue(true);
    const changedAccounts: readonly AccountSummary[] = [
      { ...accounts[0]!, account_id: "negative" },
      { ...accounts[1]!, account_id: "flat" },
    ];
    const changedPoints: readonly NetWorthPoint[] = [
      { ...point("cash", "2026-02-28", "1000"), account_id: "negative" },
      { ...point("cash", "2026-03-31", "750"), account_id: "negative" },
      { ...point("depot", "2026-02-28", "50000"), account_id: "flat" },
      { ...point("depot", "2026-03-31", "50000"), account_id: "flat" },
    ];

    renderWithTheme(<AccountOverview accounts={changedAccounts} points={changedPoints} />);

    expect(screen.getByLabelText(/Decreased by.*250.*since 2026-02-28/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Unchanged by.*0.*since 2026-02-28/)).toBeInTheDocument();
  });
});
