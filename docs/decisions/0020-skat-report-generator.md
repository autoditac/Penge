# 0020 — SKAT-format report generator (DK)

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, dk, reporting

## Context and Problem Statement

Phase-3 produced four independent calculators:

- `penge.tax.lots` — gennemsnitsmetoden tax-lot tracker (#35,
  [ADR-0016](0016-tax-lot-tracker.md))
- `penge.tax.lager` — lagerbeskatning per ISIN (#36,
  [ADR-0017](0017-lagerbeskatning-calculator.md))
- `penge.tax.aktiesparekonto` — ASK 17 % wrapper (#37,
  [ADR-0018](0018-aktiesparekonto-handling.md))
- `penge.tax.pal` — PAL-skat 15.3 % (#38,
  [ADR-0019](0019-pal-skat-tracking.md))

Each emits frozen Pydantic results in DKK. To submit a Danish tax
return, those four streams have to be aggregated into a single
year-scoped artefact that:

1. fits the format the household's Steuerberater accepts (CSV is the
   common-denominator), and
2. lets every number on the filing be traced back to a source object
   for audit.

Cross-year loss carry-forward also has to live somewhere: the
calculators surface it per row but do not persist rolling state.

## Decision

Add a thin, pure module `penge.tax.report_dk` that:

- defines a frozen `SkatReportRow` (line number, category, source_id,
  account_id, ISIN, tax_year, gain DKK, tax_withheld DKK, notes),
- defines an immutable `SkatReport` dataclass holding the rows plus
  per-year totals,
- exposes `build_skat_report(...)` consuming iterables of the four
  result types plus an optional `prior_loss_carry_forward` (DKK), and
- exposes `to_csv(report)` / `to_markdown(report)` rendering helpers.

The function applies the prior-year carry-forward only against
*ordinary capital income* (lager + realised). ASK and PAL settle at
the source and are reported on their own lines with the withheld
amount; their gains do not flow into the kapitalindkomst total. Any
residual loss after netting becomes `loss_carry_forward` for the next
year's call. Persisting that rolling state is the consumer's job.

`source_id` is a stable string keyed on category + account + ISIN +
optional realisation index, e.g. `realised:nordnet:IE0000000001:7`.
Realised gains are sorted by `(event_date, account_id, isin, gain)`
before numbering so the index is deterministic regardless of the
caller's iteration order.

## Consequences

**Positive:**

- One artefact, one CSV, one markdown summary — easy to hand to the
  Steuerberater.
- Every line traces back to a source calculator output, satisfying the
  "trustworthy data platform" mandate.
- Adding a new calculator (e.g. DE Vorabpauschale, #40) is additive:
  define a new `Category` literal and a `_row_*` helper.

**Negative:**

- Carry-forward bookkeeping across years is delegated to the consumer.
  We accept this because the household ledger is the natural owner of
  rolling state; the report stays a pure function.

**Neutral:**

- The 27 % / 42 % progressive bands are *not* applied here. That is a
  household-level computation across both spouses' returns and belongs
  in a future household aggregator (out of Phase-3 scope).
