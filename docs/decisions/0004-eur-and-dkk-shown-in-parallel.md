# 0004 — EUR and DKK shown in parallel; no single base currency

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** @autoditac
- **Tags:** sim, tax, web

## Context and Problem Statement

The user is a German citizen working in Denmark. Income, taxes, and
day-to-day spending are largely DKK; long-term FIRE planning, EU comparisons,
and German tax obligations are EUR. DKK is pegged to EUR within ERM II
(±2.25 % central rate), so a single "base currency" choice would either
distort tax calculations (DK reports must be in DKK to the øre) or distort
intuition for European peers and benchmarks.

## Decision Drivers

- Tax accuracy: DK SKAT and DE Finanzamt require their own currencies and
  rounding rules.
- Cognitive ergonomics: the user thinks natively in both currencies for
  different decisions.
- Clarity: never hide which currency a number is in; never compute a tax
  figure from a converted-back-and-forth value.

## Considered Options

1. **Dual-currency, parallel display** — store native currency on every fact, render dashboards and reports with EUR and DKK side-by-side, use a frozen daily ECB FX rate for cross-currency aggregates.
2. **EUR-only base currency** — convert all DKK at ingestion, recompute tax in DKK only when reporting.
3. **DKK-only base currency** — symmetric inverse of option 2.

## Decision

We chose **Option 1: dual-currency parallel display**.

Every monetary fact carries a `currency` column and the original native
amount. An `fx_rates` table (loaded daily from ECB reference rates) provides
EUR↔DKK conversions, frozen by date. Aggregations expose two columns
(`amount_eur`, `amount_dkk`) computed at the fact’s `value_date`. Tax
calculations always operate on the native-currency amounts.

## Consequences

### Positive

- Tax reports are exact in their statutory currency.
- Dashboards remain intuitive in both currencies.
- Historical FX is auditable and reproducible.

### Negative

- Every UI surface and dbt mart must handle two display columns.
- Slightly more storage (FX rates table + redundant display columns in marts).

### Neutral

- The narrow EUR/DKK peg means cross-currency drift is small but non-zero
  and we still record it.

## Alternatives in detail

### EUR-only / DKK-only

Rejected: introduces rounding error into the other jurisdiction’s tax math
and subtly biases the user’s intuition for spending and saving decisions.

## Links

- ADR-0001 (stack)
- `dbt/models/marts/mart_net_worth_daily.sql` (planned)
- ECB SDW euro reference rates
