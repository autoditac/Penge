# 0021 — DE Vorabpauschale + Teilfreistellung calculator

- **Status:** Proposed
- **Date:** 2026-05-10
- **Deciders:** @autoditac
- **Tags:** tax, de, etf

## Context and Problem Statement

The spouse's depot at Nordnet (and any other German-domiciled
position) holds accumulating ETFs. Germany taxes the *deemed* annual
yield via the Vorabpauschale (InvStG §18) and grants a partial
exemption (Teilfreistellung, InvStG §20) depending on the fund's
asset-class classification.

The Phase-2 simulation overlay (ADR-0013) collapses both into a
single effective rate of ≈ 18.46 %. That is enough for a 10-year
projection but not enough to (a) reconcile against last year's
Steuerbescheid or (b) hand a per-ISIN report to the Steuerberater.

## Decision

Add `penge.tax.de_vorab` mirroring the Phase-3 DK calculators:

- `BASISZINS_DE: dict[int, Decimal]` — BMF-published Basiszins per
  tax year (negative values clamped to zero by the formula; this
  removes Vorabpauschale entirely in 2021/2022).
- `TEILFREISTELLUNG_QUOTES`: equity 30 %, mixed 15 %, real-estate
  60 %, other 0 %.
- `ABGELT_RATE = 0.26375` (25 % + Solidaritätszuschlag).
- `VorabInput` (frozen Pydantic, EUR-only) with ISIN, classification,
  start/end value, distributions, holding months.
- `compute_vorabpauschale(inp) → VorabResult` applying the formula:

  ```text
  basisertrag    = start_value × max(basiszins, 0) × 0.7 × months/12
  vorab          = max(basisertrag − distributions, 0)
  vorab          = min(vorab, max(end_value − start_value + distributions, 0))
  taxable        = vorab × (1 − teilfreistellung_quote)
  tax_due        = taxable × ABGELT_RATE
  ```

- `compute_vorabpauschale_many(inputs)` and `to_markdown(results)` as
  thin convenience wrappers.

## Consequences

**Positive:**

- Provides a per-ISIN auditable artefact for the Steuerberater that
  can be reconciled line-by-line against the Steuerbescheid.
- Shares the calculator pattern with `lager`, `aktiesparekonto` and
  `pal` (frozen Pydantic, EUR/DKK guards, pure functions, no I/O),
  keeping the tax package consistent and easy to extend.
- The Phase-2 overlay can later import `ABGELT_RATE` and the
  Teilfreistellung table instead of duplicating the constants.

**Negative:**

- Sparerpauschbetrag (€1 000/year) is not applied here — it is a
  household-level allowance applied at aggregation time. We accept
  this so the per-ISIN result remains a pure function.
- The Basiszins table needs a yearly manual update from BMF
  publications. We treat that as a once-a-year maintenance task.

**Neutral:**

- Vorabpauschale only triggers tax at sale (it adjusts the cost
  basis); rolling that adjustment forward is the consumer's job, the
  same way the SKAT report (#39) leaves carry-forward bookkeeping to
  the household ledger.
