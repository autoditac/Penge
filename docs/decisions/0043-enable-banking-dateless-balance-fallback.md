# 0043 — Enable Banking balances without a reference date: stamp with the sync date

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** @autoditac
- **Tags:** ingest

## Context and Problem Statement

Bank accounts connected through Enable Banking (GLS, Evangelische Bank,
Lunar) contributed **€0** to net worth on the dashboard, even though
their transactions imported correctly. The household expects roughly
€61k across these accounts.

`balance_to_market_value()` in
`src/penge/ingest/enablebanking/mapping.py` turns a `/balances` response
into a `(amount, valuation_date)` pair for a `holding_snapshot` row. It
derives the valuation date from the balance's `reference_date`, falling
back to the date part of `last_change_date_time`. All three ASPSPs
return valid booked balances (`CLBD`/`ITBD`, correct amounts) but with
**both** date fields `null`. With no valuation date the function
returned `None`, so the snapshot was silently dropped.

The net-worth marts (`mart_position_value_daily` →
`mart_net_worth_daily`) forward-fill `holding_snapshot` over a date
spine. An account with no snapshot is €0 everywhere. Transactions are
not summed into balances, so importing them did not help.

The original guard deliberately refused to synthesise a date, to avoid
breaking idempotency across days. But the `/balances` endpoint returns
the account's **current** balance, not a historical one, so the natural
valuation date is simply *when we read it*.

## Decision Drivers

- Accounts with a real, current balance must contribute to net worth.
- The `/balances` reading is a point-in-time "now" value; the sync date
  is a truthful valuation date for it.
- Preserve backward compatibility: existing callers and tests that rely
  on dateless balances being dropped must not silently change.
- Keep idempotency within a single day (re-running a sync converges).

## Considered Options

1. **Keep dropping dateless balances** — status quo; these accounts stay
   at €0 until the ASPSP starts sending a date (it may never).
2. **Stamp dateless balances with the sync date (today, UTC)** — the
   loader passes `datetime.now(UTC).date()` as a fallback valuation date;
   `balance_to_market_value` uses it only when the balance itself carries
   no date.
3. **Use the transaction window end (`date_to`)** — rejected: `/balances`
   returns the current balance regardless of the transaction window, so
   `date_to` would misdate the snapshot.

## Decision

We chose **Option 2**. `balance_to_market_value` gains a keyword-only
`fallback_date: date | None = None` parameter. When the preferred booked
balance has no `reference_date` and no `last_change_date_time`:

- if `fallback_date` is provided, return `(amount, fallback_date)`;
- if it is `None`, return `None` as before.

The loader (`_upsert_balance_snapshot` via `_persist`) passes
`datetime.now(UTC).date()`. Balances that *do* carry their own date are
unaffected — the payload's date always wins over the fallback.

## Consequences

### Positive

- GLS/EB/Lunar accounts now produce a `holding_snapshot` and contribute
  to net worth (~€61k previously shown as €0).
- Re-running a sync on the same UTC day converges (same `as_of`, upsert
  on `(account_id, instrument_id, as_of)`).
- Backward compatible: without a fallback the historical drop-behaviour
  is preserved, so pure-mapping callers and existing tests are unchanged.

### Negative

- Syncing the same account on two different UTC days writes two
  snapshots with different `as_of` dates for what may be the same
  underlying balance reading. This is acceptable: it reflects our
  knowledge of the current balance on each day, and the marts forward-
  fill between readings anyway.
- The stamped date is our read time, not the bank's booking time; for
  ASPSPs that omit dates we cannot do better without a new data source.

### Neutral

- No change to the `holding_snapshot` schema, the balance preference
  order, dbt marts, or tax modules.

## Links

- Code: `src/penge/ingest/enablebanking/mapping.py`
  (`balance_to_market_value`),
  `src/penge/ingest/enablebanking/loader.py`
  (`_persist`, `_upsert_balance_snapshot`)
- Docs: `docs/connectors/gls.md`,
  `docs/connectors/evangelische-bank.md`, `docs/connectors/lunar.md`
- Issue: #259
- Related: [ADR-0040](0040-in-app-enable-banking-consent-flow.md)
  (consent flow), [ADR-0041](0041-connections-sync-history-window-fallback.md)
  (history-window fallback)
