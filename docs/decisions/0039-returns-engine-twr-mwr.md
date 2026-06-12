# 0039 — Returns engine: TWR/MWR methodology and hybrid dbt + Python split

- **Status:** Proposed
- **Date:** 2026-06-12
- **Deciders:** @autoditac
- **Tags:** analytics, dbt, performance, fx

## Context and Problem Statement

Issue #205 asks for a deterministic returns engine on top of the existing
holdings/price/transaction data: time-weighted return (TWR) per account,
per asset class, and household-total, plus money-weighted return
(MWR/XIRR) per account and household. The engine must handle external
flows, EUR/DKK FX via ECB rates, and fees as recorded.

Two architectural questions need a recorded answer:

1. Where does each computation live — dbt (SQL) or Python?
2. Which return-methodology conventions apply — sub-period boundaries,
   flow timing, fee/tax treatment, FX policy, and the XIRR solver?

## Decision Drivers

- **Correct numbers first.** Conventions must be explicit, tested against
  closed-form cases, and stable across runs (no solver flakiness).
- **Reuse the existing valuation pipeline.** `mart_net_worth_daily`
  already builds the forward-filled daily valuation panel and the
  EUR/DKK FX bridge (ADR-0008); the returns engine must not invent a
  second valuation or FX path.
- **dbt-testable marts.** The issue's Definition of Done requires marts
  validated by `dbt test`.
- **XIRR is iterative.** A root solver cannot be expressed in dbt SQL.
- **No new heavy dependency.** Pulling in scipy for one `brentq` call is
  not justified; a small, well-tested bisection solver suffices.
- **EUR and DKK are both first-class** (repo rule): every return series
  must exist in both measurement currencies.

## Considered Options

1. **Pure dbt** — daily return factors *and* cumulative TWR in SQL;
   approximate MWR with Modified Dietz so SQL can do it.
2. **Pure Python** — read raw tables, build the panel, compute TWR/MWR
   entirely in Python; no new marts.
3. **Hybrid (chosen)** — dbt materializes the daily
   valuation/flow/return-factor panel as marts
   (`mart_position_value_daily`, `mart_returns_daily`); Python
   (`penge.analytics.returns`) chain-links factors over arbitrary
   windows and solves XIRR.

## Decision Outcome

Chosen option: **hybrid**, because option 1 cannot deliver true
MWR/XIRR (Modified Dietz materially diverges on large mid-period flows)
and option 2 would duplicate the forward-fill and FX logic that the dbt
layer already owns and tests.

### Mart layer

- **`mart_position_value_daily`** — the forward-filled daily panel at
  (`account_id`, `instrument_id`, `as_of`) grain, extracted from
  `mart_net_worth_daily`'s internal CTE, with the market value in
  account currency, EUR, and DKK. `mart_net_worth_daily` becomes a
  thin aggregation over this mart. Because the position mart rounds
  per-position values to 4 decimals before the net-worth sum (the old
  model converted after summing), totals can differ in the 4th decimal
  in edge cases; this is accepted so that position rows always add up
  to the account and net-worth totals.
- **`mart_returns_daily`** — daily return factors at
  (`scope`, `scope_key`, `as_of`) grain where `scope` ∈
  {`account`, `asset_class`, `household`}:
  - `account`: `scope_key` = account id; values from the position mart
    summed per account.
  - `asset_class`: `scope_key` = `instrument.kind` (e.g. `cash`,
    `fund`); values summed per kind across accounts.
  - `household`: `scope_key` = `'household'`; everything summed.
  - Columns per measurement currency (EUR and DKK): begin value, end
    value, net external flow, and the daily return factor.

### Methodology conventions

- **Daily chain-linking.** Every calendar day is a TWR sub-period, so
  the GIPS requirement to break sub-periods on external flows is
  satisfied by construction.
- **Start-of-day flow convention.** The daily factor is
  `f_t = MV_t / (MV_{t-1} + F_t)` where `F_t` is the net external flow
  dated `t` (using `coalesce(value_date, ts::date)`). This stays
  defined on the very first day of a funded account
  (`MV_0 = F_0 · f_0`). Days where `MV_{t-1} + F_t <= 0` while a flow
  or value exists yield a NULL factor; the Python layer refuses to
  chain across NULLs and reports the gap instead of fabricating a
  number.
- **External flows per scope:**
  - `account` and `household`: transaction kinds `deposit`,
    `withdrawal`, and (account scope only) `internal_transfer`, with
    the signed amount as recorded. At household scope internal
    transfers net out by construction and are excluded.
  - `asset_class`, non-cash classes: `buy`/`sell` move value between
    the cash class and the instrument's class, so the flow into the
    class is `-amount` (a buy books a negative cash amount, hence a
    positive flow into e.g. `fund`). `dividend` amounts leave the
    paying class as cash, so they count as an outflow of that class —
    this makes the class return a *total* return (price + payout).
  - `asset_class = cash`: every cash-affecting transaction **except**
    `cash_interest` is a flow (deposits, withdrawals, transfers, the
    cash legs of buys/sells/dividends, fees, taxes). Interest is the
    cash class's return.
- **Fees and taxes are not external flows** at account and household
  scope; they stay inside the return, so those series are
  **net-of-fees-and-taxes as recorded** — the return the household
  actually experiences. Asset-class series are gross trading views by
  construction (fees/taxes hit the cash class as flows); the two scopes
  deliberately answer different questions and do not compose.
- **FX policy.** Identical to `mart_net_worth_daily` (ADR-0008): ECB
  EUR-base rates, forward-filled across weekends/holidays; DKK via the
  EUR bridge. Returns are computed independently in the EUR view and
  the DKK view; they legitimately differ by the FX movement of the
  measurement currency. Flows are converted at the flow-date
  (forward-filled) rate.
- **MWR/XIRR.** Python-only, from the same mart series: the start
  value is a purchase (negative), external flows are investor
  contributions (negative) / withdrawals (positive), the end value is
  a liquidation (positive). The solver brackets the root of the NPV
  function over annualized rates in `(-0.999..., +10)` and bisects to
  convergence — deterministic, no Newton divergence, no scipy. If NPV
  has no sign change in the bracket (e.g. all flows one-signed), the
  result is `None` rather than a fabricated rate.
- **Annualization** uses actual/365.25 day count and is only reported
  for windows ≥ 30 days to avoid nonsense extrapolation.
- **Out of scope:** tax-adjusted returns (planning-grade gross/net as
  defined above only), benchmark-relative metrics (issue #206), and
  intraday effects.

### Python layer

`penge.analytics.returns` is pure and DB-free (`mypy --strict`): it
consumes value/flow series as plain data, exposes `chain_linked_twr`,
`twr_summary`, `xirr`, and `mwr_from_series`, and is property-base
tested (hypothesis) against closed-form cases plus golden fixtures.
Database access stays in the existing read-API/dbt layers.

## Consequences

- Good: one valuation/FX code path; marts stay dbt-testable; XIRR is
  exact, deterministic, and dependency-free.
- Good: `mart_net_worth_daily` consumers are unaffected (pure
  refactor, asserted by its unchanged dbt tests).
- Bad: two marts and a Python module instead of one artifact; the
  scope-dependent flow definitions must be read before interpreting
  numbers (documented in `docs/analytics/returns.md`).
- Bad: forward-filled snapshots mean a same-day deposit only shows in
  the factor once the matching snapshot lands; stale snapshots
  temporarily distort daily factors (visible, self-healing, and
  documented).
