# 0018 — Aktiesparekonto handling (flat 17 % wrapper)

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, dk

## Context and Problem Statement

The *Aktiesparekonto* (ASK) is a separate Danish tax wrapper introduced
in 2019. It taxes all holdings annually on a mark-to-market basis at a
flat 17 % rate (no progressive bands), and limits cumulative net
deposits to a yearly-indexed cap (e.g. 135 900 DKK in 2024).

Phase 3 needs:

1. A way to compute ASK tax due per account, per year.
2. A guardrail against the deposit cap so we surface user errors
   before they hit a real SKAT årsopgørelse.

## Decision

| Item | Choice |
|---|---|
| **Module** | `penge.tax.aktiesparekonto` |
| **Mechanism** | Reuse `penge.tax.lager` per ISIN, then aggregate per `(account_id, tax_year)` and apply the flat 17 % rate to the *net* gain |
| **Loss handling** | Negative aggregate gain → `tax_due = 0`, magnitude returned as `loss_carry_forward`. Cross-year carry-forward bookkeeping is the SKAT report generator's (#39) job |
| **Deposit cap** | Constants table `ASK_DEPOSIT_CAPS[year]`, function `check_deposit_cap(deposits)` walks a chronological deposit/withdrawal sequence and raises on breach |
| **Currency** | DKK only on every input/output; non-DKK raises `AskError` |
| **State** | None — calculator is a pure function; deposit cap check is also pure |

## Consequences

### Positive

- Direct reuse of the lager calculator (ADR-0017): one source of truth
  for the mark-to-market formula, ASK just supplies a different rate
  and aggregation rule.
- ASK losses net against gains *within the year* automatically because
  the 17 % rate is applied to the per-account aggregate, not per ISIN.
- Deposit-cap table is a single constant edited once a year when SKAT
  publishes the new cap. Years not in the table fail loudly.

### Negative

- Caller must keep `ASK_DEPOSIT_CAPS` in sync with SKAT's annual
  indexing announcement. Mitigated by raising `AskError` for unknown
  years — silent default would be worse.
- We do not yet model the per-day deposit cap, only the per-year cap.
  In practice the per-year aggregate is what matters for tax.

## Rejected Alternatives

- **Implement ASK as a special case inside `penge.tax.lager`.** Rejected:
  the 17 % flat-rate aggregation is materially different from the 27/42 %
  progressive bands; muxing them in lager would obscure both.
- **Store the deposit cap in the database / config file.** Rejected:
  the cap is a SKAT-published statutory number, not a user setting.
  Code change + ADR audit trail is the correct way to update it.

## References

- ADR-0017 — Lagerbeskatning calculator
- `docs/tax/dk.md` — Aktiesparekonto section
- SKAT — *Aktiesparekonto*
