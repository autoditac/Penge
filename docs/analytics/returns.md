# Returns engine (TWR / MWR)

This page explains how Penge computes historical investment performance.
The methodology is decided in
[ADR-0039](../decisions/0039-returns-engine-twr-mwr.md).

## Architecture

The engine is split between dbt and Python:

- [`mart_position_value_daily`](../dbt.md) — forward-filled daily panel of
  every `(account, instrument)` position with EUR and DKK values.
- `mart_returns_daily` — daily begin/end market value, external net flow, and
  single-day return factor per scope, in both EUR and DKK.
- `penge.analytics.returns` — pure Python: chain-links daily factors into
  time-weighted returns (TWR) and solves money-weighted returns (MWR / XIRR).

SQL owns valuation and flow classification because that logic is relational.
Python owns chain-linking and root-finding because iteration is awkward in SQL.

## Scopes

`mart_returns_daily` has one row per `(scope, scope_key, as_of)`:

| Scope         | `scope_key`                     | External flows                                                                               |
| ------------- | ------------------------------- | -------------------------------------------------------------------------------------------- |
| `account`     | account id (text)               | `deposit`, `withdrawal`, `internal_transfer`                                                  |
| `asset_class` | instrument kind, by attribution | trades move value between classes; cash legs attributed via the account's attribution class   |
| `household`   | `'household'`                   | `deposit`, `withdrawal` only (internal transfers net out)                                     |

Scopes use deliberately different flow definitions, so per-scope returns do
**not** arithmetically compose across scopes.
Account and household returns are net of fees and taxes (costs reduce the
return; they are not treated as external flows).
Asset-class returns are a gross trading view: buys and sells move value
between classes at transaction value.

### Attribution class for instrument-less cash legs

Cash legs of trades, deposits, and withdrawals carry no `instrument_id`.
They are attributed to the account's _attribution class_: `cash` if the
account has ever snapshotted a cash position, otherwise the earliest
snapshotted instrument kind.
This handles fund-only pension accounts (for example PFA) whose contributions
are recorded without an instrument: their deposits count as flows into the
fund class instead of a phantom cash class.
`cash_interest` is cash's own return and instrument-less dividends on
non-cash-attributed accounts are the provider's return, so neither is a flow.

## Conventions

- **Start-of-day flows:** the single-day factor is
  `end_mv / (begin_mv + net_flow)`.
- `begin_mv` is the previous day's `end_mv` (zero before the first snapshot).
- The factor is `NULL` whenever `begin_mv + net_flow <= 0` — there is no
  meaningful return base on such days.
- Every calendar day is its own sub-period, so the GIPS requirement to break
  periods at external flows holds by construction.
- **FX:** identical to the net-worth mart — ECB EUR-base rates,
  forward-filled, DKK via the EUR bridge.
  EUR and DKK series are computed independently; do not mix them.

## Python engine

```python
from datetime import date
from decimal import Decimal

from penge.analytics import ReturnPoint, mwr_from_series, twr_summary

series = [
    ReturnPoint(
        as_of=date(2024, 1, 2),
        begin_value=Decimal("10000"),
        end_value=Decimal("10100"),
        net_flow=Decimal("0"),
    ),
    # ... one point per day from mart_returns_daily ...
]

summary = twr_summary(series)  # cumulative + annualized TWR
mwr = mwr_from_series(series)  # XIRR, or None if unsolvable
```

- `twr_summary` chain-links daily factors and annualizes via
  `(1 + r) ** (365.25 / days) - 1` only when the window covers at least
  30 days; shorter windows report the cumulative figure unannualized.
- Each point's daily factor is the derived property `point.factor`
  (`end_value / (begin_value + net_flow)`), `None` when no capital was
  at risk.
- Days without a factor must be dormant
  (`end_value == begin_value + net_flow` with no return base); anything else
  raises `ReturnsError` instead of silently skipping data.
- Out-of-order or gap-discontinuous series raise `ReturnsError`.
- `mwr_from_series` builds the XIRR cashflow set (initial outlay dated the day
  before the first sub-period, daily net flows, terminal value) and solves by
  bisection on the bracket `(-99.99 %, +1000 %)`.
  When net present value does not change sign over the bracket the function
  returns `None` rather than fabricating a rate.

## Limitations

- Positions are forward-filled from the latest snapshot, so returns lag
  reality between snapshots; a stale provider shows a flat line, not an error.
- The asset-class scope misstates performance on the trade day itself when
  execution price differs from the next snapshot price; it is a planning view,
  not a brokerage-grade attribution.
- Scope returns do not compose: do not expect account factors to multiply
  into the household factor.
- XIRR outside the bisection bracket (total loss, more than tenfold gain)
  returns `None` by design.
